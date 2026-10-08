"""Upgrade scenarios on a clean Windows machine, driven by the REAL updaters.

    python tools/e2e_upgrade.py seed-model
    python tools/e2e_upgrade.py upgrade   --from 1.7.2 --assets dist --report out
    python tools/e2e_upgrade.py installed --from 1.8.0 --assets dist --report out
    python tools/e2e_upgrade.py faults    --assets dist --report out
    python tools/e2e_upgrade.py next      --assets dist --next-assets dist-next --report out

RUN ONLY ON A THROWAWAY MACHINE (the CI runner): it edits the hosts file,
trusts a test CA machine-wide, installs and kills Echo, and runs old releases
downloaded from GitHub.

api.github.com and github.com are pointed at tools/fake_release_server.py, so
every copy of the app, whatever its version, finds "the latest release" there
and downloads it from there, with nothing in the app patched. The release it
serves is a CI dry run's signed files.

  upgrade  an old release (e.g. 1.7.2, or 1.6.86 which still asks for the old
           repo name) is installed and running. Its OWN updater module (from
           its git tag, since an old client only checks when signed in) and
           its own swap script install the bridge; the bridge then migrates
           the machine by itself, which also moves the legacy folders to the
           current names. Settings, a user-data file and the speech model must
           come through untouched, with one Installed apps entry.
  installed  the installed layout under the legacy names (v1.8.0, from the
           real GitHub) updates itself through its own updater: the installer
           stages where v1.8.0 looks, and activate.ps1 moves the machine.
  faults   with the bridge installed: a wrong checksum, a cut-off download, a
           release with no installer, no network, the installer killed while
           staging, and the install locked. After each, the machine must still
           run the bridge. Then the faults are cleared and it migrates.
  next     the installed layout at version N updates to N+1 through its own
           updater, and the old version's folder is cleaned up.
"""

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import brand  # noqa: E402
import data_paths  # noqa: E402
import install_layout as il  # noqa: E402
import updater  # noqa: E402
from tools.selftest_install import (NO_WIN, Report, reg_value, stop_all,  # noqa: E402
                                    startup_entry, task_exists, uninstall_entries)

HOSTS = r"C:\Windows\System32\drivers\etc\hosts"
MARK = "# echo-e2e"
REAL = f"https://github.com/{brand.GITHUB_REPO}/releases/download"


# ── The fake GitHub ──────────────────────────────────────────────────────────


class FakeGitHub:
    def __init__(self, work: str):
        self.work = work
        self.control_path = os.path.join(work, "control.json")
        self.proc = None

    def set(self, **kw):
        c = {}
        if os.path.exists(self.control_path):
            with open(self.control_path, encoding="utf-8") as f:
                c = json.load(f)
        c.update(kw)
        with open(self.control_path, "w", encoding="utf-8") as f:
            json.dump(c, f)

    def start(self, version: str, assets: str, rollout: dict):
        self.set(version=version, assets=os.path.abspath(assets), rollout=rollout, fault="")
        cert, key = self._certs()
        self._hosts(True)
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "tools", "fake_release_server.py"),
             "--control", self.control_path, "--cert", cert, "--key", key,
             "--log", os.path.join(self.work, "fake-github.log")])
        time.sleep(3)
        # The machine resolves github to us, and trusts us.
        req = urllib.request.Request(f"https://api.github.com/repos/{brand.GITHUB_REPO}/releases/latest",
                                     headers={"User-Agent": "e2e"})
        with urllib.request.urlopen(req, timeout=10) as r:
            print("[e2e] fake GitHub answers:", json.loads(r.read())["tag_name"])

    def stop(self):
        if self.proc:
            self.proc.kill()
        self._hosts(False)

    def _certs(self):
        openssl = shutil.which("openssl") or r"C:\Program Files\Git\usr\bin\openssl.exe"
        w = self.work
        ext = os.path.join(w, "san.ext")
        with open(ext, "w") as f:
            f.write("subjectAltName=DNS:api.github.com,DNS:github.com\n"
                    "extendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\n")
        run = lambda *a: subprocess.run([openssl, *a], check=True, capture_output=True)  # noqa: E731
        run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj",
            "/CN=Echo E2E Test CA", "-keyout", f"{w}\\ca.key", "-out", f"{w}\\ca.crt")
        run("req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=api.github.com",
            "-keyout", f"{w}\\srv.key", "-out", f"{w}\\srv.csr")
        run("x509", "-req", "-in", f"{w}\\srv.csr", "-CA", f"{w}\\ca.crt", "-CAkey", f"{w}\\ca.key",
            "-CAcreateserial", "-days", "2", "-extfile", ext, "-out", f"{w}\\srv.crt")
        # certutil, not Import-Certificate: a Windows PowerShell child of a
        # pwsh step inherits PowerShell 7's PSModulePath, loads the wrong
        # Security module and has no Cert: drive (DriveNotFound on the runner).
        subprocess.run(["certutil", "-f", "-addstore", "Root", f"{w}\\ca.crt"],
                       check=True, capture_output=True, creationflags=NO_WIN)
        return f"{w}\\srv.crt", f"{w}\\srv.key"

    @staticmethod
    def _hosts(on: bool):
        with open(HOSTS, "r", encoding="utf-8", errors="replace") as f:
            lines = [l for l in f.read().splitlines() if MARK not in l]
        if on:
            lines += [f"127.0.0.1 api.github.com {MARK}", f"127.0.0.1 github.com {MARK}"]
        with open(HOSTS, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, creationflags=NO_WIN)


# ── Watching the app ─────────────────────────────────────────────────────────


def ping_version(timeout: float = 2):
    try:
        with urllib.request.urlopen("http://127.0.0.1:47832/ping", timeout=timeout) as r:
            return json.loads(r.read().decode()).get("version")
    except Exception:
        return None


def wait_for(pred, secs: float, every: float = 2.0):
    deadline = time.time() + secs
    while time.time() < deadline:
        try:
            v = pred()
            if v:
                return v
        except Exception:
            pass
        time.sleep(every)
    return None


def canonical() -> str:
    return il.canonical_exe()


def start_canonical():
    subprocess.Popen([canonical()], cwd=il.install_dir())


def restart():
    stop_all()
    start_canonical()


def model_listing() -> dict:
    root = os.path.join(il.install_dir(), "models")
    out = {}
    for dirpath, _d, names in os.walk(root):
        for n in names:
            # The checksum record the app writes the first time it verifies
            # the model: new after an update, and not a re-download.
            if n == ".verified.json":
                continue
            p = os.path.join(dirpath, n)
            out[os.path.relpath(p, root)] = (os.path.getsize(p), int(os.path.getmtime(p)))
    return out


def collect_logs(rep: Report):
    # Both folders: a failed or partial migration leaves logs in either.
    for d, tag in ((data_paths.new_local_dir(), ""), (data_paths.legacy_local_dir(), "legacy-")):
        if not os.path.isdir(d):
            continue
        names = [il.UPDATE_LOG, "startup-error.log", "install-state.json"]
        names += [n for n in os.listdir(d) if n.startswith("setup-") and n.endswith(".log")]
        for n in names:
            try:
                shutil.copy(os.path.join(d, n), os.path.join(rep.out, tag + n))
            except OSError:
                pass
        try:
            with open(os.path.join(rep.out, tag + "listing.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(sorted(os.listdir(d))))
        except OSError:
            pass
    for slug in (brand.FILE_SLUG, brand.LEGACY_FILE_SLUG):
        try:
            shutil.copy(os.path.join(tempfile.gettempdir(), f"{slug}_update.log"),
                        os.path.join(rep.out, f"{slug}_update.log"))
        except OSError:
            pass


def check_migrated(rep: Report, version: str, label: str):
    exe = canonical()
    rep.check(f"{label}: canonical exe is the installed layout", il.is_installed_layout_exe(exe))
    rep.check(f"{label}: installed layout is whole", il.layout_ok(exe))
    rep.check(f"{label}: app runs {version}", ping_version() == version, ping_version())
    rep.check(f"{label}: no pending folder left",
              not [d for d in os.listdir(il.install_dir()) if d.startswith(brand.PENDING_DIR_PREFIX)])
    rep.check(f"{label}: one Installed apps entry", uninstall_entries() == [brand.UNINSTALL_KEY_NAME],
              uninstall_entries())
    for scheme in (brand.URL_SCHEME, brand.LEGACY_URL_SCHEME):
        cmd = reg_value("Software\\Classes\\" + scheme + r"\shell\open\command") or ""
        rep.check(f"{label}: {scheme}:// opens the canonical exe", exe.lower() in cmd.lower(), cmd)
    rep.check(f"{label}: Run entry opens the canonical exe",
              exe.lower() in startup_entry().lower(), startup_entry())
    rep.check(f"{label}: logon task present", task_exists())
    # v1.8.5: everything under the current names, nothing under the legacy ones.
    rep.check(f"{label}: runs from the current folder",
              os.path.dirname(exe).lower() == data_paths.new_local_dir().lower(), exe)
    rep.check(f"{label}: legacy local folder gone",
              wait_for(lambda: not os.path.exists(data_paths.legacy_local_dir()), 120),
              os.listdir(data_paths.legacy_local_dir())
              if os.path.isdir(data_paths.legacy_local_dir()) else "")
    rep.check(f"{label}: legacy roaming folder gone",
              wait_for(lambda: not os.path.exists(data_paths.legacy_roaming_dir()), 30),
              os.listdir(data_paths.legacy_roaming_dir())
              if os.path.isdir(data_paths.legacy_roaming_dir()) else "")
    rep.check(f"{label}: no logon task under the legacy name",
              not task_exists(brand.LEGACY_TASK_NAME))


def seed_user_data() -> dict:
    cfg = os.path.join(il.install_dir(), "config.json")
    with open(cfg, encoding="utf-8") as f:
        data = json.load(f)
    data["custom_vocabulary"] = "E2eSentinelWord"
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    roaming = data_paths.roaming_dir()
    os.makedirs(roaming, exist_ok=True)
    with open(os.path.join(roaming, "e2e-sentinel.txt"), "w") as f:
        f.write("keep me")
    return model_listing()


def check_user_data(rep: Report, models_before: dict, label: str):
    with open(os.path.join(il.install_dir(), "config.json"), encoding="utf-8") as f:
        rep.check(f"{label}: settings survived",
                  json.load(f).get("custom_vocabulary") == "E2eSentinelWord")
    rep.check(f"{label}: %APPDATA% data survived", os.path.exists(os.path.join(
        data_paths.new_roaming_dir(), "e2e-sentinel.txt")))
    after = model_listing()
    rep.check(f"{label}: speech model untouched (not re-downloaded)",
              models_before and after == models_before,
              f"{len(models_before)} files before, {len(after)} after")


def migrated_to(version: str):
    return (il.is_installed_layout_exe(canonical()) and ping_version() == version
            and il._read_json(os.path.join(il.install_dir(), il.HEALTH_FILE)).get("version") == version)


# ── Scenarios ────────────────────────────────────────────────────────────────


def install_old(rep: Report, work: str, old: str):
    """Download release *old* from the real GitHub and install it the way a
    user did: run the downloaded exe once."""
    dl = os.path.join(work, "Downloads")
    os.makedirs(dl, exist_ok=True)
    exe = os.path.join(dl, brand.UPDATE_ASSET)
    urllib.request.urlretrieve(f"{REAL}/v{old}/{brand.UPDATE_ASSET}", exe)
    subprocess.Popen([exe], cwd=dl)
    ok = wait_for(lambda: ping_version() == old and os.path.exists(canonical()), 240)
    rep.check(f"v{old} installed and running", ok, ping_version())
    restart()
    rep.check(f"v{old} runs from the canonical exe", wait_for(lambda: ping_version() == old, 180))


def drive_old_updater(rep: Report, work: str, old: str):
    """The old version's OWN updater and swap script, from its git tag. (An
    old client checks only when signed in; the code that runs is the same.)"""
    src = os.path.join(work, f"src-{old}")
    zpath = os.path.join(work, f"v{old}.zip")
    subprocess.run(["git", "archive", "--format=zip", f"v{old}", "-o", zpath], cwd=ROOT, check=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(src)
    driver = os.path.join(work, "old_updater.py")
    with open(driver, "w", encoding="utf-8") as f:
        f.write(
            "import sys\n"
            f"sys.path.insert(0, {src!r})\n"
            "import updater\n"
            "info = updater.get_latest_release()\n"
            "print('old updater sees', info, flush=True)\n"
            "if not info: sys.exit(3)\n"
            f"updater.run_auto_update(info['version'], info['download_url'], {canonical()!r},\n"
            "                        is_idle=lambda: True, poll_interval=0.0, idle_samples=1)\n"
            "sys.exit(4)\n")
    r = subprocess.run([sys.executable, driver], cwd=src, timeout=900,
                       capture_output=True, text=True)
    with open(os.path.join(rep.out, f"old-updater-{old}.log"), "w", encoding="utf-8") as f:
        f.write(r.stdout + r.stderr)
    rep.check(f"v{old}'s updater downloaded, verified and handed over", r.returncode == 0,
              r.returncode)


def scenario_upgrade(rep: Report, work: str, assets: str, old: str, version: str):
    install_old(rep, work, old)
    models = seed_user_data()
    gh = FakeGitHub(work)
    gh.start(version, assets, {"migrate_percent": 100})
    try:
        drive_old_updater(rep, work, old)
        bridge = wait_for(lambda: ping_version() == version, 300)
        rep.check(f"v{old}'s swap script installed the bridge and it started", bridge, ping_version())
        t0 = time.time()
        done = wait_for(lambda: migrated_to(version), 1500, every=5)
        rep.measure(f"migration_seconds_after_bridge_start_from_{old}", round(time.time() - t0))
        rep.check("the bridge moved the machine to the installed layout", done)
        check_migrated(rep, version, f"from v{old}")
        check_user_data(rep, models, f"from v{old}")
        rep.check("old onefile unpack folders cleaned up", wait_for(lambda: not [
            n for n in os.listdir(os.path.join(il.install_dir(), "runtime"))
            if n.startswith("_MEI")] if os.path.isdir(os.path.join(il.install_dir(), "runtime")) else True, 120))
    finally:
        collect_logs(rep)
        gh.stop()


def _still_bridge(rep: Report, version: str, label: str):
    ok = wait_for(lambda: ping_version() == version, 240)
    rep.check(f"{label}: the bridge is still running", ok, ping_version())
    rep.check(f"{label}: the canonical exe was not replaced",
              not il.is_installed_layout_exe(canonical()))


def _reset_migration_state():
    for n in (il.MIGRATION_FILE, il.BAD_VERSION_FILE):
        try:
            os.remove(os.path.join(il.install_dir(), n))
        except OSError:
            pass


def _failures(version: str) -> int:
    return il.migration_failures(version, il.install_dir())


def scenario_faults(rep: Report, work: str, assets: str, version: str):
    gh = FakeGitHub(work)
    gh.start(version, assets, {"migrate_percent": 0})   # closed while installing
    try:
        dl = os.path.join(work, "Downloads")
        os.makedirs(dl, exist_ok=True)
        bridge = os.path.join(dl, brand.UPDATE_ASSET)
        shutil.copy(os.path.join(assets, brand.UPDATE_ASSET), bridge)
        subprocess.Popen([bridge], cwd=dl)
        # Real machines only ever run the bridge from the canonical path (an
        # old updater swaps it in there and starts it). The Downloads copy puts
        # it there; restart so that copy is the one running, with its config
        # beside it. Seeding settings beside the Downloads copy tested nothing.
        rep.check("bridge copied itself to the canonical path",
                  wait_for(lambda: ping_version() == version and os.path.exists(canonical()), 240),
                  canonical())
        restart()

        def bridge_state():
            return {"ping": ping_version(), "canonical": canonical(),
                    "canonical_exists": os.path.exists(canonical()),
                    "config": os.path.join(il.install_dir(), "config.json"),
                    "config_exists": os.path.exists(os.path.join(il.install_dir(), "config.json"))}
        up = wait_for(lambda: (lambda st: st["ping"] == version and st["canonical_exists"]
                               # the copy at the canonical path writes its config
                               # on first run; seeding before that raced it
                               and st["config_exists"])(bridge_state()), 240)
        rep.check("bridge installed and running", up, "" if up else bridge_state())
        models = seed_user_data()

        for fault in ("bad-digest", "truncate"):
            _reset_migration_state()
            gh.set(fault=fault, rollout={"migrate_percent": 100})
            restart()
            failed = wait_for(lambda: _failures(version) >= 1, 900, every=5)
            rep.check(f"{fault}: the installer was refused and the failure counted", failed)
            _still_bridge(rep, version, fault)

        for fault in ("no-setup", "offline"):
            _reset_migration_state()
            gh.set(fault=fault, rollout={"migrate_percent": 100})
            restart()
            time.sleep(240)                   # past the start-up check and the idle window
            _still_bridge(rep, version, fault)
            rep.check(f"{fault}: nothing was staged",
                      not os.path.exists(os.path.join(il.install_dir(), il.pending_dir_name(version))))

        # The installer killed while it lays files out.
        _reset_migration_state()
        gh.set(fault="", rollout={"migrate_percent": 100})
        restart()
        pending = os.path.join(il.install_dir(), il.pending_dir_name(version))
        seen = wait_for(lambda: os.path.isdir(pending), 600, every=0.5)
        rep.check("kill-stage: staging started", seen)
        subprocess.run(["taskkill", "/F", "/IM", updater._SETUP_PREFIX + "*"], capture_output=True,
                       creationflags=NO_WIN)
        failed = wait_for(lambda: _failures(version) >= 1, 600, every=5)
        rep.check("kill-stage: the failed stage was counted", failed)
        _still_bridge(rep, version, "kill-stage")

        # The install locked against replacement (readable, so it still runs).
        _reset_migration_state()
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = ctypes.c_void_p
        h = k32.CreateFileW(canonical(), 0x80000000, 0x1, None, 3, 0x80, None)
        rep.check("locked: holding the canonical exe", h not in (None, ctypes.c_void_p(-1).value))
        try:
            restart()
            # v1.8.5 moves the legacy folder first, and a held exe stops that
            # (exit 6, nothing changed); either refusal leaves the bridge.
            wait_for(lambda: any(t in open(os.path.join(il.install_dir(), il.UPDATE_LOG),
                                           encoding="utf-8", errors="replace").read()
                                 for t in ("exe swap failed", "could not be moved")),
                     900, every=5)
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
        _still_bridge(rep, version, "locked")

        # Faults cleared: it migrates, keeping everything.
        _reset_migration_state()
        gh.set(fault="", rollout={"migrate_percent": 100})
        restart()
        rep.check("after the faults, the migration succeeds",
                  wait_for(lambda: migrated_to(version), 1500, every=5))
        check_migrated(rep, version, "after faults")
        check_user_data(rep, models, "after faults")
    finally:
        collect_logs(rep)
        gh.stop()


def scenario_installed(rep: Report, work: str, assets: str, old: str, version: str):
    """v1.8.0's installed layout, under the legacy names, updated by its own
    updater: /STAGEONLY without /DIR stages in the legacy folder, v1.8.0 checks
    the staged exe under the legacy name, then activate.ps1 moves everything."""
    dl = os.path.join(work, "Downloads")
    os.makedirs(dl, exist_ok=True)
    setup = os.path.join(dl, brand.LEGACY_SETUP_UPDATE_ASSET)
    urllib.request.urlretrieve(f"{REAL}/v{old}/{brand.LEGACY_SETUP_UPDATE_ASSET}", setup)
    p = subprocess.run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=900)
    rep.check(f"v{old} installed with its installer", p.returncode == 0, p.returncode)
    rep.check(f"v{old} is in the legacy folder", data_paths.uses_legacy()
              and il.is_installed_layout_exe(canonical()), canonical())
    start_canonical()
    rep.check(f"v{old} running", wait_for(lambda: ping_version() == old, 240))
    models = seed_user_data()
    gh = FakeGitHub(work)
    gh.start(version, assets, {"migrate_percent": 0})
    try:
        restart()
        t0 = time.time()
        rep.check(f"v{old} updated itself to v{version}",
                  wait_for(lambda: migrated_to(version), 1500, every=5))
        rep.measure(f"installed_update_seconds_from_{old}", round(time.time() - t0))
        check_migrated(rep, version, f"v{old} installed")
        check_user_data(rep, models, f"v{old} installed")
        rep.check("one Installed apps entry, under the current key",
                  uninstall_entries() == [brand.UNINSTALL_KEY_NAME], uninstall_entries())
    finally:
        collect_logs(rep)
        gh.stop()


def seed_model() -> int:
    """Put the speech model where an old version expects it (the legacy
    folder), from the CI cache's copy in the current one if there is one."""
    old = os.path.join(data_paths.legacy_local_dir(), "models")
    cached = os.path.join(data_paths.new_local_dir(), "models")
    os.makedirs(data_paths.legacy_local_dir(), exist_ok=True)
    if os.path.isdir(cached) and not os.path.exists(old):
        shutil.move(cached, old)
        shutil.rmtree(data_paths.new_local_dir(), ignore_errors=True)
    import asr_engine
    ok = asr_engine.download_model()
    print("[e2e] model in", asr_engine.models_dir(), "ok" if ok else "FAILED")
    return 0 if ok else 1


def scenario_next(rep: Report, work: str, assets: str, next_assets: str, version: str, nxt: str):
    setup = os.path.join(assets, brand.SETUP_UPDATE_ASSET)
    p = subprocess.run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=900)
    rep.check(f"v{version} installed with the installer", p.returncode == 0, p.returncode)
    start_canonical()
    rep.check(f"v{version} running", wait_for(lambda: ping_version() == version, 240))
    models = seed_user_data()
    gh = FakeGitHub(work)
    gh.start(nxt, next_assets, {"migrate_percent": 0})
    try:
        restart()
        t0 = time.time()
        rep.check(f"v{version} updated itself to v{nxt}",
                  wait_for(lambda: migrated_to(nxt), 1500, every=5))
        rep.measure("onedir_update_seconds_after_start", round(time.time() - t0))
        check_migrated(rep, nxt, f"v{version} to v{nxt}")
        check_user_data(rep, models, f"v{version} to v{nxt}")
        rep.check(f"v{version}'s folder was removed once v{nxt} was healthy", wait_for(
            lambda: not os.path.exists(os.path.join(il.install_dir(), il.contents_dir_name(version))), 180))
    finally:
        collect_logs(rep)
        gh.stop()


def main(argv=None) -> int:
    # The CI step is pwsh: without this every app under test, and every
    # powershell.exe it starts, inherits PowerShell 7's PSModulePath, which a
    # real user's PC never hands an old version (see pyi_runtime).
    import pyi_runtime
    pyi_runtime.use_windows_powershell_modules()
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=("seed-model", "upgrade", "installed", "faults", "next"))
    ap.add_argument("--assets", default="", help="folder with a dry run's release files")
    ap.add_argument("--next-assets", default="")
    ap.add_argument("--from", dest="old", default="")
    ap.add_argument("--report", default="report")
    a = ap.parse_args(argv)
    if a.scenario == "seed-model":
        return seed_model()
    rep = Report(os.path.abspath(a.report))
    work = tempfile.mkdtemp(prefix="echo-e2e-")
    version = _exe_version(os.path.join(a.assets, brand.UPDATE_ASSET))
    stop_all()
    try:
        if a.scenario == "upgrade":
            scenario_upgrade(rep, work, a.assets, a.old, version)
        elif a.scenario == "installed":
            scenario_installed(rep, work, a.assets, a.old, version)
        elif a.scenario == "faults":
            scenario_faults(rep, work, a.assets, version)
        else:
            nxt = _exe_version(os.path.join(a.next_assets, brand.UPDATE_ASSET))
            scenario_next(rep, work, a.assets, a.next_assets, version, nxt)
    except Exception as e:
        rep.check("scenario ran to the end", False, f"{type(e).__name__}: {e}")
    finally:
        stop_all()
    ok = rep.save()
    print("ALL PASSED" if ok else "FAILED: see report.json")
    return 0 if ok else 1


def _exe_version(path: str) -> str:
    """ProductVersion of a release exe, as the app's /ping reports it."""
    ps = f"(Get-Item -LiteralPath '{path}').VersionInfo.ProductVersion"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                         text=True, check=True).stdout.strip()
    # version_info.txt says 1.8.0.0; APP_VERSION (and /ping) say 1.8.0.
    return ".".join(out.split(".")[:3])


if __name__ == "__main__":
    sys.exit(main())
