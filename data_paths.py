"""
The folders this machine's copy of the app keeps its files in.

v1.8.5 moved them from %LOCALAPPDATA%\\<legacy name> and %APPDATA%\\<legacy name>
to the current names in brand.py. installer/activate.ps1 does the move while
the app is stopped, and writes brand.MIGRATED_MARKER into the new local folder
when it is done. Until a machine has been moved (a pre-1.8 copy running the
onefile bridge, or an update that has not run yet), the app keeps using the
legacy folders, so nobody loses the 660 MB model, their sign-in or history.

Every module asks here instead of joining a folder name itself. Standard
library and brand only: app.py's pre-import startup guard and the uninstaller
read this module.
"""

import os

import brand


def local_base() -> str:
    return os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local")


def roaming_base() -> str:
    return os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming")


def new_local_dir() -> str:
    return os.path.join(local_base(), brand.DATA_DIR_NAME)


def legacy_local_dir() -> str:
    return os.path.join(local_base(), brand.LEGACY_DATA_DIR_NAME)


def new_roaming_dir() -> str:
    return os.path.join(roaming_base(), brand.DATA_DIR_NAME)


def legacy_roaming_dir() -> str:
    return os.path.join(roaming_base(), brand.LEGACY_DATA_DIR_NAME)


def uses_legacy() -> bool:
    """True while this machine still runs from the legacy local folder: it
    exists, and the new one is neither marked as home nor holding the current
    exe. Either sign keeps a machine on the new folder even when an old exe
    run later recreates the legacy one (every onefile build unpacks there)."""
    if not os.path.isdir(legacy_local_dir()):
        return False
    new = new_local_dir()
    return not (os.path.isfile(os.path.join(new, brand.MIGRATED_MARKER))
                or os.path.isfile(os.path.join(new, brand.CANONICAL_EXE_NAME)))


def local_dir() -> str:
    """%LOCALAPPDATA%\\<data folder>: the exe, its app-<version> folder, the
    model, markers and logs."""
    return legacy_local_dir() if uses_legacy() else new_local_dir()


def roaming_dir() -> str:
    """%APPDATA%\\<data folder>: config, encrypted session, history, audio.

    Follows the local choice. A legacy roaming folder with no new one beside it
    is still used (a roaming profile arriving on a new PC before the update has
    adopted it), so history never disappears in between."""
    new, legacy = new_roaming_dir(), legacy_roaming_dir()
    if not uses_legacy() and os.path.isdir(new):
        return new
    if os.path.isdir(legacy):
        return legacy
    return new


def is_legacy_dir(path: str) -> bool:
    return _same(path, legacy_local_dir()) or _same(path, legacy_roaming_dir())


def exe_name_for(folder: str) -> str:
    """The canonical exe's file name inside *folder*."""
    if _same(folder, legacy_local_dir()):
        return brand.LEGACY_CANONICAL_EXE_NAME
    return brand.CANONICAL_EXE_NAME


def canonical_exe(folder: str = "") -> str:
    folder = folder or local_dir()
    return os.path.join(folder, exe_name_for(folder))


def all_local_dirs() -> tuple:
    return (new_local_dir(), legacy_local_dir())


def all_roaming_dirs() -> tuple:
    return (new_roaming_dir(), legacy_roaming_dir())


def is_our_folder(path: str) -> bool:
    """*path* is one of our data folders, current or legacy, directly under
    %LOCALAPPDATA% or %APPDATA%. The uninstaller deletes nothing else."""
    return any(_same(path, p) for p in all_local_dirs() + all_roaming_dirs())


def _same(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:
        return False
