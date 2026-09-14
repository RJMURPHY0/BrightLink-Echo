"""
The frozen app must always run on the files ITS OWN bootloader unpacked.

A PyInstaller onefile exe starts twice: a bootloader unpacks the bundle into a
fresh `_MEIxxxx` folder, then launches the same exe again as the Python process,
telling it where that folder is through `_PYI_APPLICATION_HOME_DIR`,
`_PYI_ARCHIVE_FILE` and `_PYI_PARENT_PROCESS_LEVEL`. Those variables stay in the
Python process's environment, so ANYTHING it launches inherits them. When that
something is the same exe (the updater's swap script relaunching it in place,
the stale-copy handoff), the new exe reads the variables, believes it is the
child of the old bootloader, skips unpacking, and runs its new code on the OLD
process's native libraries.

That is what broke every dictation in v1.6.79 (2026-09-14). The update relaunch
ran v1.6.79's code (onnxruntime 1.30 Python layer) on v1.6.78's unpacked
onnxruntime 1.29 binary; every inference raised `no attribute
'is_webgpu_graph_capture_enabled'`, the engine swallowed it, and each dictation
came back "No speech detected". Earlier updates survived only because two
consecutive builds had happened to bundle identical libraries.

Two defences, both needed:
  * clean_launch_env(): every launch of our own exe resets the bootloader
    environment (PYINSTALLER_RESET_ENVIRONMENT=1, `_PYI_*` removed).
  * relaunch_if_foreign_runtime(): at startup, a process whose parent is not its
    own bootloader is on someone else's files; it relaunches itself once, clean.
    This is what rescues an install being updated BY an old build whose updater
    still leaks the environment.

Standard library only: this runs before any other project import.
"""

import os
import sys

# Set on the one relaunch we perform, so a relaunch can never loop.
GUARD_VAR = "FTC_WHISPER_RUNTIME_RESET"
_RESET_VAR = "PYINSTALLER_RESET_ENVIRONMENT"


def clean_launch_env(base=None) -> dict:
    """A copy of *base* (default os.environ) that makes a launched copy of this
    exe unpack its OWN runtime: bootloader variables removed, reset requested,
    and our relaunch guard dropped so the child can still heal itself."""
    env = dict(os.environ if base is None else base)
    for key in list(env):
        if key.upper().startswith("_PYI_") or key.upper() == GUARD_VAR:
            del env[key]
    env[_RESET_VAR] = "1"
    return env


def _norm(path: str) -> str:
    try:
        return os.path.normcase(os.path.realpath(path))
    except Exception:
        return os.path.normcase(os.path.abspath(path))


def _process_image(pid: int) -> str:
    """Full image path of *pid*, or "" when the process is gone or unreadable."""
    import ctypes
    import ctypes.wintypes as wt
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.QueryFullProcessImageNameW.restype = wt.BOOL
    k32.QueryFullProcessImageNameW.argtypes = [
        wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wt.DWORD(len(buf))
        if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value
    finally:
        k32.CloseHandle(h)


def running_on_foreign_runtime(frozen=None, environ=None, executable=None,
                               parent_image=None) -> bool:
    """True when this frozen onefile process is running on files a DIFFERENT
    bootloader unpacked.

    A normal launch always has its own bootloader (the same exe) as its live
    parent at startup. Anything else means the `_PYI_*` variables were
    inherited from another process. Parameters exist for tests; the defaults
    read the live process."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    environ = os.environ if environ is None else environ
    if not frozen:
        return False
    if parent_image is None and sys.platform != "win32":
        return False
    if environ.get(GUARD_VAR):
        return False                    # already relaunched once: never loop
    if not environ.get("_PYI_APPLICATION_HOME_DIR"):
        return False                    # not a onefile child at all
    executable = sys.executable if executable is None else executable
    if parent_image is None:
        try:
            parent_image = _process_image(os.getppid())
        except Exception:
            return False                # cannot inspect: run as we are
    if not parent_image:
        return True                     # parent gone: no bootloader of ours
    mine = {_norm(executable)}
    archive = environ.get("_PYI_ARCHIVE_FILE")
    if archive:
        mine.add(_norm(archive))
    return _norm(parent_image) not in mine


def relaunch_if_foreign_runtime(log_path=None) -> None:
    """Relaunch this exe on its own runtime and exit, if it is not already on
    one. Never raises: if the relaunch cannot be started, carry on as-is."""
    try:
        if not running_on_foreign_runtime():
            os.environ.pop(GUARD_VAR, None)
            return
        import subprocess
        env = clean_launch_env()
        env[GUARD_VAR] = "1"
        subprocess.Popen([sys.executable] + sys.argv[1:], env=env,
                         cwd=os.path.dirname(sys.executable), close_fds=True)
        if log_path:
            try:
                import time
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Relaunched "
                            f"on own runtime (was on "
                            f"{getattr(sys, '_MEIPASS', '?')})\n")
            except Exception:
                pass
        os._exit(0)
    except Exception:
        return
