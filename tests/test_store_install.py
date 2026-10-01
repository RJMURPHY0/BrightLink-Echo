"""Microsoft Store install mode and the Start with Windows setting.

The Store runs an EXE installer silently (policy 10.2.9): `--install /S` must
install and exit with no window, and it must run BEFORE the version handoff
and the single-instance mutex, because the app may already be open. Start
with Windows is the consent Store policy 10.2.8 asks for: the HKCU Run entry
is enabled only when it is on, and Task Manager's Startup apps lists it.
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
    def _run(self, intact: bool, start: bool = True, task_manager=None, argv=("x",)):
        calls = []

        def task_manager_state():
            calls.append("task-manager")
            return task_manager

        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "argv", list(argv)), \
             mock.patch.object(app_mod, "_apply_installer_choices", lambda: None), \
             mock.patch.object(app_mod, "_task_manager_startup_state", task_manager_state), \
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
             mock.patch.object(app_mod, "_sync_startup",
                               lambda on: calls.append(("startup", on))), \
             mock.patch.object(app_mod, "_log_startup_error", lambda e: None):
            code = app_mod._run_silent_install()
        return code, calls

    def test_installs_and_registers(self):
        code, calls = self._run(intact=True)
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["copy", "task-manager", "register", "url", ("startup", True)])

    def test_respects_start_with_windows_off(self):
        code, calls = self._run(intact=True, start=False)
        self.assertEqual(code, 0)
        self.assertIn(("startup", False), calls)

    def test_a_task_manager_disable_holds_without_a_tick(self):
        # Read before _register_application, which deletes the legacy entry.
        code, calls = self._run(intact=True, start=True, task_manager=False)
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["copy", "task-manager", "register", "url", ("startup", False)])

    def test_the_installer_tick_is_a_choice_made_now(self):
        code, calls = self._run(intact=True, start=True, task_manager=False,
                                argv=("x", "--install", "/S", "--start-with-windows=1"))
        self.assertEqual(code, 0)
        self.assertNotIn("task-manager", calls)
        self.assertIn(("startup", True), calls)

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


class _FakeWinreg:
    """Just enough of winreg for the Start with Windows code, so tests never
    touch the real registry."""
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ, REG_BINARY = 1, 3
    KEY_SET_VALUE = KEY_READ = 0

    def __init__(self):
        self.keys = {}

    class _Key:
        def __init__(self, values):
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(self, root, path, *a):
        if path not in self.keys:
            raise FileNotFoundError(path)
        return self._Key(self.keys[path])

    def CreateKey(self, root, path):
        return self._Key(self.keys.setdefault(path, {}))

    def QueryValueEx(self, k, name):
        if name not in k.values:
            raise FileNotFoundError(name)
        return k.values[name], 0

    def SetValueEx(self, k, name, _reserved, _type, data):
        k.values[name] = data

    def DeleteValue(self, k, name):
        if name not in k.values:
            raise FileNotFoundError(name)
        del k.values[name]


class SyncStartupTests(unittest.TestCase):
    """Start with Windows is the HKCU Run entry plus Task Manager's on/off
    record, so the app shows (and can be switched) in Startup apps."""

    def setUp(self):
        import app_install
        self.reg = _FakeWinreg()
        self.task = []
        self.run_key = app_install.RUN_KEY
        self.approved_key = app_install.STARTUP_APPROVED_KEY
        self.name = app_mod.brand.RUN_VALUE_NAME
        for p in (mock.patch.dict(sys.modules, {"winreg": self.reg}),
                  mock.patch.object(app_mod, "_startup_target", lambda: "C:/x/Echo.exe"),
                  mock.patch.object(app_mod, "_reconcile_legacy_launchers", lambda: None),
                  mock.patch.object(app_mod, "_ensure_logon_task",
                                    lambda: self.task.append("ensure")),
                  mock.patch.object(app_mod, "_remove_logon_task",
                                    lambda: self.task.append("remove")),
                  mock.patch.object(app_mod, "_repair_desktop_shortcut", lambda t: None),
                  mock.patch.object(app_mod.sys, "frozen", True, create=True)):
            p.start()
            self.addCleanup(p.stop)

    def approval(self):
        return self.reg.keys.get(self.approved_key, {}).get(self.name)

    def test_on_writes_an_enabled_run_entry(self):
        app_mod._sync_startup(True)
        self.assertEqual(self.reg.keys[self.run_key][self.name], '"C:/x/Echo.exe" --startup')
        self.assertIsNone(self.approval())  # no record: Windows runs it
        self.assertIs(app_mod._startup_registry_state(), True)
        self.assertEqual(self.task, ["ensure"])  # the early launcher

    def test_on_after_off_clears_the_disable(self):
        app_mod._sync_startup(False)
        app_mod._sync_startup(True)
        self.assertEqual(self.approval(), bytes([2]) + bytes(11))
        self.assertIs(app_mod._startup_registry_state(), True)

    def test_off_keeps_the_entry_listed_but_disabled(self):
        app_mod._sync_startup(False)
        self.assertIn(self.name, self.reg.keys[self.run_key])
        self.assertEqual(len(self.approval()), 12)
        self.assertEqual(self.approval()[0], 3)
        self.assertIs(app_mod._startup_registry_state(), False)
        self.assertEqual(self.task, ["remove"])

    def test_unchanged_state_keeps_task_managers_record(self):
        stamped = bytes([3, 0, 0, 0]) + bytes(range(1, 9))
        self.reg.keys[self.run_key] = {self.name: '"old"'}
        self.reg.keys[self.approved_key] = {self.name: stamped}
        app_mod._sync_startup(False)
        self.assertEqual(self.approval(), stamped)
        self.assertEqual(self.reg.keys[self.run_key][self.name], '"C:/x/Echo.exe" --startup')

    def test_no_approval_record_means_enabled(self):
        self.reg.keys[self.run_key] = {self.name: '"x"'}
        self.assertIs(app_mod._startup_registry_state(), True)

    def test_no_entry_yet_applies_the_saved_setting(self):
        cfg = mock.Mock(start_with_windows=False)
        self.assertIs(app_mod._startup_registry_state(), None)
        self.assertFalse(app_mod._startup_setting_at_launch(cfg))
        cfg.save.assert_not_called()

    def test_task_manager_choice_wins_and_settings_follow(self):
        self.reg.keys[self.run_key] = {self.name: '"x"'}
        self.reg.keys[self.approved_key] = {self.name: bytes([3]) + bytes(11)}
        cfg = mock.Mock(start_with_windows=True)
        self.assertFalse(app_mod._startup_setting_at_launch(cfg))
        self.assertFalse(cfg.start_with_windows)
        cfg.save.assert_called_once()

        self.reg.keys[self.approved_key][self.name] = bytes([2]) + bytes(11)
        cfg = mock.Mock(start_with_windows=False)
        self.assertTrue(app_mod._startup_setting_at_launch(cfg))
        self.assertTrue(cfg.start_with_windows)


class LegacyStartupCarryOverTests(unittest.TestCase):
    """v1.8.1 renamed the Run entry. A disable made in Task Manager under the
    legacy name must survive the move, and nothing under that name may stay
    behind once the current one is registered or the app is uninstalled."""

    def setUp(self):
        import app_install
        self.app_install = app_install
        self.reg = _FakeWinreg()
        self.schtasks = []
        self.run_key = app_install.RUN_KEY
        self.approved_key = app_install.STARTUP_APPROVED_KEY
        self.name = app_mod.brand.RUN_VALUE_NAME
        self.legacy = app_mod.brand.LEGACY_RUN_VALUE_NAME
        self.assertNotEqual(self.name, self.legacy)

        def fake_run(cmd, *a, **k):
            self.schtasks.append(list(cmd))
            return mock.Mock(returncode=0, stdout="", stderr="")

        # Never the real registry, never a real scheduled task.
        for p in (mock.patch.dict(sys.modules, {"winreg": self.reg}),
                  mock.patch.object(app_install.subprocess, "run", fake_run)):
            p.start()
            self.addCleanup(p.stop)

    def legacy_entry(self, disabled: bool):
        self.reg.keys.setdefault(self.run_key, {})[self.legacy] = '"C:/old/FTC Whisper.exe"'
        self.reg.keys.setdefault(self.approved_key, {})[self.legacy] = (
            bytes([3 if disabled else 2]) + bytes(11))

    def test_a_legacy_disable_keeps_it_off(self):
        self.legacy_entry(disabled=True)
        self.assertIs(app_mod._startup_registry_state(), None)
        self.assertIs(app_mod._task_manager_startup_state(), False)
        cfg = mock.Mock(start_with_windows=True)
        self.assertFalse(app_mod._startup_setting_at_launch(cfg))
        self.assertFalse(cfg.start_with_windows)
        cfg.save.assert_called_once()

    def test_only_a_disable_carries_over(self):
        self.legacy_entry(disabled=False)
        self.assertIs(app_mod._task_manager_startup_state(), None)
        for saved in (True, False):
            cfg = mock.Mock(start_with_windows=saved)
            self.assertIs(app_mod._startup_setting_at_launch(cfg), saved)
            cfg.save.assert_not_called()

    def test_the_current_entry_wins_once_registered(self):
        self.legacy_entry(disabled=True)
        self.reg.keys[self.run_key][self.name] = '"C:/new/BrightLink Echo.exe" --startup'
        self.assertIs(app_mod._task_manager_startup_state(), True)

    def test_registration_removes_the_legacy_pair_and_task(self):
        self.legacy_entry(disabled=True)
        self.reg.keys[self.run_key][self.name] = '"new" --startup'
        self.reg.keys[self.approved_key][self.name] = bytes([3]) + bytes(11)
        done = self.app_install.remove_legacy_launchers()
        self.assertNotIn(self.legacy, self.reg.keys[self.run_key])
        self.assertNotIn(self.legacy, self.reg.keys[self.approved_key])
        # The current pair is untouched, so the disable now lives there.
        self.assertIn(self.name, self.reg.keys[self.run_key])
        self.assertIs(app_mod._startup_registry_state(), False)
        self.assertIn(["schtasks", "/delete", "/tn", app_mod.brand.LEGACY_TASK_NAME, "/f"],
                      self.schtasks)
        self.assertIn("removed legacy Run value", done)
        self.assertIn("removed legacy Startup apps record", done)

    def test_uninstall_removes_both_pairs_and_both_tasks(self):
        self.legacy_entry(disabled=True)
        self.reg.keys[self.run_key][self.name] = '"new" --startup'
        self.reg.keys[self.approved_key][self.name] = bytes([2]) + bytes(11)
        self.reg.keys[self.run_key]["Other App"] = '"other.exe"'
        self.app_install._remove_launchers()
        self.assertEqual(self.reg.keys[self.run_key], {"Other App": '"other.exe"'})
        self.assertEqual(self.reg.keys[self.approved_key], {})
        deleted = [c[3] for c in self.schtasks if c[:2] == ["schtasks", "/delete"]]
        self.assertIn(app_mod.brand.TASK_NAME, deleted)
        self.assertIn(app_mod.brand.LEGACY_TASK_NAME, deleted)

    def test_nothing_to_remove_is_not_an_error(self):
        self.assertEqual(self.app_install.remove_legacy_launchers(), ["removed legacy logon task"])
        self.app_install._remove_launchers()


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

    def test_startup_entry_follows_the_setting(self):
        src = open(app_mod.__file__, encoding="utf-8").read()
        main = src[src.index("def _main() -> None:"):]
        self.assertIn("args=(_startup_setting_at_launch(config),)", main)

    def test_sign_in_launch_checks_task_manager_before_anything(self):
        src = open(app_mod.__file__, encoding="utf-8").read()
        main = src[src.index("def _main() -> None:"):]
        i = main.index("if _launched_at_sign_in():")
        # Including a disable still recorded under the legacy name.
        self.assertIn("if _task_manager_startup_state() is False:", main[i:i + 200])
        self.assertLess(i, main.index("_handoff_to_canonical_if_newer()"))
        self.assertLess(i, main.index("_ensure_single_instance()"))

    def test_duplicate_sign_in_launch_never_shows_the_window(self):
        src = open(app_mod.__file__, encoding="utf-8").read()
        body = src[src.index("def _ensure_single_instance"):src.index("TASK_NAME = ")]
        self.assertLess(body.index("_launched_at_sign_in()"), body.index("/show"))

    def test_both_launchers_pass_the_startup_flag(self):
        src = open(app_mod.__file__, encoding="utf-8").read()
        task = src[src.index("def _ensure_logon_task"):src.index("def _remove_logon_task")]
        self.assertIn("args = _STARTUP_ARG", task)
        self.assertIn("<Priority>4</Priority>", task)
        with mock.patch.object(app_mod, "_startup_target", lambda: "C:/x/E.exe"), \
             mock.patch.object(app_mod.sys, "frozen", True, create=True):
            self.assertEqual(app_mod._startup_command(), '"C:/x/E.exe" --startup')

    def test_settings_has_the_toggle(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(here, "app_window.py"), encoding="utf-8").read()
        self.assertIn('_toggle_card("start_with_windows"', src)


if __name__ == "__main__":
    unittest.main()
