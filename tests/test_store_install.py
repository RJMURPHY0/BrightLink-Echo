"""Microsoft Store install mode and the Start with Windows setting.

The Store runs an EXE installer silently (policy 10.2.9): `--install /S` must
install and exit with no window, and it must run BEFORE the version handoff
and the single-instance mutex, because the app may already be open. Start
with Windows is the consent Store policy 10.2.8 asks for: the logon task is
created only when it is on.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_mod
from config import Config


class InstallFlagTests(unittest.TestCase):
    def test_install_flag_forms(self):
        for argv in (["x", "--install"], ["x", "/install", "/S"], ["x", "--INSTALL"]):
            with mock.patch.object(sys, "argv", argv):
                self.assertTrue(app_mod._install_requested(), argv)
        for argv in (["x"], ["x", "/S"], ["x", "--uninstall"]):
            with mock.patch.object(sys, "argv", argv):
                self.assertFalse(app_mod._install_requested(), argv)

    def test_source_run_refuses(self):
        with mock.patch.object(sys, "frozen", False, create=True):
            self.assertEqual(app_mod._run_silent_install(), 2)


class SilentInstallTests(unittest.TestCase):
    def _run(self, intact: bool, start: bool = True):
        calls = []
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(app_mod, "_ensure_installed_copy",
                               lambda: calls.append("copy")), \
             mock.patch.object(app_mod, "_stable_exe_path",
                               lambda: sys.executable), \
             mock.patch("updater.pyi_archive_intact", lambda p: intact), \
             mock.patch.object(app_mod, "_register_application",
                               lambda: calls.append("register")), \
             mock.patch.object(app_mod, "_register_url_protocol",
                               lambda: calls.append("url")), \
             mock.patch.object(app_mod, "_installed_start_with_windows",
                               lambda: start), \
             mock.patch.object(app_mod, "_sync_startup_task",
                               lambda on: calls.append(("startup", on))), \
             mock.patch.object(app_mod, "_log_startup_error", lambda e: None):
            code = app_mod._run_silent_install()
        return code, calls

    def test_installs_and_registers(self):
        code, calls = self._run(intact=True)
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["copy", "register", "url", ("startup", True)])

    def test_respects_start_with_windows_off(self):
        code, calls = self._run(intact=True, start=False)
        self.assertEqual(code, 0)
        self.assertIn(("startup", False), calls)

    def test_broken_copy_fails_without_registering(self):
        code, calls = self._run(intact=False)
        self.assertEqual(code, 1)
        self.assertEqual(calls, ["copy"])


class LockedInstalledCopyTests(unittest.TestCase):
    """Store install while the app is open: the installed exe is locked, the
    copy fails, and every registration must still point at the installed
    copy, never at the Store's temporary download."""

    def _copy(self, intact: bool) -> str:
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "download.exe")
            dst = os.path.join(d, "installed.exe")
            for p in (src, dst):
                with open(p, "wb") as f:
                    f.write(b"MZ")
            os.utime(dst, (1, 1))  # installed copy older: a copy is attempted

            def _locked(*_a, **_k):
                raise PermissionError("in use")

            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "executable", src), \
                 mock.patch.object(app_mod, "_stable_exe_path", lambda: dst), \
                 mock.patch("updater.pyi_archive_intact", lambda p: intact), \
                 mock.patch("shutil.copy2", _locked):
                got = app_mod._ensure_installed_copy()
            return os.path.basename(got)

    def test_locked_intact_install_is_kept(self):
        self.assertEqual(self._copy(intact=True), "installed.exe")

    def test_broken_install_falls_back_to_current(self):
        self.assertEqual(self._copy(intact=False), "download.exe")


class InstalledConfigTests(unittest.TestCase):
    def _read(self, content):
        with tempfile.TemporaryDirectory() as d:
            if content is not None:
                with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
                    f.write(content)
            with mock.patch.object(app_mod, "_app_data_dir", lambda: d):
                return app_mod._installed_start_with_windows()

    def test_defaults_on(self):
        self.assertTrue(self._read(None))
        self.assertTrue(self._read("{}"))
        self.assertTrue(self._read("not json"))

    def test_reads_off(self):
        self.assertFalse(self._read(json.dumps({"start_with_windows": False})))

    def test_legacy_auto_start_false_does_not_turn_it_off(self):
        # Every existing config carries "auto_start": false; it must not gate.
        self.assertTrue(self._read(json.dumps({"auto_start": False})))


class SyncStartupTests(unittest.TestCase):
    def test_on_registers_off_removes(self):
        calls = []
        with mock.patch.object(app_mod, "_ensure_startup_task",
                               lambda: calls.append("ensure")), \
             mock.patch.object(app_mod, "_remove_startup_task",
                               lambda: calls.append("remove")), \
             mock.patch.object(app_mod, "_repair_desktop_shortcut",
                               lambda t: None), \
             mock.patch.object(app_mod, "_startup_target", lambda: "x"):
            app_mod._sync_startup_task(True)
            app_mod._sync_startup_task(False)
        self.assertEqual(calls, ["ensure", "remove"])


class ConfigTests(unittest.TestCase):
    def test_default_on_and_legacy_key_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"auto_start": False}, f)
            cfg = Config.load(p)
        self.assertTrue(cfg.start_with_windows)


class SourceOrderTests(unittest.TestCase):
    """--install must run before anything that can hand off, take the mutex
    or show UI."""

    def test_install_runs_before_handoff_and_mutex(self):
        src = open(app_mod.__file__, encoding="utf-8").read()
        main = src[src.index("def _main() -> None:"):]
        i = main.index("_install_requested()")
        self.assertLess(i, main.index("_handoff_to_canonical_if_newer()"))
        self.assertLess(i, main.index("_ensure_single_instance()"))
        self.assertLess(i, main.index("WhisperFlowApp("))

    def test_startup_task_follows_the_setting(self):
        src = open(app_mod.__file__, encoding="utf-8").read()
        main = src[src.index("def _main() -> None:"):]
        self.assertNotIn("target=_ensure_startup_task", main)
        self.assertIn("start_with_windows", main)

    def test_settings_has_the_toggle(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(here, "app_window.py"), encoding="utf-8").read()
        self.assertIn('_toggle_card("start_with_windows"', src)


if __name__ == "__main__":
    unittest.main()
