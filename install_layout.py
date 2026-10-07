"""
The installed layout (v1.8.0 on): what is on disk, and whether it is whole.

    %LOCALAPPDATA%\\BrightLink Echo\\  (data_paths.local_dir(); the legacy name
                                      until activate.ps1 moved the machine)
        BrightLink Echo.exe    the canonical exe: a PyInstaller ONEDIR bootloader
        app-1.8.1\\             its files (contents_directory), with manifest.json
        pending-1.8.2\\         an update laid out in full before it is switched in

Until v1.7.x the canonical exe was a ONEFILE build that unpacked 5,334 files
(291 MB) into runtime\\_MEIxxxx on every start. The contents folder is named
after the version, so an update never writes into files the running version
uses, and rolling back is swapping one exe back (its folder is still there).

An exe records its contents folder in its own archive table
("pyi-contents-directory app-1.8.0"); onefile builds record "_internal" and
never have that folder beside them. Nothing here guesses from folder names.

manifest.json lists every file of a version (path, size, SHA-256) and is
written by CI after the exe is signed. A version is only ever switched in when
its files match it: an interrupted install, a full disk or an antivirus
quarantining one DLL all leave a folder that looks complete and is not.

Standard library only: app.py's startup, the uninstaller and the build tools
all read this module.
"""

import hashlib
import json
import os
import sys
import time

import brand
import data_paths

MANIFEST_NAME = "manifest.json"
HEALTH_FILE = "health.json"
BAD_VERSION_FILE = "bad-version.txt"
MIGRATION_FILE = "migration-state.json"
UPDATE_LOG = "update.log"
PREVIOUS_SUFFIX = ".previous"

_CONTENTS_OPTION = b"pyi-contents-directory "
_TAIL_SEARCH = 1024 * 1024


# ── Paths ────────────────────────────────────────────────────────────────────


def install_dir() -> str:
    """The local data folder: data_paths.local_dir(), which stays the legacy
    one until installer/activate.ps1 has moved this machine."""
    return data_paths.local_dir()


def canonical_exe(root: str = "") -> str:
    """The exe that runs *root*'s layout: the legacy folder keeps its legacy
    exe name; every other folder (the new one, a dist build) the current one."""
    return data_paths.canonical_exe(root or install_dir())


def contents_dir_name(version: str) -> str:
    return brand.CONTENTS_DIR_PREFIX + version.lstrip("vV")


def pending_dir_name(version: str) -> str:
    return brand.PENDING_DIR_PREFIX + version.lstrip("vV")


# ── What kind of build is running ────────────────────────────────────────────


def running_layout(frozen=None, meipass=None, executable=None) -> str:
    """"onedir" (the installed layout), "onefile" or "source".

    Onedir: the bootloader loads its files from a folder beside the exe, so
    sys._MEIPASS sits directly in the exe's folder. Onefile: _MEIPASS is an
    unpack folder under runtime\\ (or %TEMP%)."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not frozen:
        return "source"
    meipass = getattr(sys, "_MEIPASS", "") if meipass is None else meipass
    executable = sys.executable if executable is None else executable
    if not meipass:
        return "onefile"
    here = os.path.normcase(os.path.abspath(os.path.dirname(executable)))
    parent = os.path.normcase(os.path.abspath(os.path.dirname(meipass)))
    return "onedir" if here == parent else "onefile"


def exe_contents_dir(exe: str) -> str:
    """The contents folder name recorded in *exe*'s archive, or "" when the
    file is unreadable or not a PyInstaller exe."""
    try:
        size = os.path.getsize(exe)
        with open(exe, "rb") as f:
            f.seek(max(0, size - _TAIL_SEARCH))
            tail = f.read()
    except OSError:
        return ""
    i = tail.rfind(_CONTENTS_OPTION)
    if i < 0:
        return ""
    end = tail.find(b"\0", i)
    raw = tail[i + len(_CONTENTS_OPTION):end if end > 0 else None]
    try:
        return raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return ""


def is_installed_layout_exe(exe: str) -> bool:
    """True for a onedir exe of ours: its contents folder is versioned."""
    return exe_contents_dir(exe).startswith(brand.CONTENTS_DIR_PREFIX)


def layout_ok(exe: str) -> bool:
    """Can *exe* start, as far as its files are concerned?

    A onedir exe needs its contents folder, with a manifest, holding every file
    it lists at the listed size (sizes, not hashes: this runs before the mutex
    at every launch). A onefile exe carries everything itself, so it is judged
    by updater.pyi_archive_intact alone and this returns True."""
    name = exe_contents_dir(exe)
    if not name.startswith(brand.CONTENTS_DIR_PREFIX):
        return True
    root = os.path.dirname(exe)
    manifest = load_manifest(os.path.join(root, name, MANIFEST_NAME))
    if not manifest:
        return False
    return not verify_tree(root, manifest, full_hash=False, include_exe=False)


# ── Manifest ─────────────────────────────────────────────────────────────────


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def make_manifest(root: str, version: str) -> dict:
    """Describe the layout under *root* (the folder holding the exe and its
    app-<version> folder). The manifest never lists itself."""
    exe = canonical_exe(root)
    contents = contents_dir_name(version)
    files = []
    base = os.path.join(root, contents)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if rel == f"{contents}/{MANIFEST_NAME}":
                continue
            files.append({"path": rel, "size": os.path.getsize(full),
                          "sha256": file_sha256(full)})
    return {
        "version": version.lstrip("vV"),
        "contents": contents,
        "exe": {"path": brand.CANONICAL_EXE_NAME, "size": os.path.getsize(exe),
                "sha256": file_sha256(exe)},
        "files": files,
    }


def write_manifest(root: str, version: str) -> str:
    manifest = make_manifest(root, version)
    path = os.path.join(root, manifest["contents"], MANIFEST_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    return path


def load_manifest(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("files"), list) \
                and isinstance(data.get("exe"), dict):
            return data
    except Exception:
        pass
    return {}


def verify_tree(root: str, manifest: dict, full_hash: bool = True,
                include_exe: bool = True, limit: int = 20) -> list:
    """Every way the layout under *root* differs from *manifest*, as short
    strings (empty list = whole). Stops after *limit* problems."""
    problems = []
    entries = list(manifest.get("files") or [])
    if include_exe:
        entries.insert(0, manifest.get("exe") or {})
    for entry in entries:
        rel = str(entry.get("path") or "")
        if not rel or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
            problems.append(f"bad manifest path {rel!r}")
            break
        full = os.path.join(root, *rel.split("/"))
        try:
            size = os.path.getsize(full)
        except OSError:
            problems.append(f"missing {rel}")
        else:
            if size != entry.get("size"):
                problems.append(f"size {rel}: {size} != {entry.get('size')}")
            elif full_hash and file_sha256(full) != str(entry.get("sha256", "")).lower():
                problems.append(f"sha256 {rel}")
        if len(problems) >= limit:
            break
    return problems


# ── Markers shared with activate.ps1 ─────────────────────────────────────────


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: str, data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        pass


def write_health(version: str, root: str = "") -> None:
    """The app is up. activate.ps1 waits for this after switching versions and
    rolls back only when the new version EXITS without ever writing it."""
    _write_json(os.path.join(root or install_dir(), HEALTH_FILE),
                {"version": version.lstrip("vV"), "pid": os.getpid(),
                 "time": time.time()})


def read_bad_version(root: str = "") -> str:
    try:
        # utf-8-sig: Windows PowerShell's own writers put a BOM first.
        with open(os.path.join(root or install_dir(), BAD_VERSION_FILE),
                  "r", encoding="utf-8-sig") as f:
            return f.read().strip().lstrip("vV")
    except Exception:
        return ""


def migration_failures(version: str, root: str = "") -> int:
    """Failed installer attempts for *version* (the bridge falls back to the
    onefile swap after a few, so a machine that blocks installers still
    updates)."""
    state = _read_json(os.path.join(root or install_dir(), MIGRATION_FILE))
    if state.get("version") != version.lstrip("vV"):
        return 0
    try:
        return int(state.get("failures") or 0)
    except (TypeError, ValueError):
        return 0


def record_migration_failure(version: str, detail: str = "", root: str = "") -> int:
    count = migration_failures(version, root) + 1
    _write_json(os.path.join(root or install_dir(), MIGRATION_FILE),
                {"version": version.lstrip("vV"), "failures": count,
                 "last": str(detail)[:300], "time": time.time()})
    return count


def log(message: str, root: str = "") -> None:
    try:
        with open(os.path.join(root or install_dir(), UPDATE_LOG), "a",
                  encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [app] {message}\n")
    except Exception:
        pass


# ── Rollout ──────────────────────────────────────────────────────────────────


def machine_id() -> str:
    """A stable, anonymous id for this machine: the first 12 hex digits of the
    SHA-256 of Windows' MachineGuid. Nothing identifying leaves the machine;
    Ryan can allow-list a PC by this value in the rollout file."""
    guid = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
            guid, _ = winreg.QueryValueEx(k, "MachineGuid")
    except Exception:
        guid = (os.environ.get("COMPUTERNAME", "") + "|"
                + os.environ.get("USERNAME", ""))
    return hashlib.sha256(str(guid).lower().encode("utf-8")).hexdigest()[:12]


def rollout_allows(rollout, mid: str = "") -> bool:
    """May this machine migrate to the installed layout now?

    *rollout* is the release's rollout file, parsed: {"migrate_percent": 0-100,
    "machines": ["<machine_id>", ...]}. Missing or unreadable means NO: the
    migration only ever starts because a release said so, and setting the
    percentage back to 0 pauses it fleet-wide without a new build."""
    if not isinstance(rollout, dict):
        return False
    mid = mid or machine_id()
    machines = rollout.get("machines") or []
    if isinstance(machines, list) and mid in [str(m).lower() for m in machines]:
        return True
    try:
        percent = int(rollout.get("migrate_percent") or 0)
    except (TypeError, ValueError):
        return False
    return int(mid[:8], 16) % 100 < max(0, min(100, percent))


# ── Clean-up after a version is running ──────────────────────────────────────


def stale_paths(root: str, own_contents: str) -> list:
    """What a healthy onedir version may delete: other versions' folders
    (except the one a pending rollback would need), leftover pending folders
    and onefile unpack folders. Returned, not deleted, so it is testable."""
    keep = {own_contents.lower()}
    prev = canonical_exe(root) + PREVIOUS_SUFFIX
    if os.path.exists(prev):
        try:
            if time.time() - os.path.getmtime(prev) < 86400:
                name = exe_contents_dir(prev)
                if name:
                    keep.add(name.lower())
        except OSError:
            pass
    out = []
    try:
        entries = os.listdir(root)
    except OSError:
        return out
    for name in entries:
        full = os.path.join(root, name)
        if not os.path.isdir(full):
            continue
        low = name.lower()
        if low.startswith(brand.CONTENTS_DIR_PREFIX) and low not in keep:
            out.append(full)
        elif low.startswith(brand.PENDING_DIR_PREFIX):
            out.append(full)
    runtime = os.path.join(root, "runtime")
    try:
        for name in os.listdir(runtime):
            if name.startswith("_MEI"):
                out.append(os.path.join(runtime, name))
    except OSError:
        pass
    # What activate.ps1 could not delete after moving the legacy folder here
    # (a file that was in use). The marker says this folder replaced it, so
    # nothing in it is needed any more. The roaming folder is never touched.
    if (os.path.basename(root).lower() == brand.DATA_DIR_NAME.lower()
            and os.path.isfile(os.path.join(root, brand.MIGRATED_MARKER))):
        legacy = os.path.join(os.path.dirname(root), brand.LEGACY_DATA_DIR_NAME)
        if os.path.isdir(legacy):
            out.append(legacy)
    return out
