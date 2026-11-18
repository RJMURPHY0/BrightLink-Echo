"""Where the app starts in the sign-in queue (Settings: Start with Windows).

Two launchers fire at sign-in, both with --startup: the logon task (Task
Scheduler, seconds after sign-in, ahead of everything) and the Run entry
(Explorer, in the same burst as the person's other startup apps). The slider
decides which of them starts the app and when:

  First         the logon task starts it at once, ahead of everything.
  With others   the logon task steps aside; the Run entry starts it alongside
                the other startup apps, the moment Windows opens them.
  After others  the Run entry waits until no new app has opened for a while.
  Last          the same, waiting longer and for the processor to calm down.

A fixed timer cannot do this: on a busy laptop the other startup apps open
anywhere from 40 seconds to 3 minutes after sign-in (measured 18 Nov 2026:
OneDrive +43 s, Chrome +103 s, ChatGPT +134 s), so "20 seconds" landed well
ahead of them. The waits here watch what Windows is actually doing, with a cap
so a PC that never settles still gets the app.

It changes start-up only: once the speech model is ready the process goes back
to the above-normal class it always dictates at. A launch by hand never waits,
and nor does a relaunch long after sign-in (crash recovery, an update).

Runs ahead of every project import in app.py except brand (constants only), so
stdlib only otherwise, and it reads the one value it needs straight from
config.json rather than through Config.
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time
from typing import NamedTuple, Optional

import brand

ABOVE_NORMAL = 0x00008000
NORMAL = 0x00000020

STARTUP_ARG = "--startup"
RELAUNCH_ARG = "--relaunch"  # crash recovery: start now, whatever the stop

# Launch kinds, from the parent process.
EARLY = "early"      # the logon task: Task Scheduler's svchost / taskhostw
STARTUP_APPS = "startup_apps"  # the Run entry: explorer.exe
OTHER = "other"      # a relaunch by Echo itself, Windows restart recovery, a dev run

_TASK_PARENTS = {"svchost.exe", "taskhostw.exe", "taskeng.exe"}

# A --startup launch this long after sign-in is a relaunch, not a sign-in.
SIGN_IN_WINDOW_S = 10 * 60
# The logon task waits this long after sign-in for the Run entry to appear
# before starting the app itself (Explorer can skip or be very late).
EARLY_HANDOVER_LIMIT_S = 4 * 60
POLL_S = 2.0


class Stop(NamedTuple):
    label: str          # under the slider
    caption: str        # the one line that says what this stop does
    wait_for_others: bool  # the logon task hands over to the Run entry
    quiet_seconds: int  # no new app may open for this long before starting
    min_seconds: int    # after the Run entry fires
    max_seconds: int    # cap after the Run entry fires: a PC that never settles
    cpu_settled: bool   # also wait for the processor to calm down
    load_class: int     # process priority class while the model loads


# Index 0 is what every install did before this setting existed, and the default.
STOPS = (
    Stop("First", "Ready the moment you sign in, ahead of Teams and other apps.",
         False, 0, 0, 0, False, ABOVE_NORMAL),
    Stop("With others", "Starts together with your other startup apps.",
         True, 0, 0, 0, False, NORMAL),
    Stop("After others", "Starts once your other apps have finished opening.",
         True, 45, 30, 300, False, NORMAL),
    Stop("Last", "Starts when your PC has settled after sign-in.",
         True, 90, 60, 480, True, NORMAL),
)
DEFAULT_STOP = 0

_lowered = False
_report = ""
_wait_mutex = None  # held for the life of a waiting startup-apps launch


def clamp(value) -> int:
    """A valid stop index for anything a config file may hold."""
    if isinstance(value, bool):
        return DEFAULT_STOP
    try:
        return max(0, min(int(value), len(STOPS) - 1))
    except (TypeError, ValueError):
        return DEFAULT_STOP


def launched_at_sign_in(argv) -> bool:
    return any(str(a).lower() == STARTUP_ARG for a in argv[1:])


def _config_path() -> str:
    # The same rule as config.get_config_path(), which cannot be imported yet.
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "config.json")


def saved_stop(path: str = "") -> int:
    """The saved stop; the default when the file is missing or unreadable, so a
    damaged config can never hold the app back at sign-in."""
    try:
        with open(path or _config_path(), "r", encoding="utf-8") as f:
            return clamp(json.load(f).get("startup_priority", DEFAULT_STOP))
    except (OSError, ValueError, AttributeError):
        return DEFAULT_STOP


# ── Windows plumbing (private WinDLLs: argtypes on the shared ctypes.windll
#    leak into every other module, the popup wrong-monitor saga) ─────────────

_PROCESS_QUERY_LIMITED = 0x1000
_TH32CS_SNAPPROCESS = 0x2
_EPOCH_DIFF_100NS = 116444736000000000


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def _k32():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(wt.FILETIME)] * 4
    k32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, wt.DWORD, ctypes.c_wchar_p, ctypes.POINTER(wt.DWORD)]
    k32.ProcessIdToSessionId.argtypes = [wt.DWORD, ctypes.POINTER(wt.DWORD)]
    k32.GetSystemTimes.argtypes = [ctypes.POINTER(wt.FILETIME)] * 3
    k32.OpenMutexW.restype = ctypes.c_void_p
    k32.OpenMutexW.argtypes = [wt.DWORD, wt.BOOL, ctypes.c_wchar_p]
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, ctypes.c_wchar_p]
    return k32


def _ft(ft: "wt.FILETIME") -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def _ft_to_unix(value: int) -> float:
    return (value - _EPOCH_DIFF_100NS) / 1e7


def _set_priority_class(value: int) -> bool:
    try:
        k32 = _k32()
        return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), value))
    except Exception as e:
        print(f"[Startup] Could not set process priority: {e}", file=sys.stderr)
        return False


def _processes():
    """[(pid, parent_pid, exe_name)] from a Toolhelp snapshot."""
    k32 = _k32()
    snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return []
    out = []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


def _process_info(k32, pid: int):
    """(full image path, creation time as unix seconds), or None."""
    h = k32.OpenProcess(_PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return None
    try:
        c, e, kt, ut = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
        if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                                   ctypes.byref(kt), ctypes.byref(ut)):
            return None
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        path = buf.value if k32.QueryFullProcessImageNameW(
            h, 0, buf, ctypes.byref(size)) else ""
        return path, _ft_to_unix(_ft(c))
    finally:
        k32.CloseHandle(h)


def launch_kind() -> str:
    """Who started this process: the logon task, Explorer's startup apps, or
    something else. Unknown counts as startup apps, which waits as asked."""
    try:
        name = _launcher_name(_processes(), os.getpid(),
                              os.path.basename(sys.executable))
    except Exception:
        return STARTUP_APPS
    return classify_launcher(name)


def _launcher_name(procs, me: int, own_exe: str) -> str:
    """The first ancestor that is not this program: a one-file build runs as a
    bootloader process with the app as its child, so the app's own parent is
    another copy of itself."""
    parents = {p: pp for p, pp, _ in procs}
    names = {p: n for p, _, n in procs}
    pid = parents.get(me)
    for _ in range(4):
        if not pid:
            return ""
        name = names.get(pid, "")
        if name.lower() != own_exe.lower():
            return name
        pid = parents.get(pid)
    return ""


def classify_launcher(name: str) -> str:
    name = (name or "").lower()
    if name == "explorer.exe":
        return STARTUP_APPS
    if name in _TASK_PARENTS:
        return EARLY
    # Anything else, or a parent that has already gone (a copy of Echo that
    # relaunched itself and exited): never a sign-in launcher, which stays up.
    return OTHER


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", ctypes.c_long)]


class _LSA_UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wt.USHORT), ("MaximumLength", wt.USHORT),
                ("Buffer", ctypes.c_void_p)]


class _SECURITY_LOGON_SESSION_DATA(ctypes.Structure):
    _fields_ = [("Size", wt.ULONG), ("LogonId", _LUID),
                ("UserName", _LSA_UNICODE_STRING), ("LogonDomain", _LSA_UNICODE_STRING),
                ("AuthenticationPackage", _LSA_UNICODE_STRING),
                ("LogonType", wt.ULONG), ("Session", wt.ULONG), ("Sid", ctypes.c_void_p),
                ("LogonTime", ctypes.c_longlong)]


def signed_in_at() -> Optional[float]:
    """When this Windows logon session began (unix seconds), or None."""
    try:
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        sec = ctypes.WinDLL("secur32")
        k32 = _k32()
        adv.OpenProcessToken.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.POINTER(ctypes.c_void_p)]
        adv.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                            wt.DWORD, ctypes.POINTER(wt.DWORD)]
        sec.LsaGetLogonSessionData.argtypes = [
            ctypes.POINTER(_LUID), ctypes.POINTER(ctypes.POINTER(_SECURITY_LOGON_SESSION_DATA))]
        sec.LsaGetLogonSessionData.restype = ctypes.c_long
        sec.LsaFreeReturnBuffer.argtypes = [ctypes.c_void_p]
        token = ctypes.c_void_p()
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            return None
        try:
            stats = (ctypes.c_byte * 64)()
            got = wt.DWORD()
            # TokenStatistics (10): TokenId LUID, then AuthenticationId LUID.
            if not adv.GetTokenInformation(token, 10, stats, ctypes.sizeof(stats),
                                           ctypes.byref(got)):
                return None
            luid = _LUID.from_buffer_copy(bytes(stats)[8:16])
        finally:
            k32.CloseHandle(token)
        data = ctypes.POINTER(_SECURITY_LOGON_SESSION_DATA)()
        if sec.LsaGetLogonSessionData(ctypes.byref(luid), ctypes.byref(data)) != 0:
            return None
        try:
            t = data.contents.LogonTime
        finally:
            sec.LsaFreeReturnBuffer(data)
        return _ft_to_unix(t) if t > 0 else None
    except Exception:
        return None


def _mutex_exists(name: str) -> bool:
    try:
        k32 = _k32()
        h = k32.OpenMutexW(0x00100000, False, name)  # SYNCHRONIZE
        if h:
            k32.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


def _echo_running_or_queued() -> bool:
    return _mutex_exists(brand.MUTEX_NAME) or _mutex_exists(brand.SIGNIN_WAIT_MUTEX)


def _hold_wait_mutex() -> None:
    global _wait_mutex
    try:
        _wait_mutex = _k32().CreateMutexW(None, False, brand.SIGNIN_WAIT_MUTEX)
    except Exception:
        _wait_mutex = None


class AppWatch:
    """When the most recent app opened since sign-in. An app is a process in
    this session from outside the Windows folder, counted once per program
    name (a browser opening tabs is still one app)."""

    def __init__(self, since: float):
        self.since = since
        self._seen = {}   # pid -> program name or "" when it does not count
        self._first = {}  # program name -> earliest start
        self._win = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows")) + os.sep
        self._own = os.path.basename(sys.executable).lower()
        try:
            k32 = _k32()
            sid = wt.DWORD()
            k32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
            self._session = sid.value
        except Exception:
            self._session = None

    def latest_start(self) -> float:
        k32 = _k32()
        for pid, _, name in _processes():
            if pid in self._seen:
                continue
            self._seen[pid] = ""
            low = name.lower()
            if low == self._own or pid in (0, 4):
                continue
            if self._session is not None:
                sid = wt.DWORD()
                if not k32.ProcessIdToSessionId(pid, ctypes.byref(sid)) or sid.value != self._session:
                    continue
            info = _process_info(k32, pid)
            if not info:
                continue
            path, started = info
            if not path or os.path.normcase(path).startswith(self._win):
                continue
            if started < self.since:
                continue
            self._seen[pid] = low
            if low not in self._first or started < self._first[low]:
                self._first[low] = started
        return max(self._first.values(), default=self.since)


class CpuWatch:
    """Share of the processor busy since the last reading."""

    def __init__(self):
        self._last = self._read()

    @staticmethod
    def _read():
        try:
            idle, kern, user = wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
            if _k32().GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
                return _ft(idle), _ft(kern) + _ft(user)
        except Exception:
            pass
        return None

    def busy(self) -> float:
        now = self._read()
        last, self._last = self._last, now
        if not now or not last or now[1] <= last[1]:
            return 0.0
        return 1.0 - (now[0] - last[0]) / (now[1] - last[1])


CPU_SETTLED = 0.35


def settle(stop: Stop, sleep, clock, latest_app_start, cpu_busy) -> float:
    """Wait for a startup-apps launch at this stop. Returns seconds waited."""
    began = clock()
    if stop.quiet_seconds <= 0 and stop.min_seconds <= 0:
        return 0.0
    while True:
        now = clock()
        waited = now - began
        if waited >= stop.max_seconds:
            break
        busy = cpu_busy() if stop.cpu_settled else 0.0
        if (waited >= stop.min_seconds
                and now - latest_app_start() >= stop.quiet_seconds
                and busy < CPU_SETTLED):
            break
        sleep(POLL_S)
    return clock() - began


def wait_at_sign_in(argv, sleep=time.sleep, set_class=_set_priority_class,
                    stop=None, kind=None, clock=time.time, signed_in=None,
                    others_present=_echo_running_or_queued, exit_fn=os._exit,
                    watch=None, cpu=None) -> float:
    """Called once, at the very top of app.py. Returns the seconds waited.
    May end this process (exit_fn) when it is a launch that is not needed."""
    global _lowered, _report
    if not launched_at_sign_in(argv):
        return 0
    stop_i = saved_stop() if stop is None else clamp(stop)
    chosen = STOPS[stop_i]
    if not chosen.wait_for_others:
        _report = f"stop {chosen.label}: started at once"
        return 0
    if any(str(a).lower() == RELAUNCH_ARG for a in argv[1:]):
        _report = f"stop {chosen.label}: relaunch, no wait"
        return 0
    kind = launch_kind() if kind is None else kind
    signed = signed_in_at() if signed_in is None else signed_in
    now = clock()
    since = (now - signed) if signed else None
    if kind == OTHER or (since is not None and since > SIGN_IN_WINDOW_S):
        _report = f"stop {chosen.label}: {kind} launch {int(since or 0)} s after sign-in, no wait"
        return 0
    _lowered = True
    set_class(chosen.load_class)
    began = now
    if kind == EARLY:
        # Step aside for the Run entry, which Windows opens with the other
        # startup apps. Start anyway if it never comes.
        limit = (signed or now) + EARLY_HANDOVER_LIMIT_S
        while clock() < limit:
            if others_present():
                _report = ""
                exit_fn(0)
                return clock() - began
            sleep(POLL_S)
        # No Run entry: carry on as if this were it.
    else:
        _hold_wait_mutex()
    start_point = signed if signed else now
    watch = watch or AppWatch(start_point - 5)
    cpu = cpu or CpuWatch()
    settle(chosen, sleep, clock, watch.latest_start, cpu.busy)
    waited = clock() - began
    after = f", {int(clock() - signed)} s after sign-in" if signed else ""
    _report = (f"stop {chosen.label}: {kind} launch waited {int(waited)} s{after}")
    return waited


def restore_dictation_priority(set_class=_set_priority_class) -> None:
    """The model is ready (or failed): dictate at the usual class, and log
    how this sign-in launch was placed. No-op unless there is something to do."""
    global _lowered, _report
    if _report:
        print(f"[Startup] {_report}")
        _report = ""
    if _lowered:
        _lowered = False
        set_class(ABOVE_NORMAL)
