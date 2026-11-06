"""Full paths of the Windows tools Echo starts.

A bare name such as "powershell" or "schtasks" is searched for in the current
folder and along PATH first, so a look-alike placed there would run instead of
the Windows tool. Windows is asked where its own System32 folder is, and the
tool is started from there. The environment is never read for this.
"""
import ctypes
import os

_FALLBACK = r"C:\Windows\System32"


def system32_dir() -> str:
    """The Windows System32 folder, from GetSystemDirectoryW."""
    try:
        buf = ctypes.create_unicode_buffer(520)
        n = ctypes.windll.kernel32.GetSystemDirectoryW(buf, len(buf))
        if 0 < n < len(buf):
            return buf.value
    except Exception as e:
        print(f"[SystemTools] GetSystemDirectoryW failed, using {_FALLBACK}: {e}")
    return _FALLBACK


def system_tool(name: str) -> str:
    """Full path of a tool that lives directly in System32 (schtasks.exe...)."""
    return os.path.join(system32_dir(), name)


def powershell_exe() -> str:
    """Full path of Windows PowerShell 5.1."""
    return os.path.join(system32_dir(), "WindowsPowerShell", "v1.0", "powershell.exe")
