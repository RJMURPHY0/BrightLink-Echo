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
drives the native tools: taskkill.exe, sc.exe and tasklist.exe.
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
HELPER_ARG = "--restart-audio-engine"

_SERVICE = "Audiosrv"
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW

_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_NOASYNC = 0x00000100
_SEE_MASK_FLAG_NO_UI = 0x00000400  # no Windows error dialog if it can't start
_SW_HIDE = 0
_WAIT_OBJECT_0 = 0


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


def _tool(name: str) -> str:
    """Full System32 path of a Windows tool. The elevated copy runs as admin,
    and a bare name would be searched for in Echo's own (user-writable) folder
    first, so a planted sc.exe there would run elevated."""
    return os.path.join(os.environ.get("SystemRoot") or r"C:\Windows",
                        "System32", name)


def _run(args: list, timeout: float = 15.0) -> str:
    """stdout of a windowless native tool, or "" when it could not run.
    errors="replace": tasklist and sc print localised text on some machines."""
    try:
        return subprocess.run(
            args, capture_output=True, text=True, errors="replace",
            timeout=timeout, creationflags=_NO_WINDOW,
        ).stdout or ""
    except Exception as e:
        print(f"[AudioEngine] {os.path.basename(args[0])} failed: {e}")
        return ""


def _sc_state(out: str):
    """'RUNNING', 'STOPPED', 'START_PENDING'... from `sc.exe query` output,
    or None when there is no STATE line."""
    for line in (out or "").splitlines():
        key, _, value = line.partition(":")
        if key.strip().upper() == "STATE":
            parts = value.split()
            return parts[1].upper() if len(parts) >= 2 else None
    return None


def service_running(timeout: float = 5.0) -> bool:
    """True when the Windows Audio service reports RUNNING. Needs no admin.
    Any failure to ask counts as running, so a broken query never escalates a
    healthy machine."""
    if sys.platform != "win32":
        return True
    try:
        out = subprocess.run(
            [_tool("sc.exe"), "query", _SERVICE], capture_output=True, text=True,
            timeout=timeout, creationflags=_NO_WINDOW,
        ).stdout
    except Exception as e:
        print(f"[AudioEngine] Service query failed: {e}")
        return True
    state = _sc_state(out)
    return True if state is None else state == "RUNNING"


def _service_pid() -> int:
    for line in _run([_tool("sc.exe"), "queryex", _SERVICE]).splitlines():
        key, _, value = line.partition(":")
        if key.strip().upper() == "PID":
            try:
                return int(value.strip())
            except ValueError:
                return 0
    return 0


def _services_in(pid: int) -> list:
    """Names of the services hosted by process *pid* (tasklist /svc)."""
    out = _run([_tool("tasklist.exe"), "/svc", "/fo", "csv", "/nh",
                "/fi", f"PID eq {pid}"])
    for row in csv.reader(out.splitlines()):
        if len(row) >= 3 and row[1].strip() == str(pid):
            return [s.strip() for s in row[2].split(",")
                    if s.strip() and s.strip().upper() != "N/A"]
    return []


def _wait_for(state: str, tries: int = 40, interval: float = 0.25) -> bool:
    for _ in range(tries):
        if _sc_state(_run([_tool("sc.exe"), "query", _SERVICE])) == state:
            return True
        time.sleep(interval)
    return _sc_state(_run([_tool("sc.exe"), "query", _SERVICE])) == state


def restart_elevated() -> int:
    """The half that runs as admin, inside the windowless frozen exe. Never
    raises: an uncaught error there would show PyInstaller's error dialog."""
    try:
        return _restart_elevated()
    except Exception as e:
        print(f"[AudioEngine] Elevated restart failed: {e}")
        return HELPER_ERROR


def _restart_elevated() -> int:
    """audiodg.exe is killed explicitly because a
    hung one can outlive its service (it did on 2026-10-05), and a fresh
    Audiosrv then hands every new stream to the corpse. A hung service can also
    ignore a stop request, so its host process is killed instead, but only when
    that svchost hosts Audiosrv alone (low-RAM machines share hosts between
    services). Anything unreadable takes the gentle path: a stop request."""
    _run([_tool("taskkill.exe"), "/F", "/IM", "audiodg.exe"])
    pid = _service_pid()
    if pid > 0:
        if [s.upper() for s in _services_in(pid)] == [_SERVICE.upper()]:
            _run([_tool("taskkill.exe"), "/F", "/PID", str(pid)])
        else:
            _run([_tool("sc.exe"), "stop", _SERVICE])
    # A service that never stopped was never restarted: it still reads RUNNING
    # below, which would otherwise report success for a restart that did not
    # happen (Codex review 2026-10-06).
    if not _wait_for("STOPPED"):
        return NOT_STOPPED
    _run([_tool("sc.exe"), "start", _SERVICE])
    return RESTARTED if _wait_for("RUNNING") else NOT_STARTED


def _helper_command():
    """(program, args) that starts a copy of Echo running restart_elevated()."""
    if getattr(sys, "frozen", False):
        return sys.executable, [HELPER_ARG]
    # From source: pythonw, so the elevated copy has no console window.
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return (pyw if os.path.exists(pyw) else exe), [os.path.abspath(__file__), HELPER_ARG]


def _shell_execute(verb: str, file: str, params: str, timeout: float) -> int:
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
    info.lpVerb = verb
    info.lpFile = file
    info.lpParameters = params
    info.nShow = _SW_HIDE
    try:
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            err = ctypes.get_last_error()
            if err == CANCELLED:
                return CANCELLED
            print(f"[AudioEngine] Could not start the restart (error {err}).")
            return 1
        if not info.hProcess:
            print("[AudioEngine] The restart started without a process handle.")
            return 1
        try:
            ms = max(0, int(timeout * 1000))
            if kernel32.WaitForSingleObject(info.hProcess, ms) != _WAIT_OBJECT_0:
                print("[AudioEngine] The restart did not finish in time.")
                return 1
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
                print(f"[AudioEngine] No exit code ({ctypes.get_last_error()}).")
                return 1
            return code.value
        finally:
            kernel32.CloseHandle(info.hProcess)
    finally:
        if com:
            ole32.CoUninitialize()


def restart(timeout: float = 300.0) -> int:
    """Kill the hung audio engine and restart Windows Audio, via one UAC
    prompt. Blocks until done; call it off the UI thread. Returns RESTARTED,
    CANCELLED, or another non-zero code on failure."""
    if sys.platform != "win32":
        return 1
    program, args = _helper_command()
    params = subprocess.list2cmdline(args)
    result = []

    def _go():
        try:
            result.append(_shell_execute("runas", program, params, timeout))
        except Exception as e:
            print(f"[AudioEngine] Restart failed to launch: {e}")
            result.append(1)

    # ShellExecuteExW blocks while the UAC prompt is up, and that prompt never
    # times out on its own, so the deadline is kept here.
    t = threading.Thread(target=_go, daemon=True, name="audio-engine-uac")
    t.start()
    t.join(timeout)
    if not result:
        print("[AudioEngine] Restart timed out waiting for the UAC prompt.")
        return CANCELLED
    return result[0]


if __name__ == "__main__":
    # Source runs: restart() elevates `python audio_engine.py HELPER_ARG`.
    sys.exit(restart_elevated() if HELPER_ARG in sys.argv[1:] else 1)
