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


class ActivationContractTests(unittest.TestCase):
    """What the script and the Python side must agree on, without running it."""

    def setUp(self):
        with open(SCRIPT, "r", encoding="utf-8") as f:
            self.src = f.read()

    def test_names_are_the_frozen_ones(self):
        self.assertIn(f"$ExeName = '{brand.CANONICAL_EXE_NAME}'", self.src)
        self.assertIn(f'$Contents = "{brand.CONTENTS_DIR_PREFIX}$Version"', self.src)
        self.assertIn(f'"{brand.PENDING_DIR_PREFIX}$Version"', self.src)
        self.assertIn(f"'{install_layout.HEALTH_FILE}'", self.src)
        self.assertIn(f"'{install_layout.BAD_VERSION_FILE}'", self.src)
        self.assertIn(f"'{install_layout.UPDATE_LOG}'", self.src)
        self.assertIn(f"'{install_layout.MANIFEST_NAME}'", self.src)
        self.assertIn(install_layout.PREVIOUS_SUFFIX, self.src)

    def test_the_exe_swap_is_file_replace_with_a_backup(self):
        # The primitive the onefile updater proved; never a plain copy over
        # the installed exe (that installed a 21 MB prefix and said success).
        self.assertIn("[System.IO.File]::Replace($PendingExe, $Canonical, $Backup)", self.src)
        self.assertNotIn("Copy-Item", self.src)

    def test_processes_elsewhere_are_found_by_their_own_name_only_on_request(self):
        # Never Get-Process -Name "FTC Whisper": the leaf name alone would
        # stop an unrelated copy (or, in this suite, the developer's own Echo).
        self.assertNotIn("Get-Process -Name", self.src)
        self.assertIn("if (-not $ours -and $KillCopiesElsewhere)", self.src)
        self.assertIn("OriginalFilename -eq $ExeName", self.src)


if __name__ == "__main__":
    unittest.main()
