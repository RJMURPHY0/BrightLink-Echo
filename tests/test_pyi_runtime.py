"""The frozen app must always run on the files its own bootloader unpacked.

v1.6.79 (2026-09-14): the updater relaunched the new exe with the old process's
PyInstaller bootloader variables, so it skipped unpacking and ran its onnxruntime
1.30 Python layer on the previous build's 1.29 binary. Every inference raised,
the engine swallowed it, and every dictation came back "No speech detected".

Pinned here:
  1. clean_launch_env() strips every bootloader variable and requests a reset.
  2. The updater's swap script, the stale-copy handoff and the startup relaunch
     all launch with that environment.
  3. running_on_foreign_runtime() tells a normal launch (parent is our own
     bootloader) from an inherited one (parent is anything else, or gone), and
     a relaunch can never loop.
  4. The guard runs before any other project import in app.py.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyi_runtime as R

EXE = r"C:\Users\x\AppData\Local\FTC Whisper\FTC Whisper.exe"
CHILD_ENV = {
    "_PYI_APPLICATION_HOME_DIR": r"C:\Users\x\AppData\Local\FTC Whisper\runtime\_MEI1",
    "_PYI_ARCHIVE_FILE": EXE,
    "_PYI_PARENT_PROCESS_LEVEL": "1",
    "PATH": r"C:\Windows",
}


def _src(name):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class CleanEnvTests(unittest.TestCase):
    def test_bootloader_variables_are_removed_and_reset_requested(self):
        env = R.clean_launch_env(dict(CHILD_ENV, _PYI_SPLASH_IPC="9"))
        self.assertFalse([k for k in env if k.upper().startswith("_PYI_")])
        self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertEqual(env["PATH"], r"C:\Windows")

    def test_the_relaunch_guard_is_not_passed_on(self):
        env = R.clean_launch_env(dict(CHILD_ENV, **{R.GUARD_VAR: "1"}))
        self.assertNotIn(R.GUARD_VAR, env)

    def test_it_copies_rather_than_mutating(self):
        base = dict(CHILD_ENV)
        R.clean_launch_env(base)
        self.assertEqual(base, CHILD_ENV)


class ForeignRuntimeTests(unittest.TestCase):
    def check(self, parent_image, environ=None, frozen=True):
        return R.running_on_foreign_runtime(
            frozen=frozen, environ=CHILD_ENV if environ is None else environ,
            executable=EXE, parent_image=parent_image)

    def test_a_normal_launch_is_not_foreign(self):
        self.assertFalse(self.check(EXE))

    def test_case_and_short_path_differences_still_match(self):
        self.assertFalse(self.check(EXE.upper()))

    def test_a_launch_from_the_update_script_is_foreign(self):
        self.assertTrue(self.check(
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"))

    def test_a_parent_that_is_gone_is_foreign(self):
        # The broken v1.6.79 process: the swap script had already exited.
        self.assertTrue(self.check(""))

    def test_source_runs_are_never_foreign(self):
        self.assertFalse(self.check("", frozen=False))

    def test_not_a_onefile_child_is_never_foreign(self):
        env = {k: v for k, v in CHILD_ENV.items()
               if k != "_PYI_APPLICATION_HOME_DIR"}
        self.assertFalse(self.check("", environ=env))

    def test_a_relaunch_never_loops(self):
        self.assertFalse(self.check("", environ=dict(CHILD_ENV, **{R.GUARD_VAR: "1"})))


class LaunchSiteTests(unittest.TestCase):
    """Every place the app starts its own exe must use the clean environment."""

    def test_updater_swap_script_launches_clean(self):
        src = _src("updater.py")
        body = src[src.index("def spawn_swap_script"):src.index("def current_exe_path")]
        self.assertIn("env=pyi_runtime.clean_launch_env()", body)
        # Both Popen calls share **std, which carries the env.
        self.assertEqual(body.count("subprocess.Popen("), body.count("**std"))

    def test_handoff_launches_clean(self):
        src = _src("app.py")
        body = src[src.index("def _handoff_to_canonical_if_newer"):
                   src.index("def _ensure_startup_task")]
        self.assertIn("env=pyi_runtime.clean_launch_env()", body)

    def test_guard_runs_before_any_project_import(self):
        src = _src("app.py")
        guard = src.index("pyi_runtime.relaunch_if_foreign_runtime(")
        self.assertLess(guard, src.index("from config import Config"))
        self.assertLess(guard, src.index("from app_window import AppWindow"))

    def test_selftest_exits_before_the_mutex(self):
        src = _src("app.py")
        main = src[src.index("def _main() -> None:"):]
        self.assertLess(main.index('"--selftest"'),
                        main.index("_ensure_single_instance()"))


class ConstraintsTests(unittest.TestCase):
    def test_ci_installs_with_the_pinned_set(self):
        wf = _src(os.path.join(".github", "workflows", "build-release.yml"))
        self.assertIn("-c constraints.txt", wf)
        pins = _src("constraints.txt")
        for pkg in ("onnxruntime==", "onnx-asr==", "numpy==", "pyinstaller==",
                    "faster-whisper==", "ctranslate2=="):
            self.assertIn(pkg, pins)

    def test_bootloader_accepts_the_old_updaters_launch(self):
        # Installs on v1.6.78/v1.6.79 relaunch the next version with a leaked
        # bootloader environment. A 6.22.2 bootloader answers that with a
        # "Security validation failure" dialog and the app never starts; 6.22.3
        # starts it and pyi_runtime heals it. Proven with the real app and the
        # swap script's exact launch sequence. Changing this pin means proving
        # that path again with a real build before releasing.
        pins = [ln.strip() for ln in _src("constraints.txt").splitlines()]
        self.assertIn("pyinstaller==6.22.3", pins)


if __name__ == "__main__":
    unittest.main()
