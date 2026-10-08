"""installer/activate.ps1 switches an installed Echo to a new version all or
nothing, and gives the old one back when the new one dies at start.

Executed for real in PowerShell against dummy installs in a temp folder. Each
"exe" is a small Python script run through -LaunchWith, so a test can make the
new version healthy, crash, hang or refuse to register. Names used by the
script are brand.py's frozen values and are pinned here.

Pinned, each against the real script:
  * a good pending version is switched in, and the old folder is left alone;
  * a pending version that differs from its manifest installs NOTHING (a
    missing file, a wrong size, a wrong exe hash) and the old one relaunches;
  * a new version that exits at start without reporting health is rolled back,
    and remembered as bad so the updater does not retry it every six hours;
  * a slow new version is never rolled back;
  * a locked install leaves the previous exe in place;
  * a crash between File.Replace's two renames is repaired on the next run;
  * a re-run after a partial switch finishes it; a re-run after a full one is
    a no-op;
  * Install mode registers through the new exe with the installer's choices;
  * processes outside the install folder are never stopped.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import brand  # noqa: E402
import install_layout  # noqa: E402

SCRIPT = os.path.join(ROOT, "installer", "activate.ps1")
# Start-Process gives a console Python its own visible window, which pops over
# whatever Ryan is typing; the windowless pythonw runs the stand-in just the same.
_PYW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
LAUNCHER = _PYW if os.path.exists(_PYW) else sys.executable

# The stand-in app. Its behaviour is chosen by the line after the marker.
_APP = r'''# BEHAVIOUR={behaviour}
import json, os, sys, time
root = os.path.dirname(os.path.abspath(__file__))
beh = "{behaviour}"
ver = "{version}"
if "--install" in sys.argv:
    with open(os.path.join(root, "registered.json"), "w") as f:
        json.dump({{"version": ver, "argv": sys.argv[1:]}}, f)
    sys.exit(1 if beh == "noregister" else 0)
with open(os.path.join(root, "launched-" + ver + ".txt"), "a") as f:
    f.write("x")
if beh == "crash":
    sys.exit(3)
if beh == "slow":
    time.sleep(12)
    sys.exit(0)
with open(os.path.join(root, "health.json"), "w") as f:
    json.dump({{"version": ver, "pid": os.getpid()}}, f)
time.sleep(2)
'''


@unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell"),
                     "the activation script is PowerShell")
class ActivationTests(unittest.TestCase):
    OLD, NEW = "1.0.0", "2.0.0"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="echo-activate-")
        self.exe = os.path.join(self.dir, brand.CANONICAL_EXE_NAME)

    def tearDown(self):
        for _ in range(10):
            shutil.rmtree(self.dir, ignore_errors=True)
            if not os.path.exists(self.dir):
                return
            time.sleep(0.5)

    # ── Building dummy installs ───────────────────────────────────────────

    def _app(self, version: str, behaviour: str = "healthy") -> str:
        return _APP.format(version=version, behaviour=behaviour)

    def _layout(self, root: str, version: str, behaviour: str = "healthy",
                manifest: bool = True) -> None:
        contents = os.path.join(root, install_layout.contents_dir_name(version))
        os.makedirs(os.path.join(contents, "sub"), exist_ok=True)
        with open(os.path.join(root, brand.CANONICAL_EXE_NAME), "w") as f:
            f.write(self._app(version, behaviour))
        for rel, data in (("python3.dll", b"dll" * 1000 + version.encode()),
                          (os.path.join("sub", "_x.pyd"), b"pyd" * 500),
                          ("config.json", b"{}")):
            with open(os.path.join(contents, rel), "wb") as f:
                f.write(data)
        shutil.copy(SCRIPT, os.path.join(contents, "activate.ps1"))
        if manifest:
            install_layout.write_manifest(root, version)

    def _installed(self, version: str = OLD) -> None:
        self._layout(self.dir, version)

    def _pending(self, version: str = NEW, behaviour: str = "healthy") -> str:
        root = os.path.join(self.dir, install_layout.pending_dir_name(version))
        self._layout(root, version, behaviour)
        return root

    def _run(self, *extra, version: str = NEW, mode: str = "Update",
             relaunch: bool = True, health_timeout: int = 20,
             attempts: int = 30, timeout: int = 120) -> int:
        copy = os.path.join(self.dir, f"activate-{version}.ps1")
        shutil.copy(SCRIPT, copy)
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", copy,
                "-InstallDir", self.dir, "-Version", version, "-Mode", mode,
                "-LaunchWith", LAUNCHER, "-HealthTimeout", str(health_timeout),
                "-Attempts", str(attempts)]
        if relaunch:
            args.append("-Relaunch")
        args += list(extra)
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode

    def _read(self, path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def _canonical_version(self) -> str:
        head = self._read(self.exe)
        return head.split('ver = "', 1)[1].split('"', 1)[0]

    def _log(self) -> str:
        try:
            return self._read(os.path.join(self.dir, install_layout.UPDATE_LOG))
        except OSError:
            return ""

    def _wait_for(self, name: str, secs: float = 15) -> bool:
        deadline = time.time() + secs
        while time.time() < deadline:
            if os.path.exists(os.path.join(self.dir, name)):
                return True
            time.sleep(0.2)
        return False

    # ── The good path ─────────────────────────────────────────────────────

    def test_a_good_version_is_switched_in(self):
        self._installed()
        self._pending()
        self.assertEqual(0, self._run(), self._log())
        self.assertEqual(self.NEW, self._canonical_version())
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "app-2.0.0")))
        # The old folder stays: the new app removes it once it is healthy.
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "app-1.0.0")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "pending-2.0.0")))
        self.assertFalse(os.path.exists(self.exe + ".previous"))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "launched-2.0.0.txt")))
        # The switched-in files are exactly the manifest's.
        manifest = install_layout.load_manifest(
            os.path.join(self.dir, "app-2.0.0", "manifest.json"))
        self.assertEqual([], install_layout.verify_tree(self.dir, manifest))
        # The copy it ran from removes itself.
        self.assertFalse(os.path.exists(os.path.join(self.dir, "activate-2.0.0.ps1")))

    def test_a_slow_version_is_never_rolled_back(self):
        self._installed()
        self._pending(behaviour="slow")
        self.assertEqual(0, self._run(health_timeout=4), self._log())
        self.assertEqual(self.NEW, self._canonical_version())
        self.assertFalse(os.path.exists(os.path.join(self.dir, "bad-version.txt")))

    # ── Nothing changes unless the files are exactly CI's ────────────────

    def _assert_untouched_and_old_relaunched(self, code: int):
        self.assertEqual(2, code, self._log())
        self.assertEqual(self.OLD, self._canonical_version())
        self.assertFalse(os.path.exists(os.path.join(self.dir, "app-2.0.0")))
        self.assertTrue(self._wait_for("launched-1.0.0.txt"), self._log())

    def test_a_missing_file_installs_nothing(self):
        self._installed()
        root = self._pending()
        os.remove(os.path.join(root, "app-2.0.0", "sub", "_x.pyd"))   # AV quarantine
        self._assert_untouched_and_old_relaunched(self._run())
        self.assertIn("missing app-2.0.0/sub/_x.pyd", self._log())

    def test_a_short_file_installs_nothing(self):
        self._installed()
        root = self._pending()
        with open(os.path.join(root, "app-2.0.0", "python3.dll"), "r+b") as f:
            f.truncate(10)                                            # cut off
        self._assert_untouched_and_old_relaunched(self._run())

    def test_a_different_exe_installs_nothing(self):
        self._installed()
        root = self._pending()
        with open(os.path.join(root, brand.CANONICAL_EXE_NAME), "a") as f:
            f.write("\n# tampered\n")
        self._assert_untouched_and_old_relaunched(self._run())

    def test_no_manifest_installs_nothing(self):
        self._installed()
        root = self._pending()
        os.remove(os.path.join(root, "app-2.0.0", "manifest.json"))
        self._assert_untouched_and_old_relaunched(self._run())

    # ── Rollback ──────────────────────────────────────────────────────────

    def test_a_version_that_dies_at_start_is_rolled_back(self):
        self._installed()
        self._pending(behaviour="crash")
        self.assertEqual(5, self._run(), self._log())
        self.assertEqual(self.OLD, self._canonical_version())
        # The old version's folder was never touched, so the old exe runs.
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "app-1.0.0")))
        self.assertTrue(self._wait_for("launched-1.0.0.txt"), self._log())
        self.assertEqual(self.NEW, self._read(
            os.path.join(self.dir, "bad-version.txt")).strip())
        self.assertEqual(self.NEW, install_layout.read_bad_version(self.dir))

    def test_a_locked_install_keeps_the_previous_exe(self):
        self._installed()
        self._pending()
        # Hold the installed exe open with no sharing, as a stuck process or an
        # AV scan would.
        import msvcrt  # noqa: F401  (Windows only; the class is skipped elsewhere)
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = ctypes.c_void_p
        h = k32.CreateFileW(self.exe, 0x80000000, 0, None, 3, 0x80, None)
        self.assertNotEqual(h, ctypes.c_void_p(-1).value)
        try:
            code = self._run(attempts=2, relaunch=False)
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
        self.assertEqual(3, code, self._log())
        self.assertEqual(self.OLD, self._canonical_version())
        # The verified new exe is still staged for the next attempt.
        self.assertTrue(os.path.exists(
            os.path.join(self.dir, "pending-2.0.0", brand.CANONICAL_EXE_NAME)))

    # ── Interrupted runs ──────────────────────────────────────────────────

    def test_a_missing_exe_beside_its_backup_is_repaired(self):
        # A kill between File.Replace's two renames: canonical gone, backup left.
        self._installed()
        os.replace(self.exe, self.exe + ".previous")
        root = self._pending()
        os.remove(os.path.join(root, "app-2.0.0", "manifest.json"))   # and a bad pending
        self.assertEqual(2, self._run(), self._log())
        self.assertEqual(self.OLD, self._canonical_version())
        self.assertIn("Repaired", self._log())

    def test_a_run_after_the_folder_moved_finishes_the_switch(self):
        self._installed()
        root = self._pending()
        os.replace(os.path.join(root, "app-2.0.0"), os.path.join(self.dir, "app-2.0.0"))
        self.assertEqual(0, self._run(), self._log())
        self.assertEqual(self.NEW, self._canonical_version())

    def test_a_leftover_folder_from_a_failed_attempt_is_replaced(self):
        self._installed()
        self._pending()
        junk = os.path.join(self.dir, "app-2.0.0")
        os.makedirs(junk)
        with open(os.path.join(junk, "half-written.dll"), "wb") as f:
            f.write(b"x")
        self.assertEqual(0, self._run(), self._log())
        self.assertFalse(os.path.exists(os.path.join(junk, "half-written.dll")))
        self.assertEqual(self.NEW, self._canonical_version())

    def test_a_run_after_a_finished_switch_changes_nothing(self):
        self._installed()
        self._pending()
        self.assertEqual(0, self._run(relaunch=False), self._log())
        self.assertEqual(0, self._run(relaunch=False), self._log())
        self.assertEqual(self.NEW, self._canonical_version())
        self.assertIn("already in place", self._log())

    # ── Install mode ──────────────────────────────────────────────────────

    def test_a_fresh_install_registers_with_the_installers_choices(self):
        self._pending()
        self.assertEqual(0, self._run("-NoDesktopShortcut", "-StartWithWindows", "0",
                                      mode="Install", relaunch=False), self._log())
        self.assertEqual(self.NEW, self._canonical_version())
        reg = json.loads(self._read(os.path.join(self.dir, "registered.json")))
        self.assertEqual(self.NEW, reg["version"])
        self.assertEqual(["--install", "/S", "--no-desktop-shortcut",
                          "--start-with-windows=0"], reg["argv"])

    def test_a_failed_registration_rolls_back(self):
        self._installed()
        self._pending(behaviour="noregister")
        self.assertEqual(4, self._run(mode="Install", relaunch=False), self._log())
        self.assertEqual(self.OLD, self._canonical_version())

    # ── The script itself ─────────────────────────────────────────────────

    def test_the_script_parses_and_is_ascii(self):
        # Windows PowerShell reads a BOM-less script as ANSI: keep it ASCII.
        with open(SCRIPT, "rb") as f:
            self.assertTrue(all(b < 128 for b in f.read()))
        check = ("$e = $null; [void][System.Management.Automation.Language.Parser]::"
                 f"ParseFile('{SCRIPT}', [ref]$null, [ref]$e); $e.Count")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", check],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual("0", out.stdout.strip(), out.stdout + out.stderr)


@unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell"),
                     "the activation script is PowerShell")
class MigrationTests(unittest.TestCase):
    """v1.8.5: the legacy folders become the current ones during activation,
    and go back exactly as they were when anything fails. Runs the real script
    against a fake %LOCALAPPDATA% and %APPDATA% in a temp folder."""

    OLD, NEW = "1.8.0", "1.8.1"

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="echo-migrate-")
        self.local = os.path.join(self.base, "Local")
        self.roaming = os.path.join(self.base, "Roaming")
        self.legacy = os.path.join(self.local, brand.LEGACY_DATA_DIR_NAME)
        self.new = os.path.join(self.local, brand.DATA_DIR_NAME)
        self.legacy_roam = os.path.join(self.roaming, brand.LEGACY_DATA_DIR_NAME)
        self.new_roam = os.path.join(self.roaming, brand.DATA_DIR_NAME)
        os.makedirs(self.legacy_roam)
        with open(os.path.join(self.legacy_roam, "history.json"), "w") as f:
            f.write('["kept"]')
        self._helper = ActivationTests()

    def tearDown(self):
        for _ in range(10):
            shutil.rmtree(self.base, ignore_errors=True)
            if not os.path.exists(self.base):
                return
            time.sleep(0.5)

    def _legacy_install(self, stage_in: str = "", behaviour: str = "healthy") -> None:
        """v1.8.0 as it is on disk: the legacy exe on app-1.8.0, the model, and
        v1.8.5 staged by the installer (in the legacy folder, where a v1.8.0
        updater asks for it, unless *stage_in* says otherwise)."""
        self._helper._layout(self.legacy, self.OLD)
        os.replace(os.path.join(self.legacy, brand.CANONICAL_EXE_NAME),
                   os.path.join(self.legacy, brand.LEGACY_CANONICAL_EXE_NAME))
        os.makedirs(os.path.join(self.legacy, "models"))
        with open(os.path.join(self.legacy, "models", "encoder.onnx"), "wb") as f:
            f.write(b"model" * 1000)
        pending = os.path.join(stage_in or self.legacy,
                               install_layout.pending_dir_name(self.NEW))
        self._helper._layout(pending, self.NEW, behaviour)
        # The copy v1.8.0's own check hashes, under the name it knows.
        shutil.copy(os.path.join(pending, brand.CANONICAL_EXE_NAME),
                    os.path.join(pending, brand.LEGACY_CANONICAL_EXE_NAME))

    def _run(self, install_dir: str, *extra, mode: str = "Update",
             relaunch: bool = True, attempts: int = 30) -> int:
        copy = os.path.join(install_dir, f"activate-{self.NEW}.ps1")
        shutil.copy(SCRIPT, copy)
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", copy,
                "-InstallDir", install_dir, "-Version", self.NEW, "-Mode", mode,
                "-LaunchWith", sys.executable, "-HealthTimeout", "20",
                "-Attempts", str(attempts), "-NoSystemChanges"]
        if relaunch:
            args.append("-Relaunch")
        args += list(extra)
        env = dict(os.environ, APPDATA=self.roaming, LOCALAPPDATA=self.local)
        # Started from inside the folder it moves, as the v1.8.0 to v1.8.4 updater is.
        r = subprocess.run(args, capture_output=True, text=True, timeout=240,
                           env=env, cwd=install_dir)
        return r.returncode

    def _version_of(self, exe: str) -> str:
        with open(exe, "r", encoding="utf-8") as f:
            return f.read().split('ver = "', 1)[1].split('"', 1)[0]

    def _log(self) -> str:
        out = []
        for d in (self.new, self.legacy):
            try:
                with open(os.path.join(d, install_layout.UPDATE_LOG), encoding="utf-8",
                          errors="replace") as f:
                    out.append(f.read())
            except OSError:
                pass
        return "\n".join(out)

    def _wait(self, path: str, secs: float = 15) -> bool:
        deadline = time.time() + secs
        while time.time() < deadline:
            if os.path.exists(path):
                return True
            time.sleep(0.2)
        return False

    def _assert_legacy_intact(self):
        exe = os.path.join(self.legacy, brand.LEGACY_CANONICAL_EXE_NAME)
        self.assertEqual(self.OLD, self._version_of(exe), self._log())
        self.assertTrue(os.path.isdir(os.path.join(self.legacy, "app-" + self.OLD)))
        self.assertTrue(os.path.exists(os.path.join(self.legacy, "models", "encoder.onnx")))
        self.assertTrue(os.path.exists(os.path.join(self.legacy_roam, "history.json")))
        self.assertFalse(os.path.exists(os.path.join(self.new, brand.MIGRATED_MARKER)))

    def test_an_update_from_the_legacy_folder_moves_everything(self):
        self._legacy_install()
        self.assertEqual(0, self._run(self.legacy), self._log())
        exe = os.path.join(self.new, brand.CANONICAL_EXE_NAME)
        self.assertEqual(self.NEW, self._version_of(exe))
        self.assertFalse(os.path.exists(self.legacy), "the legacy folder is gone")
        self.assertFalse(os.path.exists(self.legacy_roam))
        # The model and the user's history came along; nothing is re-downloaded.
        self.assertTrue(os.path.exists(os.path.join(self.new, "models", "encoder.onnx")))
        with open(os.path.join(self.new_roam, "history.json")) as f:
            self.assertEqual('["kept"]', f.read())
        self.assertTrue(os.path.exists(os.path.join(self.new, brand.MIGRATED_MARKER)))
        self.assertTrue(os.path.exists(os.path.join(self.new, "launched-" + self.NEW + ".txt")))
        # Nothing under a legacy name is left in the new folder.
        left = [n for n in os.listdir(self.new) if brand.LEGACY_EXE_BASENAME in n]
        self.assertEqual([], left)
        self.assertFalse(os.path.exists(os.path.join(self.new, "pending-" + self.NEW)))

    def test_a_version_that_dies_at_start_goes_back_to_the_legacy_folder(self):
        self._legacy_install(behaviour="crash")
        self.assertEqual(5, self._run(self.legacy), self._log())
        self._assert_legacy_intact()
        self.assertFalse(os.path.exists(os.path.join(self.new, brand.CANONICAL_EXE_NAME)))
        self.assertFalse(os.path.exists(self.new_roam))
        # Remembered as bad where the previous version looks for it.
        self.assertEqual(self.NEW, install_layout.read_bad_version(self.legacy))
        self.assertTrue(self._wait(os.path.join(self.legacy, "launched-" + self.OLD + ".txt")),
                        self._log())

    def test_a_locked_roaming_file_undoes_the_local_move(self):
        self._legacy_install()
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = ctypes.c_void_p
        # Held open without FILE_SHARE_DELETE, as an indexer or AV scan may:
        # its folder cannot be renamed while it is open.
        h = k32.CreateFileW(os.path.join(self.legacy_roam, "history.json"),
                            0x80000000, 1, None, 3, 0x80, None)
        self.assertNotEqual(h, ctypes.c_void_p(-1).value)
        try:
            code = self._run(self.legacy, attempts=2)
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
        self.assertEqual(6, code, self._log())
        self._assert_legacy_intact()
        # Not the version's fault: the updater may try it again.
        self.assertEqual("", install_layout.read_bad_version(self.legacy))
        self.assertTrue(self._wait(os.path.join(self.legacy, "launched-" + self.OLD + ".txt")),
                        self._log())
        # And the retry, once nothing holds the file, succeeds.
        self.assertEqual(0, self._run(self.legacy), self._log())
        self.assertFalse(os.path.exists(self.legacy))

    def test_a_migration_registers_through_the_new_exe_before_it_is_done(self):
        # Real registry work, so pinned on the script (the e2e runs it for real):
        # after a healthy start, a migration runs "--install /S" and waits, and
        # a failure there only logs (it never undoes a working update).
        with open(SCRIPT, encoding="utf-8") as f:
            src = f.read()
        start = src.index("# 6b.")
        block = src[start:src.index("Remove-Item -LiteralPath $script:Backup -Force", start)]
        self.assertIn("$script:PrevHomeLegacy -and -not $NoSystemChanges", block)
        self.assertIn("Start-Echo @('--install', '/S')", block)
        self.assertIn("WaitForExit(180000)", block)
        self.assertNotIn("Restore-Previous", block)
        self.assertNotIn("Finish", block)
        # After the health check, so only a version that starts is registered.
        self.assertLess(src.index("The new version reported healthy."), src.index("# 6b."))

    def test_a_locked_file_in_the_legacy_folder_leaves_everything_and_relaunches(self):
        # The FIRST move fails, so nothing has moved yet: the previous version
        # must still be started again (CI 2026-10-08: it was not, and the log
        # went to the new folder, which did not exist).
        self._legacy_install()
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = ctypes.c_void_p
        # The e2e's lock: the legacy exe held for reading, shared for reading.
        h = k32.CreateFileW(os.path.join(self.legacy, brand.LEGACY_CANONICAL_EXE_NAME),
                            0x80000000, 1, None, 3, 0x80, None)
        self.assertNotEqual(h, ctypes.c_void_p(-1).value)
        try:
            code = self._run(self.legacy, attempts=2)
            launched = self._wait(os.path.join(self.legacy, "launched-" + self.OLD + ".txt"))
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
        self.assertEqual(6, code, self._log())
        self._assert_legacy_intact()
        self.assertFalse(os.path.exists(self.new), self._log())
        self.assertTrue(launched, self._log())
        self.assertIn("NOT installing", self._log())
        self.assertEqual("", install_layout.read_bad_version(self.legacy))
        # Once nothing holds it, the next try moves the machine.
        self.assertEqual(0, self._run(self.legacy), self._log())
        self.assertFalse(os.path.exists(self.legacy))

    def test_an_install_over_the_legacy_folder_adopts_its_data(self):
        os.makedirs(self.new)
        self._legacy_install(stage_in=self.new)
        self.assertEqual(0, self._run(self.new, mode="Install", relaunch=False), self._log())
        self.assertEqual(self.NEW, self._version_of(os.path.join(self.new, brand.CANONICAL_EXE_NAME)))
        self.assertTrue(os.path.exists(os.path.join(self.new, "registered.json")))
        self.assertTrue(os.path.exists(os.path.join(self.new, "models", "encoder.onnx")))
        self.assertTrue(os.path.exists(os.path.join(self.new_roam, "history.json")))
        self.assertFalse(os.path.exists(self.legacy))
        self.assertTrue(os.path.exists(os.path.join(self.new, brand.MIGRATED_MARKER)))

    def _moved_install(self, behaviour: str = "healthy") -> None:
        """A machine already on the current folder (v1.8.0 here stands for any
        installed version), with a stray legacy folder beside it: an old exe
        run from Downloads unpacks into it."""
        self._helper._layout(self.new, self.OLD)
        with open(os.path.join(self.new, brand.MIGRATED_MARKER), "w") as f:
            f.write("{}")
        os.makedirs(os.path.join(self.legacy, "runtime", "_MEI1"))
        pending = os.path.join(self.new, install_layout.pending_dir_name(self.NEW))
        self._helper._layout(pending, self.NEW, behaviour)

    def test_a_failed_update_on_a_moved_machine_leaves_the_legacy_folder_alone(self):
        self._moved_install(behaviour="crash")
        self.assertEqual(5, self._run(self.new), self._log())
        exe = os.path.join(self.new, brand.CANONICAL_EXE_NAME)
        self.assertEqual(self.OLD, self._version_of(exe), self._log())
        self.assertEqual(self.NEW, install_layout.read_bad_version(self.new))
        self.assertTrue(os.path.exists(os.path.join(self.new, brand.MIGRATED_MARKER)))
        self.assertFalse(os.path.exists(os.path.join(self.legacy, brand.LEGACY_CANONICAL_EXE_NAME)))
        self.assertTrue(self._wait(os.path.join(self.new, "launched-" + self.OLD + ".txt")),
                        self._log())

    def test_an_update_on_a_moved_machine_clears_a_stray_legacy_folder(self):
        self._moved_install()
        self.assertEqual(0, self._run(self.new), self._log())
        self.assertEqual(self.NEW, self._version_of(os.path.join(self.new, brand.CANONICAL_EXE_NAME)))
        self.assertFalse(os.path.exists(self.legacy))
        # The user's roaming data was never the stray's to take.
        self.assertTrue(os.path.exists(os.path.join(self.legacy_roam, "history.json"))
                        or os.path.exists(os.path.join(self.new_roam, "history.json")))

    def test_a_fresh_install_is_marked_as_home(self):
        shutil.rmtree(self.legacy_roam)
        pending = os.path.join(self.new, install_layout.pending_dir_name(self.NEW))
        self._helper._layout(pending, self.NEW)
        self.assertEqual(0, self._run(self.new, mode="Install", relaunch=False), self._log())
        self.assertTrue(os.path.exists(os.path.join(self.new, brand.MIGRATED_MARKER)))

    def test_a_failed_install_over_the_legacy_folder_gives_it_back(self):
        os.makedirs(self.new)
        self._legacy_install(stage_in=self.new, behaviour="noregister")
        self.assertEqual(4, self._run(self.new, mode="Install", relaunch=False), self._log())
        self._assert_legacy_intact()


class ActivationContractTests(unittest.TestCase):
    """What the script and the Python side must agree on, without running it."""

    def setUp(self):
        with open(SCRIPT, "r", encoding="utf-8") as f:
            self.src = f.read()

    def test_every_native_call_that_can_write_stderr_is_inside_a_try(self):
        # ErrorActionPreference Stop + Windows PowerShell 5.1: a native
        # command's stderr line is a terminating error even when redirected
        # to $null. An unguarded `schtasks /query` for a task that does not
        # exist ended activation with exit 1 (CI self-test, 2026-10-07).
        lines = self.src.splitlines()
        for i, line in enumerate(lines):
            s = line.strip()
            if not ("& " in s and ".exe" in s and "2>" in s):
                continue
            window = "\n".join(lines[max(0, i - 3):i + 1])
            with self.subTest(line=i + 1):
                self.assertTrue(s.startswith("try {") or "try {" in window,
                                f"unguarded native call: {s}")

    def test_names_are_the_frozen_ones(self):
        self.assertIn(f"$ExeName = '{brand.CANONICAL_EXE_NAME}'", self.src)
        self.assertIn(f"$DirName = '{brand.DATA_DIR_NAME}'", self.src)
        self.assertIn(f"$LegacyExeName = '{brand.LEGACY_CANONICAL_EXE_NAME}'", self.src)
        self.assertIn(f"$LegacyDirName = '{brand.LEGACY_DATA_DIR_NAME}'", self.src)
        self.assertIn(f"$MarkerName = '{brand.MIGRATED_MARKER}'", self.src)
        self.assertIn(f"$TaskName = '{brand.TASK_NAME}'", self.src)
        self.assertIn(f"$RunValueName = '{brand.RUN_VALUE_NAME}'", self.src)
        self.assertIn(f"$LegacyTaskName = '{brand.LEGACY_TASK_NAME}'", self.src)
        self.assertIn(f"$LegacyRunValueName = '{brand.LEGACY_RUN_VALUE_NAME}'", self.src)
        self.assertIn(f"$UninstallKeyName = '{brand.UNINSTALL_KEY_NAME}'", self.src)
        self.assertIn(f"$UrlScheme = '{brand.URL_SCHEME}'", self.src)
        self.assertIn(f'Contents = "{brand.CONTENTS_DIR_PREFIX}$Version"', self.src)
        self.assertIn(f'"{brand.PENDING_DIR_PREFIX}$Version"', self.src)
        self.assertIn(f"'{install_layout.HEALTH_FILE}'", self.src)
        self.assertIn(f"'{install_layout.BAD_VERSION_FILE}'", self.src)
        self.assertIn(f"'{install_layout.UPDATE_LOG}'", self.src)
        self.assertIn(f"'{install_layout.MANIFEST_NAME}'", self.src)
        self.assertIn(install_layout.PREVIOUS_SUFFIX, self.src)

    def test_the_exe_swap_is_file_replace_with_a_backup(self):
        # The primitive the onefile updater proved; never a plain copy over
        # the installed exe (that installed a 21 MB prefix and said success).
        self.assertIn("[System.IO.File]::Replace($script:PendingExe, $script:Canonical, "
                      "$script:Backup)", self.src)
        self.assertNotIn("Copy-Item", self.src)

    def test_processes_elsewhere_are_found_by_their_own_name_only_on_request(self):
        # Never Get-Process -Name "FTC Whisper": the leaf name alone would
        # stop an unrelated copy (or, in this suite, the developer's own Echo).
        self.assertNotIn("Get-Process -Name", self.src)
        self.assertIn("if (-not $ours -and $KillCopiesElsewhere)", self.src)
        self.assertIn("($orig -eq $ExeName) -or ($orig -eq $LegacyExeName)", self.src)

    def test_start_with_windows_crosses_the_migration_as_it_was(self):
        import app_install
        # The bridge launches like every sign-in launcher, and a Task Manager
        # disable under the legacy name moves to the current one.
        bridge = self.src[self.src.index("$legacyTask = "):self.src.index("# 6. Register")]
        self.assertIn('--startup"', bridge)
        self.assertIn("-Name $LegacyRunValueName", bridge)
        self.assertIn("New-ItemProperty -LiteralPath $ApprovedKey -Name $RunValueName", bridge)
        self.assertIn("-PropertyType Binary", bridge)
        # A rollback takes the new pair away again.
        undo = self.src[self.src.index("function Remove-NewRegistrations"):
                        self.src.index("function Retarget-Links")]
        self.assertIn("foreach ($k in @($RunKey, $ApprovedKey))", undo)
        for key, var in ((app_install.RUN_KEY, "$RunKey"),
                         (app_install.STARTUP_APPROVED_KEY, "$ApprovedKey")):
            self.assertIn(f"{var} = 'HKCU:\\{key}'", self.src)

    def test_the_folders_move_only_after_leaving_them(self):
        # The v1.8.0 to v1.8.4 updater starts this script inside the legacy folder; a
        # folder that is any process's current directory cannot be renamed.
        self.assertLess(self.src.index("SetCurrentDirectory"),
                        self.src.index("Adopt-Folder $LegacyDir $NewDir"))


if __name__ == "__main__":
    unittest.main()
