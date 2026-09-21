"""
FTC Whisper — auto-update helpers.

All network errors are swallowed silently; updating is best-effort and
should never crash or block the main application.
"""

import json
import brand
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from typing import Callable, Optional

_GITHUB_API = f"https://api.github.com/repos/{brand.GITHUB_REPO}/releases/latest"
# The update channel. Deliberately NOT the download people see: every
# installed copy, and the CRM's download button, look for this exact name.
_DOWNLOAD_FILENAME = brand.UPDATE_ASSET

_cached_release: Optional[dict] = None

# A release exe bundles Python + models glue; anything smaller than this is a
# GitHub error page or a truncated download, never a real build.
_MIN_EXE_BYTES = 5 * 1024 * 1024

_APPLY_LOCK = threading.Lock()
_apply_started = False

# One update run per process. The automatic updater, the Update Now button and
# the CRM's /update call each used to start their own run, and two runs shared
# one download file: the second deleted the first's VERIFIED download and began
# rewriting it, the first then installed (exiting the process mid-download),
# and the swap script copied a 21 MB prefix of a 130 MB exe over the install
# (v1.6.81 on Ryan's machine, 2026-09-21). A second caller now joins the run in
# flight; asking to install now only shortens that run's idle wait.
_RUN_LOCK = threading.Lock()
_run_active = False
_apply_now = threading.Event()

_DOWNLOAD_PREFIX = "FTC-Whisper-new"
_STALE_DOWNLOAD_SECS = 3600


def _app_data_dir() -> str:
    """Per-user data dir shared with app.py (%LOCALAPPDATA%\\FTC Whisper)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local"
    )
    d = os.path.join(base, brand.DATA_DIR_NAME)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _last_version_path() -> str:
    return os.path.join(_app_data_dir(), "last-version.txt")


def read_last_run_version() -> str:
    """Version the app last ran as, or "" (fresh install / file missing)."""
    try:
        with open(_last_version_path(), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def write_last_run_version(version: str) -> None:
    try:
        with open(_last_version_path(), "w", encoding="utf-8") as f:
            f.write(version)
    except Exception:
        pass


def _last_name_path() -> str:
    return os.path.join(_app_data_dir(), "last-product-name.txt")


def read_last_run_name() -> str:
    """Product name the app last ran under, or "" when nothing recorded it:
    a fresh install, or any version from before names were recorded."""
    try:
        with open(_last_name_path(), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def write_last_run_name(name: str) -> None:
    try:
        with open(_last_name_path(), "w", encoding="utf-8") as f:
            f.write(name)
    except Exception:
        pass


def update_announcement(prev_version: str, prev_name: str,
                        version: str, name: str) -> Optional[dict]:
    """What to tell the user on the first launch after an update, or None.

    Returns {"title", "message", "toast", "toast_ms"}. A rename gets its own
    wording: an unfamiliar name appearing in the tray after a silent
    auto-update reads like something else got installed. It is ONE notice, not
    an update notice plus a rename notice racing for the same tray balloon.

    prev_name is "" for every version from before names were recorded, and
    all of those shipped as brand.UNRECORDED_PRODUCT_NAME.
    """
    if not prev_version or not is_newer(version, prev_version):
        return None
    before = prev_name or brand.UNRECORDED_PRODUCT_NAME
    # Case alone ("Brightlink" to "BrightLink") is a spelling fix, not news.
    if before.casefold() != name.casefold():
        return {
            "title": f"{before} is now {name}",
            "message": f"Updated to v{version}. Same app and settings, new name.",
            "toast": f"{before} is now {name} (v{version})",
            "toast_ms": 9000,
        }
    return {
        "title": name,
        "message": f"Updated to v{version} ✓",
        "toast": f"{name} updated to v{version} ✓",
        "toast_ms": 6000,
    }


def cached_release() -> Optional[dict]:
    """Return the last successful result from get_latest_release(), or None."""
    return _cached_release


def _version_tuple(v: str):
    """Tolerant parse: 'v1.6.0-beta' / '1.6.0rc1' -> (1, 6, 0). A non-numeric
    tag must not make is_newer fail closed and hide real updates."""
    parts = []
    for seg in v.lstrip("vV").split("."):
        digits = ""
        for ch in seg:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    """Return True if *latest* is strictly newer than *current*."""
    try:
        return _version_tuple(latest) > _version_tuple(current)
    except Exception:
        return False


def get_latest_release() -> Optional[dict]:
    """
    Query GitHub Releases API and return {"version": str, "download_url": str},
    or None on any error. Result is cached in _cached_release.
    """
    global _cached_release
    try:
        req = urllib.request.Request(
            _GITHUB_API,
            headers={"User-Agent": brand.UPDATER_USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())

        tag = data.get("tag_name", "")
        assets = data.get("assets", [])
        asset = next(
            (a for a in assets if a.get("name") == _DOWNLOAD_FILENAME),
            None,
        )
        if tag and asset:
            digest = str(asset.get("digest") or "")
            _cached_release = {
                "version": tag,
                "download_url": asset["browser_download_url"],
                # Exact asset size lets the download/verify path detect
                # truncation even when a proxy strips Content-Length.
                "size": int(asset.get("size") or 0),
                # GitHub's own SHA-256 of the asset, when the API gives one:
                # proves the download is the file CI published, byte for byte.
                "sha256": digest[7:].lower() if digest.startswith("sha256:") else "",
            }
            return _cached_release
    except Exception:
        pass
    return None


def check_for_update(current_version: str, callback: Callable[[str, str], None]) -> None:
    """
    Check for a newer release in a background thread.
    Calls callback(version, download_url) on the calling thread if an update
    is found — the caller is responsible for routing this onto the UI thread.
    """
    import threading

    def _worker():
        info = get_latest_release()
        if info and is_newer(info["version"], current_version):
            callback(info["version"], info["download_url"])

    threading.Thread(target=_worker, daemon=True, name="update-check").start()


def download_update(
    url: str,
    dest_path: str,
    progress_cb: Callable[[int, int], None],
    expected_bytes: int = 0,
) -> None:
    """
    Download *url* to *dest_path*, calling progress_cb(bytes_done, total_bytes)
    after each chunk. Raises on network/IO errors.

    expected_bytes (the GitHub asset size) guards against truncation even when
    a proxy re-chunks the response and strips Content-Length — without it a
    mid-stream cut produces a partial file that still starts with 'MZ' and
    passes the size floor, and installing it bricks the app.
    """
    req = urllib.request.Request(url, headers={"User-Agent": brand.UPDATER_USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                progress_cb(done, total)
    if total and done != total:
        raise IOError(f"Truncated download: got {done} of {total} bytes")
    if expected_bytes and done != expected_bytes:
        raise IOError(
            f"Truncated download: got {done}, release asset is {expected_bytes} bytes"
        )


# PyInstaller's onefile exe ends with its app archive, closed by this marker
# and the archive length. A file cut short anywhere after the PE header (which
# is all the version resource needs) has no marker, and its bootloader dies
# with "Could not load PyInstaller's embedded PKG archive". The marker sits
# 88 bytes from the end; a code signature appended later moves it back a few
# KB, so the tail is searched rather than read at a fixed offset.
_PYI_COOKIE = b"MEI\x0c\x0b\x0a\x0b\x0e"
_PYI_TAIL_SEARCH = 256 * 1024


def pyi_archive_intact(path: str) -> bool:
    """True when *path* is a whole PyInstaller onefile exe: its archive marker
    is present and the archive it describes fits inside the file."""
    import struct
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            start = max(0, size - _PYI_TAIL_SEARCH)
            f.seek(start)
            tail = f.read()
    except OSError:
        return False
    i = tail.rfind(_PYI_COOKIE)
    if i < 0 or len(tail) - i < 24:
        return False
    (pkg_len,) = struct.unpack("!I", tail[i + 8:i + 12])
    end_of_cookie = start + i + 88
    return 0 < pkg_len <= min(size, end_of_cookie)


def verify_exe(path: str, min_bytes: int = _MIN_EXE_BYTES,
               expected_bytes: int = 0) -> None:
    """Sanity-check a downloaded update before it is allowed to replace the
    installed exe. Raises IOError on anything suspicious — installing a
    corrupt/HTML-error-page 'exe' bricks the install until manual reinstall."""
    size = os.path.getsize(path)
    if size < min_bytes:
        raise IOError(f"Downloaded file too small ({size} bytes) — not a release exe")
    if expected_bytes and size != expected_bytes:
        raise IOError(
            f"Downloaded file is {size} bytes but the release asset is "
            f"{expected_bytes} — truncated or tampered download"
        )
    with open(path, "rb") as f:
        if f.read(2) != b"MZ":
            raise IOError("Downloaded file is not a Windows executable (no MZ header)")
    if not pyi_archive_intact(path):
        raise IOError("Downloaded file is incomplete (no PyInstaller archive at the end)")


def file_sha256(path: str) -> str:
    """Lower-case hex SHA-256 of a file."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def apply_update(new_exe: str, current_exe: str,
                 sha256: Optional[str] = None) -> None:
    """
    Launch a detached PowerShell script that waits for this process to exit,
    installs the new exe over the current one (with retries for AV file locks),
    relaunches, then self-deletes. Exits the current process immediately via
    os._exit.

    *sha256* is the hash of the file as VERIFIED. The script installs only a
    file that still has it, and only through a staged copy that has it too, so
    a download changed or cut short after verification can never replace the
    install. Hashed here when the caller has none.

    Idempotent per process: the manual "Update Now" button and the automatic
    updater can both reach this — only the first caller wins, the rest no-op
    (two swap scripts racing over the same exe corrupts the install).
    """
    global _apply_started
    with _APPLY_LOCK:
        if _apply_started:
            return
        _apply_started = True
    if not sha256:
        sha256 = file_sha256(new_exe)
    spawn_swap_script(new_exe, current_exe, os.getpid(), sha256=sha256)
    # os._exit guarantees the process dies immediately so the PS script unblocks
    os._exit(0)


def spawn_swap_script(new_exe: str, current_exe: str, pid: int,
                      sha256: str = "", ps_file: Optional[str] = None,
                      log_file: Optional[str] = None,
                      launch: bool = True) -> str:
    """Write + launch the detached PowerShell swap script. Waits for *pid* to
    exit, then installs new_exe over current_exe and relaunches. Returns the log
    file path. Split from apply_update so it can be exercised against a dummy
    process in tests without killing the caller.

    The install is: check new_exe still hashes to *sha256* → copy it to a
    staging file beside current_exe → check the staged copy's hash → swap it in
    with File.Replace (one rename, the old exe kept as a backup) → check the
    installed hash, restoring the backup if it is wrong. A plain Copy-Item over
    the exe reported success for a truncated file; nothing here can."""
    # Escape single quotes in paths for PowerShell single-quoted strings
    new_ps  = new_exe.replace("'", "''")
    cur_ps  = current_exe.replace("'", "''")
    want = (sha256 or "").lower().replace("'", "")
    launch_flag = "$true" if launch else "$false"
    ps_file = ps_file or os.path.join(tempfile.gettempdir(), "ftc_whisper_update.ps1")
    log_file = (log_file or os.path.join(tempfile.gettempdir(),
                                         "ftc_whisper_update.log")).replace("'", "''")
    script = f"""
$NewExe = '{new_ps}'
$CurExe = '{cur_ps}'
$Want   = '{want}'
$Log    = '{log_file}'
$Stage  = "$CurExe.staging"
$Backup = "$CurExe.previous"
function Log($msg) {{ "[$(Get-Date -Format 'HH:mm:ss')] $msg" | Add-Content -Path $Log -Encoding UTF8 }}
function HashOf($p) {{
    try {{ (Get-FileHash -Path $p -Algorithm SHA256 -ErrorAction Stop).Hash.ToLower() }} catch {{ '' }}
}}
Log "Update started. PID={pid}"
Log "New: $NewExe"
Log "Cur: $CurExe"
Log "Want sha256: $Want"
# Wait for the old process to fully exit
while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{
    Start-Sleep -Milliseconds 500
}}
Log "Old process exited."
# Kill any OTHER instances still holding the installed exe open. A double-launch
# leaves a second process whose loaded image locks $CurExe, so Copy-Item fails
# every retry and the update silently never replaces the exe. Match by full path
# first (precise), then by leaf name as a backstop.
try {{
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object {{ $_.Path -eq $CurExe }} |
        Stop-Process -Force -ErrorAction SilentlyContinue
}} catch {{}}
try {{
    $leaf = [System.IO.Path]::GetFileNameWithoutExtension($CurExe)
    Get-Process -Name $leaf -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
}} catch {{}}
Start-Sleep -Milliseconds 800
Log "Cleared any sibling instances holding the exe."
# Remove Mark-of-the-Web so Defender releases its scan lock on the download
Unblock-File -Path $NewExe -ErrorAction SilentlyContinue
Log "Unblocked download. Brief settle before copy (retry loop handles any remaining scan lock)..."
Start-Sleep -Seconds 3
$ok = $false
# The download must still be the file that was verified. If anything changed
# it since (a second download reusing the path, AV remediation, a cut-off
# write), install nothing and relaunch the version already installed.
$newGood = ($Want -ne '') -and ((HashOf $NewExe) -eq $Want)
if (-not $newGood) {{
    Log "NOT installing: $NewExe no longer matches the verified download (sha256 $(HashOf $NewExe))."
}} else {{
    # Up to 30 attempts, 2 s apart (60 s) for AV / lingering file locks.
    for ($i = 0; $i -lt 30; $i++) {{
        try {{
            Copy-Item -Path $NewExe -Destination $Stage -Force -ErrorAction Stop
            if ((HashOf $Stage) -ne $Want) {{ throw "staged copy does not match the verified download" }}
            if (Test-Path -LiteralPath $CurExe) {{
                Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue
                [System.IO.File]::Replace($Stage, $CurExe, $Backup)
            }} else {{
                [System.IO.File]::Move($Stage, $CurExe)
            }}
            if ((HashOf $CurExe) -ne $Want) {{
                Log "Installed file does not match after the swap: restoring the previous exe."
                if (Test-Path -LiteralPath $Backup) {{ Copy-Item -Path $Backup -Destination $CurExe -Force -ErrorAction SilentlyContinue }}
                throw "installed hash mismatch"
            }}
            $ok = $true
            Log "Installed and verified on attempt $($i + 1)."
            break
        }} catch {{
            Log "Install attempt $($i + 1) failed: $_"
            Remove-Item -LiteralPath $Stage -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }}
    }}
}}
# Launch the installed exe when it was replaced; otherwise the verified download
# if it is intact (the install was merely locked); otherwise the old exe as-is.
$launch = if ($ok -or -not $newGood) {{ $CurExe }} else {{ $NewExe }}
Unblock-File -Path $launch -ErrorAction SilentlyContinue
Log "Launching: $launch (installed=$ok)"
if ({launch_flag}) {{ Start-Process -FilePath $launch }}
Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
if ($ok) {{
    Remove-Item -LiteralPath $NewExe -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue
}}
Log "Done."
"""
    with open(ps_file, "w", encoding="utf-8") as f:
        f.write(script)

    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden",
        "-File", ps_file,
    ]
    # NEVER combine DETACHED_PROCESS with CREATE_NO_WINDOW: they are conflicting
    # console modes and powershell.exe exits 0 without ever running -File. That
    # exact combination shipped in every build ≤1.6.3 — the app killed itself
    # via os._exit and the swap script silently never started, which is why
    # updates never applied. CREATE_NO_WINDOW alone gives the child its own
    # hidden console, and children outlive their parent by default on Windows.
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    # env: the script's Start-Process hands ITS environment to the new exe. Ours
    # carries this process's PyInstaller bootloader variables, and a new exe
    # that inherits them skips unpacking and runs on OUR old native libraries —
    # which is how v1.6.79 lost every dictation (see pyi_runtime). NEVER drop it.
    import pyi_runtime
    std = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, env=pyi_runtime.clean_launch_env())
    try:
        # Break out of any job object (Task Scheduler wraps the logon-task app
        # in one) so the swap script can't be reaped when the task's process
        # tree is torn down at os._exit.
        subprocess.Popen(
            cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **std
        )
    except OSError:
        subprocess.Popen(cmd, creationflags=flags, **std)
    return log_file


def current_exe_path() -> Optional[str]:
    """Return the path to the running EXE, or None when running from source."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return None


def _fresh_download_path(preferred: str) -> str:
    """Return a writable path for the update download.

    A stale or LOCKED leftover at the fixed path is the single most common way
    an install gets stranded on an old build: every download fails to (over)write
    it, so run_auto_update gives up and the manual button falls back to the
    browser — every time. Clear the leftover; if it can't be removed (AV hold or
    a zombie process keeping the handle), download to a fresh sibling name so the
    update still proceeds instead of failing forever.
    """
    try:
        if os.path.exists(preferred):
            os.remove(preferred)
        return preferred
    except OSError:
        pass
    base, ext = os.path.splitext(preferred)
    for i in range(1, 20):
        alt = f"{base}-{i}{ext}"
        try:
            if os.path.exists(alt):
                os.remove(alt)
            return alt
        except OSError:
            continue
    return preferred  # give up — download_update will surface the real error


def _emit(on_event, stage: str, ok, detail: str = "") -> None:
    """Best-effort telemetry hook — never let a logging failure affect updates."""
    if on_event is None:
        return
    try:
        on_event(stage, ok, detail)
    except Exception:
        pass


def _sweep_stale_downloads(keep: str = "") -> None:
    """Remove update downloads left by a run that never finished (a crash, a
    power cut). Only files over an hour old: a younger one may be another
    run's download, verified and waiting for the app to go idle."""
    d = _app_data_dir()
    try:
        names = os.listdir(d)
    except OSError:
        return
    now = time.time()
    for name in names:
        if not (name.startswith(_DOWNLOAD_PREFIX) and name.lower().endswith(".exe")):
            continue
        path = os.path.join(d, name)
        if keep and os.path.normcase(path) == os.path.normcase(keep):
            continue
        try:
            if now - os.path.getmtime(path) > _STALE_DOWNLOAD_SECS:
                os.remove(path)
        except OSError:
            pass


def run_auto_update(
    version: str,
    url: str,
    current_exe: str,
    is_idle: Callable[[], bool],
    on_status: Callable[[str], None] = lambda _msg: None,
    apply_fn: Callable[..., None] = None,
    poll_interval: float = 5.0,
    idle_samples: int = 6,
    on_event: Optional[Callable[[str, object, str], None]] = None,
    apply_now: bool = False,
) -> bool:
    """
    Fully automatic update: download → verify → wait for the app to be idle →
    apply (restart). Blocking — run in a daemon thread.

    ONE run per process. A second call while a run is in flight downloads
    nothing and returns True ("joined"): the run in flight installs the update.
    apply_now=True (the Update Now button, the CRM) makes that run install as
    soon as its download is verified instead of waiting for the idle window.

    Returns False when the download failed after every retry (or the verified
    file changed before install). On success apply_update exits the process,
    so a real run never returns True.

    is_idle() must be cheap and thread-safe; the update is only applied after
    *idle_samples* consecutive polls report idle, so a restart never lands in
    the middle of a dictation.

    apply_fn(new_exe, current_exe, sha256=...) is injectable for tests; the
    default (apply_update) exits the process and never returns.

    on_event(stage, ok, detail) is an optional fire-and-forget telemetry hook —
    called at "download_start" / "download_ok" / "download_fail" / "swap_started"
    so update outcomes can be tracked across the fleet.
    """
    global _run_active
    with _RUN_LOCK:
        if apply_now:
            _apply_now.set()
        if _run_active:
            return True
        _run_active = True
    try:
        return _run_auto_update_once(version, url, current_exe, is_idle,
                                     on_status, apply_fn, poll_interval,
                                     idle_samples, on_event)
    finally:
        with _RUN_LOCK:
            _run_active = False
            _apply_now.clear()


def _run_auto_update_once(version, url, current_exe, is_idle, on_status,
                          apply_fn, poll_interval, idle_samples, on_event) -> bool:
    # A download file of this run's own: nothing else may write it between
    # verification and install. The shared fixed name is what let a second run
    # truncate a verified download.
    dest = _fresh_download_path(os.path.join(
        _app_data_dir(), f"{_DOWNLOAD_PREFIX}-{os.getpid()}-{int(time.time())}.exe"))
    _sweep_stale_downloads(keep=dest)
    _emit(on_event, "download_start", None, f"v{version.lstrip('v')}")

    # Exact asset size and GitHub's SHA-256 from the release check (when it's
    # the same release): detect truncation even without a Content-Length
    # header, and prove the bytes are the ones CI published.
    rel = cached_release() or {}
    expected = 0
    want_sha = ""
    if str(rel.get("version", "")).lstrip("vV") == version.lstrip("vV"):
        expected = int(rel.get("size") or 0)
        want_sha = str(rel.get("sha256") or "").lower()

    # Download with retries — transient network errors must not strand the
    # user on an old build until the next 6-hour check.
    last_exc = None
    digest = ""
    for attempt, backoff in enumerate((0, 20, 60), start=1):
        if backoff:
            time.sleep(backoff)
        try:
            on_status(f"Downloading update v{version.lstrip('v')}…")
            download_update(url, dest, lambda *_: None, expected_bytes=expected)
            verify_exe(dest, expected_bytes=expected)
            digest = file_sha256(dest)
            if want_sha and digest != want_sha:
                raise IOError(f"Download does not match the release checksum "
                              f"({digest[:12]}… vs {want_sha[:12]}…)")
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            print(f"[Updater] Download attempt {attempt} failed: {exc}")
    if last_exc is not None:
        on_status("")  # clear status — next 6-hour check retries from scratch
        _emit(on_event, "download_fail", False, str(last_exc)[:300])
        try:
            os.remove(dest)
        except OSError:
            pass
        return False

    _emit(on_event, "download_ok", True, f"{os.path.getsize(dest)} bytes")
    on_status("Update downloaded — installing when idle…")
    consecutive = 0
    while consecutive < idle_samples and not _apply_now.is_set():
        _apply_now.wait(poll_interval)
        consecutive = consecutive + 1 if is_idle() else 0

    # The file installed must be the file verified: check it again right
    # before handing it over (the swap script checks the hash a third time).
    try:
        verify_exe(dest, expected_bytes=expected)
        if file_sha256(dest) != digest:
            raise IOError("the verified download changed before install")
    except Exception as exc:
        print(f"[Updater] Not installing: {exc}")
        on_status("")
        _emit(on_event, "download_fail", False, f"pre-install check: {exc}"[:300])
        try:
            os.remove(dest)
        except OSError:
            pass
        return False

    on_status(f"Installing v{version.lstrip('v')} — restarting…")
    _emit(on_event, "swap_started", True, f"v{version.lstrip('v')}")
    (apply_fn or apply_update)(dest, current_exe, sha256=digest)
    return False
