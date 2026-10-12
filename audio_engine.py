"""
Windows audio engine health and recovery.

When the Windows audio engine (audiodg.exe under the Audiosrv service) hangs,
every app gets an open input stream that carries nothing, and no amount of
reopening our own stream helps (observed 2026-10-05: five dead dictations in a
row, then Windows killed Audiosrv for hanging while the hung audiodg.exe lived
on). The only cure is killing audiodg.exe and restarting Audiosrv, which needs
admin rights, so restart() asks once through the normal Windows UAC prompt.

No PowerShell (2026-10-12): the first version ran an encoded, hidden,
elevated PowerShell script that stopped a service, and Avast Behavior Shield
killed it as IDP.HELU.PSE94. Customers' antivirus scores the same tokens. Now
Echo starts ITSELF elevated (ShellExecuteExW "runas", HELPER_ARG) and that copy
talks to the Service Control Manager directly, plus System32 taskkill.exe and
tasklist.exe. Service state and process id come back as numbers, never as
sc.exe text, whose labels are translated on non-English Windows.
"""

import csv
import ctypes
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes

# Exit codes from restart(): 0 = restarted, 1223 = the user declined the UAC
# prompt (ERROR_CANCELLED), anything else = the restart itself failed.
RESTARTED = 0
CANCELLED = 1223
NOT_STARTED = 2  # stopped, but never came back up
NOT_STOPPED = 3  # never stopped, so it was never restarted
HELPER_ERROR = 4  # the elevated copy hit an unexpected error

# The elevated copy of Echo runs restart_elevated() and exits with its code.
# app.py checks for it before any heavy import or the single-instance mutex.
# An optional second argument is a log file for the elevated copy's errors:
# a windowless build has nowhere else to put them.
HELPER_ARG = "--restart-audio-engine"

_SERVICE = "Audiosrv"
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW

_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_NOASYNC = 0x00000100
_SEE_MASK_FLAG_NO_UI = 0x00000400  # no Windows error dialog if it can't start
_SW_HIDE = 0
_WAIT_OBJECT_0 = 0

# Service Control Manager (winsvc.h)
_SC_MANAGER_CONNECT = 0x0001
_SERVICE_QUERY_STATUS = 0x0004
_SERVICE_ENUMERATE_DEPENDENTS = 0x0008
_SERVICE_START = 0x0010
_SERVICE_STOP = 0x0020
_SC_STATUS_PROCESS_INFO = 0
_SERVICE_CONTROL_STOP = 0x00000001
_SERVICE_ACTIVE = 0x00000001
_ERROR_MORE_DATA = 234
_ERROR_SERVICE_ALREADY_RUNNING = 1056
_ERROR_SERVICE_NOT_ACTIVE = 1062

STOPPED = 1
START_PENDING = 2
STOP_PENDING = 3
RUNNING = 4


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


class _SERVICE_STATUS(ctypes.Structure):
    _fields_ = [(n, wintypes.DWORD) for n in (
        "dwServiceType", "dwCurrentState", "dwControlsAccepted", "dwWin32ExitCode",
        "dwServiceSpecificExitCode", "dwCheckPoint", "dwWaitHint")]


class _SERVICE_STATUS_PROCESS(ctypes.Structure):
    _fields_ = [(n, wintypes.DWORD) for n in (
        "dwServiceType", "dwCurrentState", "dwControlsAccepted", "dwWin32ExitCode",
        "dwServiceSpecificExitCode", "dwCheckPoint", "dwWaitHint", "dwProcessId",
        "dwServiceFlags")]


class _ENUM_SERVICE_STATUSW(ctypes.Structure):
    _fields_ = [("lpServiceName", wintypes.LPWSTR),
                ("lpDisplayName", wintypes.LPWSTR),
                ("ServiceStatus", _SERVICE_STATUS)]


def _log(log_path: str, msg: str) -> None:
    """Print, and append to *log_path* when there is one: the elevated copy is
    windowless, so its stdout goes nowhere."""
    print(f"[AudioEngine] {msg}")
    if not log_path:
        return
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Audio engine: {msg}\n")
    except OSError as e:
        print(f"[AudioEngine] Could not write {log_path}: {e}")


def _tool(name: str) -> str:
    """Full System32 path of a Windows tool. The elevated copy runs as admin,
    and a bare name would be searched for in Echo's own (user-writable) folder
    first, so a planted taskkill.exe there would run elevated."""
    return os.path.join(os.environ.get("SystemRoot") or r"C:\Windows",
                        "System32", name)


def _run(args: list, log_path: str = "", timeout: float = 15.0) -> str:
    """stdout of a windowless native tool, or "" when it could not run.
    errors="replace": tasklist prints localised text on some machines."""
    try:
        return subprocess.run(
            args, capture_output=True, text=True, errors="replace",
            timeout=timeout, creationflags=_NO_WINDOW,
        ).stdout or ""
    except Exception as e:
        _log(log_path, f"{os.path.basename(args[0])} failed: {e}")
        return ""


# ------------------------------------------------------- Service Control Manager

def _advapi():
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    h = ctypes.c_void_p
    a.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    a.OpenSCManagerW.restype = h
    a.OpenServiceW.argtypes = [h, wintypes.LPCWSTR, wintypes.DWORD]
    a.OpenServiceW.restype = h
    a.CloseServiceHandle.argtypes = [h]
    a.CloseServiceHandle.restype = wintypes.BOOL
    a.QueryServiceStatusEx.argtypes = [h, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.DWORD)]
    a.QueryServiceStatusEx.restype = wintypes.BOOL
    a.ControlService.argtypes = [h, wintypes.DWORD, ctypes.POINTER(_SERVICE_STATUS)]
    a.ControlService.restype = wintypes.BOOL
    a.StartServiceW.argtypes = [h, wintypes.DWORD, ctypes.c_void_p]
    a.StartServiceW.restype = wintypes.BOOL
    a.EnumDependentServicesW.argtypes = [h, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD),
                                         ctypes.POINTER(wintypes.DWORD)]
    a.EnumDependentServicesW.restype = wintypes.BOOL
    return a


class _Service:
    """An open service handle. Raises OSError when it cannot be opened."""

    def __init__(self, name: str, access: int):
        self.a = _advapi()
        self.scm = self.a.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
        if not self.scm:
            raise ctypes.WinError(ctypes.get_last_error())
        self.h = self.a.OpenServiceW(self.scm, name, access)
        if not self.h:
            err = ctypes.get_last_error()
            self.a.CloseServiceHandle(self.scm)
            raise ctypes.WinError(err)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.a.CloseServiceHandle(self.h)
        self.a.CloseServiceHandle(self.scm)


def _status(name: str) -> tuple:
    """(state, process id) of service *name*. Raises OSError on failure."""
    with _Service(name, _SERVICE_QUERY_STATUS) as s:
        st = _SERVICE_STATUS_PROCESS()
        need = wintypes.DWORD()
        if not s.a.QueryServiceStatusEx(s.h, _SC_STATUS_PROCESS_INFO, ctypes.byref(st),
                                        ctypes.sizeof(st), ctypes.byref(need)):
            raise ctypes.WinError(ctypes.get_last_error())
        return st.dwCurrentState, st.dwProcessId


def _stop(name: str) -> int:
    """Ask service *name* to stop without waiting. 0 or a Windows error code."""
    with _Service(name, _SERVICE_STOP) as s:
        st = _SERVICE_STATUS()
        return 0 if s.a.ControlService(s.h, _SERVICE_CONTROL_STOP, ctypes.byref(st)) \
            else ctypes.get_last_error()


def _start(name: str) -> int:
    """Start service *name* without waiting. 0 (also when it already runs) or
    a Windows error code."""
    with _Service(name, _SERVICE_START) as s:
        if s.a.StartServiceW(s.h, 0, None):
            return 0
        err = ctypes.get_last_error()
        return 0 if err == _ERROR_SERVICE_ALREADY_RUNNING else err


def _running_dependents(name: str) -> list:
    """Names of the running services that depend on *name*, in the order
    Windows stops them (dependents of dependents first)."""
    with _Service(name, _SERVICE_ENUMERATE_DEPENDENTS) as s:
        need, count = wintypes.DWORD(), wintypes.DWORD()
        if s.a.EnumDependentServicesW(s.h, _SERVICE_ACTIVE, None, 0,
                                      ctypes.byref(need), ctypes.byref(count)):
            return []
        err = ctypes.get_last_error()
        if err != _ERROR_MORE_DATA:
            raise ctypes.WinError(err)
        buf = ctypes.create_string_buffer(need.value)
        if not s.a.EnumDependentServicesW(s.h, _SERVICE_ACTIVE, buf, need.value,
                                          ctypes.byref(need), ctypes.byref(count)):
            raise ctypes.WinError(ctypes.get_last_error())
        items = ctypes.cast(buf, ctypes.POINTER(_ENUM_SERVICE_STATUSW))
        return [items[i].lpServiceName for i in range(count.value)]


def service_running(timeout: float = 5.0) -> bool:
    """True when the Windows Audio service reports RUNNING. Needs no admin.
    Any failure to ask counts as running, so a broken query never escalates a
    healthy machine."""
    if sys.platform != "win32":
        return True
    try:
        state, _ = _status(_SERVICE)
    except Exception as e:
        print(f"[AudioEngine] Service query failed: {e}")
        return True
    return state == RUNNING


# ---------------------------------------------------------------- elevated half

def _services_in(pid: int, log_path: str = "") -> list:
    """Names of the services hosted by process *pid* (tasklist /svc)."""
    out = _run([_tool("tasklist.exe"), "/svc", "/fo", "csv", "/nh",
                "/fi", f"PID eq {pid}"], log_path)
    for row in csv.reader(out.splitlines()):
        if len(row) >= 3 and row[1].strip() == str(pid):
            return [s.strip() for s in row[2].split(",")
                    if s.strip() and s.strip().upper() != "N/A"]
    return []


def _state_of(name: str) -> int:
    try:
        return _status(name)[0]
    except Exception:
        return 0


def _wait_for(name: str, state: int, tries: int = 40, interval: float = 0.25) -> bool:
    for _ in range(tries):
        if _state_of(name) == state:
            return True
        time.sleep(interval)
    return _state_of(name) == state


def _start_all(names: list, log_path: str) -> None:
    for name in names:
        try:
            err = _start(name)
        except Exception as e:
            err = e
        if err:
            _log(log_path, f"could not start {name}: {err}")


def restart_elevated(log_path: str = "") -> int:
    """The half that runs as admin, inside the windowless frozen exe. Never
    raises: an uncaught error there would show PyInstaller's error dialog."""
    try:
        return _restart_elevated(log_path)
    except Exception as e:
        _log(log_path, f"elevated restart failed: {e}")
        return HELPER_ERROR


def _restart_elevated(log_path: str = "") -> int:
    """audiodg.exe is killed explicitly because a hung one can outlive its
    service (it did on 2026-10-05), and a fresh Audiosrv then hands every new
    stream to the corpse. A hung service can also ignore a stop request, so its
    host process is killed instead, but only when that svchost hosts Audiosrv
    alone (low-RAM machines share hosts between services). Anything unreadable
    takes the gentle path: a stop request, after stopping the services that
    depend on Audiosrv (a Realtek one often does), since Windows refuses to
    stop a service while a dependent runs. Everything that was running is
    started again, whatever happens."""
    _run([_tool("taskkill.exe"), "/F", "/IM", "audiodg.exe"], log_path)
    try:
        dependents = _running_dependents(_SERVICE)
    except Exception as e:
        _log(log_path, f"could not list dependent services: {e}")
        dependents = []
    try:
        state, pid = _status(_SERVICE)
    except Exception as e:
        _log(log_path, f"could not read {_SERVICE}: {e}")
        state, pid = 0, 0

    if pid > 0 and [s.upper() for s in _services_in(pid, log_path)] == [_SERVICE.upper()]:
        _run([_tool("taskkill.exe"), "/F", "/PID", str(pid)], log_path)
    elif state != STOPPED:
        for name in dependents:
            try:
                err = _stop(name)
            except Exception as e:
                err = e
            if err and err != _ERROR_SERVICE_NOT_ACTIVE:
                _log(log_path, f"could not stop {name}: {err}")
        for name in dependents:
            _wait_for(name, STOPPED, tries=20)
        try:
            err = _stop(_SERVICE)
        except Exception as e:
            err = e
        if err and err != _ERROR_SERVICE_NOT_ACTIVE:
            _log(log_path, f"could not stop {_SERVICE}: {err}")

    # A service that never stopped was never restarted: it still reads RUNNING
    # below, which would otherwise report success for a restart that did not
    # happen (Codex review 2026-10-06). Start it anyway, so a host we killed or
    # a dependent we stopped is never left down.
    if not _wait_for(_SERVICE, STOPPED):
        _start_all([_SERVICE] + dependents[::-1], log_path)
        return NOT_STOPPED
    _start_all([_SERVICE], log_path)
    up = _wait_for(_SERVICE, RUNNING)
    _start_all(dependents[::-1], log_path)
    return RESTARTED if up else NOT_STARTED


# ---------------------------------------------------------------- caller half

def _helper_command():
    """(program, args) that starts a copy of Echo running restart_elevated()."""
    if getattr(sys, "frozen", False):
        return sys.executable, [HELPER_ARG]
    # From source: pythonw, so the elevated copy has no console window.
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return (pyw if os.path.exists(pyw) else exe), [os.path.abspath(__file__), HELPER_ARG]


def _owner_window():
    """Echo's own foreground window, so the UAC prompt opens in front of it
    rather than as a flashing taskbar button. None when another app is in
    front."""
    try:
        user32 = ctypes.WinDLL("user32")
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                    ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        hwnd = user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        if hwnd and user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) \
                and pid.value == os.getpid():
            return hwnd
    except Exception as e:
        print(f"[AudioEngine] No owner window: {e}")
    return None


def _shell_execute(verb: str, file: str, params: str, timeout: float,
                   hwnd=None, log_path: str = "") -> int:
    """Start *file* hidden through ShellExecuteExW and wait for it. Returns its
    exit code, CANCELLED when the user says No to the UAC prompt, or 1 when it
    could not start or did not finish within *timeout* seconds."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32")
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                            ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long

    # Microsoft's advice for ShellExecuteEx: an STA with OLE1 DDE off.
    com = ole32.CoInitializeEx(None, 0x2 | 0x4) >= 0
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_NOASYNC | _SEE_MASK_FLAG_NO_UI
    info.hwnd = hwnd
    info.lpVerb = verb
    info.lpFile = file
    info.lpParameters = params
    info.nShow = _SW_HIDE
    try:
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            err = ctypes.get_last_error()
            if err == CANCELLED:
                return CANCELLED
            _log(log_path, f"could not start the restart (error {err})")
            return 1
        if not info.hProcess:
            _log(log_path, "the restart started without a process handle")
            return 1
        try:
            ms = max(0, int(timeout * 1000))
            if kernel32.WaitForSingleObject(info.hProcess, ms) != _WAIT_OBJECT_0:
                _log(log_path, "the restart did not finish in time")
                return 1
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
                _log(log_path, f"no exit code ({ctypes.get_last_error()})")
                return 1
            return code.value
        finally:
            kernel32.CloseHandle(info.hProcess)
    finally:
        if com:
            ole32.CoUninitialize()


# One prompt at a time: a restart that outlived its caller's deadline (UAC
# prompt still open, or a late Yes still running) is joined by the next call
# instead of a second prompt or a second elevated copy racing the first.
_pending_lock = threading.Lock()
_pending = None  # (thread, result list)


def restart(timeout: float = 300.0, log_path: str = "") -> int:
    """Kill the hung audio engine and restart Windows Audio, via one UAC
    prompt. Blocks until done; call it off the UI thread. Returns RESTARTED,
    CANCELLED, or another non-zero code on failure. *log_path* collects what
    went wrong, from both halves."""
    global _pending
    if sys.platform != "win32":
        return 1
    with _pending_lock:
        if _pending is not None and _pending[0].is_alive():
            worker, result = _pending
        else:
            program, args = _helper_command()
            params = subprocess.list2cmdline(args + ([log_path] if log_path else []))
            hwnd = _owner_window()
            result = []

            def _go():
                try:
                    result.append(_shell_execute("runas", program, params, timeout,
                                                 hwnd=hwnd, log_path=log_path))
                except Exception as e:
                    _log(log_path, f"restart failed to launch: {e}")
                    result.append(1)

            # ShellExecuteExW blocks while the UAC prompt is up, and that prompt
            # never times out on its own, so the deadline is kept here.
            worker = threading.Thread(target=_go, daemon=True, name="audio-engine-uac")
            worker.start()
            _pending = (worker, result)
    worker.join(timeout)
    if not result:
        _log(log_path, "restart timed out waiting for the UAC prompt")
        return CANCELLED
    return result[0]


if __name__ == "__main__":
    # Source runs: restart() elevates `pythonw audio_engine.py HELPER_ARG [log]`.
    if HELPER_ARG in sys.argv[1:]:
        i = sys.argv.index(HELPER_ARG)
        sys.exit(restart_elevated(sys.argv[i + 1] if len(sys.argv) > i + 1 else ""))
    sys.exit(1)
