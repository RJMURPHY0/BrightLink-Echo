"""Guards for Windows application registration and the uninstaller.

Two things must never regress here:
  1. Auto-update keeps working: every shortcut and registry value points at
     the CANONICAL exe path the updater swaps in place, never at the volatile
     copy the user happened to launch (Downloads, a USB stick).
  2. The deferred uninstall cleanup runs `Remove-Item -Recurse -Force`, so the
     only paths that may reach it are our own two folders directly under
     %LOCALAPPDATA% / %APPDATA%.
"""

import inspect
import os
import shutil
import sys
import time
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_install
import brand


EXE = r"C:\Users\jo\AppData\Local\FTC Whisper\FTC Whisper.exe"


class ShortcutTests(unittest.TestCase):
    def test_start_menu_link_is_recreated_when_missing(self):
        state = {"exe": EXE, "desktop_shortcut": True}
        needed = app_install.shortcuts_needed(
            state, EXE, "start.lnk", "desk.lnk", exists=lambda p: False
        )
        self.assertIn("start.lnk", needed)

    def test_start_menu_link_is_retargeted_when_exe_path_changes(self):
        state = {"exe": r"C:\Downloads\FTC-Whisper.exe", "desktop_shortcut": True}
        needed = app_install.shortcuts_needed(
            state, EXE, "start.lnk", "desk.lnk", exists=lambda p: True
        )
        self.assertEqual(["start.lnk"], needed)

    def test_desktop_shortcut_is_never_recreated_once_made(self):
        # Putting back a shortcut the user deleted is adware behaviour.
        state = {"exe": EXE, "desktop_shortcut": True}
        needed = app_install.shortcuts_needed(
            state, EXE, "start.lnk", "desk.lnk", exists=lambda p: p == "start.lnk"
        )
        self.assertNotIn("desk.lnk", needed)

    def test_first_install_creates_both(self):
        needed = app_install.shortcuts_needed(
            {}, EXE, "start.lnk", "desk.lnk", exists=lambda p: False
        )
        self.assertEqual(["start.lnk", "desk.lnk"], needed)

    def test_steady_state_writes_nothing(self):
        state = {"exe": EXE, "desktop_shortcut": True}
        needed = app_install.shortcuts_needed(
            state, EXE, "start.lnk", "desk.lnk", exists=lambda p: True
        )
        self.assertEqual([], needed)

    def test_shortcut_script_targets_the_canonical_exe(self):
        script = app_install.shortcut_script(["a.lnk", "b.lnk"], EXE)
        self.assertIn(EXE, script)
        self.assertIn("$l.TargetPath = $t", script)
        # Icon comes from the exe itself, so it survives any loose .ico going
        # missing and matches the taskbar pin. Built with single quotes: a
        # double-quoted "$t,0" is stripped to the comma operator by
        # powershell.exe -Command and IShellLink then refuses to save.
        self.assertIn("$l.IconLocation = $t + ',0'", script)
        self.assertNotIn('"', script)
        self.assertIn("a.lnk", script)
        self.assertIn("b.lnk", script)

    def test_shortcut_script_escapes_quotes_in_paths(self):
        script = app_install.shortcut_script([r"C:\o'brien\x.lnk"], EXE)
        self.assertIn("o''brien", script)


class _FakeFolder:
    """A folder that compares names the way Windows does (ignoring case)."""

    def __init__(self, *names):
        self.files = list(names)
        self.log = []

    def listdir(self, folder):
        return list(self.files)

    def _index(self, path):
        name = os.path.basename(path).lower()
        return next(i for i, f in enumerate(self.files) if f.lower() == name)

    def replace(self, src, dst):
        self.files[self._index(src)] = os.path.basename(dst)
        self.log.append(("replace", os.path.basename(src), os.path.basename(dst)))

    def remove(self, path):
        del self.files[self._index(path)]
        self.log.append(("remove", os.path.basename(path)))

    def run(self, want, old_names):
        return app_install.rename_shortcuts(
            [os.path.join(r"C:\folder", want)], old_names,
            listdir=self.listdir, replace=self.replace, remove=self.remove,
        )


class ShortcutRenameTests(unittest.TestCase):
    """A product rename carries the user's shortcuts over; it never creates one
    and never deletes the current one."""

    def test_old_shortcut_is_renamed_in_place(self):
        fs = _FakeFolder("FTC Whisper.lnk", "Other App.lnk")
        fs.run("BrightLink Echo.lnk", ["FTC Whisper"])
        self.assertEqual(["BrightLink Echo.lnk", "Other App.lnk"], fs.files)

    def test_a_deleted_shortcut_stays_deleted(self):
        fs = _FakeFolder("Other App.lnk")
        fs.run("BrightLink Echo.lnk", ["FTC Whisper"])
        self.assertEqual(["Other App.lnk"], fs.files)
        self.assertEqual([], fs.log)

    def test_duplicate_old_name_is_removed_when_both_exist(self):
        fs = _FakeFolder("BrightLink Echo.lnk", "FTC Whisper.lnk")
        fs.run("BrightLink Echo.lnk", ["FTC Whisper"])
        self.assertEqual(["BrightLink Echo.lnk"], fs.files)

    def test_case_only_rename_fixes_the_case_and_deletes_nothing(self):
        fs = _FakeFolder("Brightlink Echo.lnk")
        fs.run("BrightLink Echo.lnk", ["Brightlink Echo", "FTC Whisper"])
        self.assertEqual(["BrightLink Echo.lnk"], fs.files)
        self.assertNotIn("remove", [step[0] for step in fs.log])

    def test_steady_state_does_nothing(self):
        fs = _FakeFolder("BrightLink Echo.lnk")
        fs.run("BrightLink Echo.lnk", ["FTC Whisper"])
        self.assertEqual([], fs.log)

    def test_unreadable_folder_is_skipped(self):
        def boom(folder):
            raise OSError("no such folder")

        self.assertEqual([], app_install.rename_shortcuts(
            [r"C:\gone\BrightLink Echo.lnk"], ["FTC Whisper"], listdir=boom))

    def test_real_files_on_this_filesystem(self):
        # Proves os.replace does what the fake assumes, including a case-only
        # rename, which is a no-op on some filesystems if done carelessly.
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "FTC Whisper.lnk"), "w").close()
            app_install.rename_shortcuts([os.path.join(d, "Brightlink Echo.lnk")], ["FTC Whisper"])
            self.assertEqual(["Brightlink Echo.lnk"], os.listdir(d))
            app_install.rename_shortcuts([os.path.join(d, "BrightLink Echo.lnk")], ["Brightlink Echo"])
            self.assertEqual(["BrightLink Echo.lnk"], os.listdir(d))

    def test_previous_names_never_include_the_current_one(self):
        self.assertEqual(list(brand.LEGACY_PRODUCT_NAMES),
                         app_install.previous_names({}))
        names = app_install.previous_names({"shortcut_name": "Old Name"})
        self.assertEqual("Old Name", names[0])
        self.assertNotIn(brand.PRODUCT_NAME, app_install.previous_names(
            {"shortcut_name": brand.PRODUCT_NAME}))

    def test_register_renames_before_deciding_what_to_write(self):
        src = inspect.getsource(app_install.register)
        self.assertLess(src.index("rename_shortcuts("), src.index("shortcuts_needed("))
        self.assertIn('new_state["shortcut_name"] = brand.PRODUCT_NAME', src)

    def test_registry_and_legacy_clean_up_come_before_powershell(self):
        # The shortcut steps start PowerShell, which a busy or antivirus-scanned
        # machine can hold for minutes; the legacy Installed apps entry and
        # logon task must already be gone by then (v1.8.5 CI, 2026-10-07).
        calls = []
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, brand.CANONICAL_EXE_NAME)
            rec = lambda name, ret=None: (lambda *a, **k: (calls.append(name), ret)[1])  # noqa: E731
            with mock.patch.object(app_install.sys, "platform", "win32"), \
                    mock.patch.object(app_install, "_registered_entry", return_value={}), \
                    mock.patch.object(app_install, "_write_uninstall_entry", rec("entry")), \
                    mock.patch.object(app_install, "_write_app_paths", rec("app_paths")), \
                    mock.patch.object(app_install, "legacy_entry_present", return_value=True), \
                    mock.patch.object(app_install, "remove_legacy_registrations", rec("legacy", [])), \
                    mock.patch.object(app_install, "start_menu_link", return_value=os.path.join(d, "s.lnk")), \
                    mock.patch.object(app_install, "desktop_link", return_value=os.path.join(d, "d.lnk")), \
                    mock.patch.object(app_install, "_write_shortcuts", rec("shortcuts", True)), \
                    mock.patch.object(app_install, "retarget_legacy_links", rec("retarget", [])), \
                    mock.patch.object(app_install, "_note"):
                app_install.register(exe, "1.8.5")
            self.assertEqual(["entry", "app_paths", "legacy", "shortcuts", "retarget"], calls)
            # Done once per exe: the next launch skips the legacy steps.
            self.assertEqual(exe, app_install.load_state(d).get("legacy_cleared_for"))


class UninstallEntryTests(unittest.TestCase):
    def _values(self):
        return dict(
            (name, value)
            for name, _dword, value in app_install.uninstall_values(
                EXE, "1.6.46", os.path.dirname(EXE), 700_000, "20260805"
            )
        )

    def test_entry_has_what_installed_apps_shows(self):
        v = self._values()
        self.assertEqual(brand.PRODUCT_NAME, v["DisplayName"])
        self.assertEqual("1.6.46", v["DisplayVersion"])
        self.assertEqual(brand.COMPANY_NAME, v["Publisher"])
        self.assertEqual(f"{EXE},0", v["DisplayIcon"])
        self.assertEqual(700_000, v["EstimatedSize"])

    def test_entry_is_rewritten_when_the_name_or_publisher_changes(self):
        # Checking only the version would leave a renamed product listed under
        # its old name until a later release bumped the version again.
        current = {"DisplayVersion": "1.6.81", "DisplayName": brand.PRODUCT_NAME,
                   "Publisher": brand.COMPANY_NAME}
        self.assertTrue(app_install.entry_is_current(current, "1.6.81"))
        self.assertFalse(app_install.entry_is_current(current, "1.6.82"))
        self.assertFalse(app_install.entry_is_current(
            dict(current, DisplayName="FTC Whisper"), "1.6.81"))
        self.assertFalse(app_install.entry_is_current(
            dict(current, Publisher="Someone Else"), "1.6.81"))
        self.assertFalse(app_install.entry_is_current({}, "1.6.81"))

    def test_an_entry_that_uninstalls_through_another_exe_is_rewritten(self):
        # The onefile bridge registers the entry from the legacy folder; the
        # migration then moves the exe at the same version. Same version, name
        # and publisher must not keep the stale uninstall path.
        new = r"C:\x\BrightLink Echo\BrightLink Echo.exe"
        old = r"C:\x\FTC Whisper\FTC Whisper.exe"
        current = {"DisplayVersion": "1.8.5", "DisplayName": brand.PRODUCT_NAME,
                   "Publisher": brand.COMPANY_NAME,
                   "UninstallString": f'"{old}" --uninstall'}
        self.assertFalse(app_install.entry_is_current(current, "1.8.5", new))
        current["UninstallString"] = f'"{new}" --uninstall'
        self.assertTrue(app_install.entry_is_current(current, "1.8.5", new))

    def test_uninstall_string_is_quoted_and_runnable(self):
        v = self._values()
        # The install path contains a space; an unquoted command runs
        # "C:\Users\jo\AppData\Local\FTC" with "Whisper\..." as an argument.
        self.assertEqual(f'"{EXE}" --uninstall', v["UninstallString"])
        self.assertEqual(f'"{EXE}" --uninstall /S', v["QuietUninstallString"])

    def test_version_fields_parse(self):
        v = self._values()
        self.assertEqual(1, v["VersionMajor"])
        self.assertEqual(6, v["VersionMinor"])

    def test_no_modify_or_repair_buttons(self):
        v = self._values()
        self.assertEqual(1, v["NoModify"])
        self.assertEqual(1, v["NoRepair"])


class DeleteGuardTests(unittest.TestCase):
    def setUp(self):
        self.local = os.environ.get("LOCALAPPDATA") or r"C:\Users\jo\AppData\Local"
        self.roaming = os.environ.get("APPDATA") or r"C:\Users\jo\AppData\Roaming"

    def test_accepts_our_own_folders(self):
        self.assertTrue(
            app_install.safe_to_delete(os.path.join(self.local, "FTC Whisper"))
        )
        self.assertTrue(
            app_install.safe_to_delete(os.path.join(self.roaming, "FTC Whisper"))
        )

    def test_rejects_everything_else(self):
        for path in (
            "",
            self.local,
            os.path.dirname(self.local),
            r"C:\Windows",
            r"C:\FTC Whisper",
            os.path.join(self.local, "FTC Whisper", "models"),
            os.path.join(self.local, "Microsoft"),
        ):
            self.assertFalse(
                app_install.safe_to_delete(path), f"must not delete {path!r}"
            )

    def test_guard_follows_the_frozen_folder_not_the_display_name(self):
        # The data stays in "FTC Whisper" whatever the product is called. A
        # guard keyed to the display name would refuse the real folder and
        # leave 660 MB behind, or worse, accept a folder that is not ours.
        with mock.patch.object(brand, "PRODUCT_NAME", "Some Other Name"):
            self.assertTrue(app_install.safe_to_delete(os.path.join(self.local, "FTC Whisper")))
            self.assertFalse(app_install.safe_to_delete(os.path.join(self.local, "Some Other Name")))

    def test_uninstall_stops_every_name_a_running_copy_can_have(self):
        images = [n.lower() for n in app_install.image_names()]
        for name in (brand.CANONICAL_EXE_NAME, brand.UPDATE_ASSET, brand.DOWNLOAD_ASSET,
                     f"{brand.PRODUCT_NAME}.exe"):
            self.assertIn(name.lower(), images)
        self.assertEqual(len(set(images)), len(images))

    def test_cleanup_script_waits_for_the_process_and_self_deletes(self):
        script = app_install.cleanup_script(
            4321, [os.path.join(self.local, "FTC Whisper")], "s.ps1"
        )
        self.assertIn("Get-Process -Id 4321", script)
        self.assertIn("Remove-Item -LiteralPath $d -Recurse -Force", script)
        self.assertIn("s.ps1", script)

    def test_cleanup_script_stops_a_relaunched_copy_and_logs(self):
        d = os.path.join(self.local, "BrightLink Echo")
        script = app_install.cleanup_script(
            4321, [d], "s.ps1", "u.log",
            keys=["Software\\Classes\\ftcwhisper"], tasks=["BrightLink Echo"],
            run_values=["BrightLink Echo"], files=["C:\\x\\a.lnk"],
        )
        # anything running from inside the folder is stopped before each delete
        self.assertIn("Win32_Process", script)
        self.assertIn("Stop-Process", script)
        self.assertIn("AddSeconds(90)", script)
        # a failure is written down, never silent
        self.assertIn("COULD NOT REMOVE", script)
        self.assertIn("u.log", script)
        # a launch during the uninstall re-registers; the entries go again after
        self.assertIn("schtasks /delete /tn $t /f", script)
        self.assertIn("Remove-ItemProperty", script)
        self.assertIn("ftcwhisper", script)
        self.assertIn("a.lnk", script)
        self.assertLess(script.index("Remove-Item -LiteralPath $d"),
                        script.index("schtasks /delete"))

    def test_spawn_cleanup_lists_every_name_both_generations(self):
        d = tempfile.mkdtemp()
        written = {}

        def fake_popen(cmd, **kw):
            with open(cmd[-1], encoding="utf-8") as f:
                written["script"] = f.read()
            return mock.Mock()

        try:
            with mock.patch.object(app_install, "safe_to_delete", return_value=True), \
                    mock.patch.object(app_install.subprocess, "Popen", fake_popen):
                app_install._spawn_cleanup([d])
        finally:
            shutil.rmtree(d, ignore_errors=True)
        script = written["script"]
        for name in (brand.TASK_NAME, brand.LEGACY_TASK_NAME, brand.URL_SCHEME,
                     brand.LEGACY_URL_SCHEME, brand.UNINSTALL_KEY_NAME,
                     brand.LEGACY_UNINSTALL_KEY_NAME):
            self.assertIn(name, script)

    def test_spawn_never_uses_detached_process(self):
        # DETACHED_PROCESS combined with CREATE_NO_WINDOW makes powershell.exe
        # exit 0 without running -File. That exact pair silently broke every
        # in-app update up to v1.6.3; the uninstaller must not repeat it.
        code = "\n".join(
            line for line in inspect.getsource(app_install._spawn_cleanup).splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertNotIn("DETACHED_PROCESS", code)
        self.assertIn("CREATE_NO_WINDOW", inspect.getsource(app_install))


class UninstallMarkerTests(unittest.TestCase):
    """A relaunch while the cleanup is removing the folder must not bring the
    app back (it re-registered everything and ran with the model deleted)."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.folder = os.path.join(self.root, "BrightLink Echo")
        os.makedirs(self.folder)
        self.exe = os.path.join(self.folder, "BrightLink Echo.exe")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_no_marker_never_blocks(self):
        self.assertFalse(app_install.uninstall_pending(self.exe, dirs=[self.folder]))

    def test_a_fresh_marker_blocks_a_copy_in_that_folder(self):
        app_install.write_uninstall_marker([self.folder])
        self.assertTrue(app_install.uninstall_pending(self.exe, dirs=[self.folder]))
        nested = os.path.join(self.folder, "app-1.8.5", "BrightLink Echo.exe")
        self.assertTrue(app_install.uninstall_pending(nested, dirs=[self.folder]))

    def test_a_stale_marker_stops_counting(self):
        app_install.write_uninstall_marker([self.folder])
        later = time.time() + app_install.UNINSTALL_MARKER_TTL + 5
        self.assertFalse(app_install.uninstall_pending(self.exe, now=later, dirs=[self.folder]))

    def test_a_copy_elsewhere_is_never_blocked(self):
        app_install.write_uninstall_marker([self.folder])
        other = os.path.join(self.root, "Downloads", "BrightLink-Echo.exe")
        self.assertFalse(app_install.uninstall_pending(other, dirs=[self.folder]))
        # a sibling whose name merely starts the same
        sibling = os.path.join(self.root, "BrightLink Echo 2", "BrightLink Echo.exe")
        self.assertFalse(app_install.uninstall_pending(sibling, dirs=[self.folder]))

    def test_marker_is_written_only_into_folders_that_exist(self):
        missing = os.path.join(self.root, "nope")
        written = app_install.write_uninstall_marker([self.folder, missing])
        self.assertEqual(written, [os.path.join(self.folder, app_install.UNINSTALL_MARKER)])
        self.assertFalse(os.path.exists(missing))

    def test_run_uninstall_writes_the_marker_before_it_kills_anything(self):
        order = []
        with mock.patch.object(app_install, "write_uninstall_marker",
                               lambda *a, **k: order.append("marker")), \
                mock.patch.object(app_install, "_kill_other_instances",
                                  lambda: order.append("kill")), \
                mock.patch.object(app_install, "_remove_launchers", lambda: None), \
                mock.patch.object(app_install, "_remove_registry_entries", lambda: None), \
                mock.patch.object(app_install, "_remove_shortcuts", lambda: None):
            self.assertEqual(app_install.run_uninstall(silent=True), 0)
        self.assertEqual(order, ["marker", "kill"])

    def test_setup_deletes_the_marker_on_a_reinstall(self):
        iss = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "installer", "echo.iss")
        with open(iss, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(app_install.UNINSTALL_MARKER, text)


class CleanupInsideAJobTests(unittest.TestCase):
    """A job that forbids breakaway (a CI runner, some launchers) refuses the
    whole CreateProcess. The uninstall then silently left the install folder
    behind (CI run 36683407903); it must start the cleanup inside the job."""

    def test_a_refused_breakaway_still_starts_the_cleanup(self):
        import subprocess
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        if not breakaway:
            self.skipTest("Windows only")
        calls = []

        def fake_popen(cmd, creationflags=0, **kw):
            calls.append(creationflags)
            if creationflags & breakaway:
                raise PermissionError(5, "Access is denied")
            return mock.Mock()

        d = tempfile.mkdtemp()
        try:
            with mock.patch.object(app_install, "safe_to_delete", return_value=True), \
                    mock.patch.object(app_install.subprocess, "Popen", side_effect=fake_popen):
                app_install._spawn_cleanup([d])
        finally:
            os.rmdir(d)
        self.assertEqual(2, len(calls))
        self.assertTrue(calls[0] & breakaway)
        self.assertFalse(calls[1] & breakaway)


class NotificationIdentityTests(unittest.TestCase):
    """A toast from an unpackaged app is titled with its AppUserModelID unless
    that id has a DisplayName registered. Without it v1.6.89 showed
    "FTC.Whisper" over the update notice."""

    def test_the_toast_name_is_the_product_name(self):
        values = dict(app_install.notification_identity_values(r"C:\x\icon.png"))
        self.assertEqual(brand.PRODUCT_NAME, values["DisplayName"])
        self.assertEqual(r"C:\x\icon.png", values["IconUri"])

    def test_the_key_is_keyed_by_the_frozen_id(self):
        self.assertEqual(
            "Software\\Classes\\AppUserModelId\\" + brand.APP_USER_MODEL_ID,
            app_install.NOTIFICATION_ID_KEY)

    def test_the_icon_lives_in_the_install_folder(self):
        self.assertEqual(
            os.path.dirname(app_install.notification_icon_path()),
            app_install._install_dir())

    def test_uninstall_removes_the_key(self):
        src = inspect.getsource(app_install._registry_key_paths)
        self.assertIn("NOTIFICATION_ID_KEY", src)

    def test_registered_before_the_window_exists(self):
        import app_window
        src = inspect.getsource(app_window.AppWindow.run)
        self.assertIn("register_notification_identity()", src)
        self.assertLess(src.index("register_notification_identity()"),
                        src.index("tk.Tk()"))
        self.assertNotIn('"FTC.Whisper"', src)


class AppWiringTests(unittest.TestCase):
    def test_app_registers_against_the_stable_exe_path(self):
        import app

        src = inspect.getsource(app._register_application)
        # _startup_target() is the canonical %LOCALAPPDATA% copy the updater
        # maintains. Registering sys.executable would pin every shortcut to
        # whatever folder the user first ran the download from.
        self.assertIn("_startup_target()", src)
        self.assertNotIn("sys.executable", src)
        self.assertIn('getattr(sys, "frozen", False)', src)

    def test_uninstall_is_handled_before_the_single_instance_check(self):
        import app

        src = inspect.getsource(app._main)
        self.assertLess(
            src.index("_uninstall_requested()"),
            src.index("_ensure_single_instance()"),
            "the resident instance would kill the uninstaller",
        )



class LegacyRegistrationTests(unittest.TestCase):
    """v1.8.5 moved the on-disk names: what older versions registered under
    the legacy ones is removed once, and every link to the legacy exe is
    pointed at the current one."""

    def test_links_to_the_legacy_exe_are_retargeted_and_nothing_else(self):
        ps = app_install.retarget_script(
            [r"C:\Users\a\Desktop", r"C:\Users\a\Pinned\TaskBar"],
            [r"C:\Users\a\AppData\Local\Old Name\Old Name.exe"],
            r"C:\Users\a\AppData\Local\New Name\New Name.exe")
        self.assertIn("$old -contains $l.TargetPath", ps)
        self.assertIn(r"'C:\Users\a\Pinned\TaskBar'", ps)
        self.assertIn(r"$l.TargetPath = 'C:\Users\a\AppData\Local\New Name\New Name.exe'", ps)
        # It never creates, renames or deletes a link.
        for verb in ("Remove-Item", "Rename-Item", "Move-Item", "New-Item"):
            self.assertNotIn(verb, ps)

    def test_pins_are_among_the_folders_checked(self):
        dirs = [d.lower() for d in app_install.pinned_link_dirs()]
        self.assertTrue(any(d.endswith("user pinned\\taskbar") for d in dirs), dirs)
        self.assertTrue(any(d.endswith("user pinned\\startmenu") for d in dirs), dirs)

    def test_the_legacy_keys_are_not_the_current_ones(self):
        self.assertNotEqual(app_install.LEGACY_UNINSTALL_KEY.lower(), app_install.UNINSTALL_KEY.lower())
        self.assertNotEqual(app_install.LEGACY_APP_PATHS_KEY.lower(), app_install.APP_PATHS_KEY.lower())

    def test_the_clean_up_is_latched_per_exe(self):
        src = inspect.getsource(app_install.register)
        self.assertIn('state.get("legacy_cleared_for") != exe or legacy_entry_present()', src)
        self.assertIn("legacy_cleared_for=exe", src)

    def test_the_uninstaller_can_delete_either_folder(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\L", "APPDATA": r"C:\R"}):
            import brand
            for base in (r"C:\L", r"C:\R"):
                for name in (brand.DATA_DIR_NAME, brand.LEGACY_DATA_DIR_NAME):
                    self.assertTrue(app_install.safe_to_delete(os.path.join(base, name)))
            self.assertFalse(app_install.safe_to_delete(r"C:\L\Something Else"))


if __name__ == "__main__":
    unittest.main()
