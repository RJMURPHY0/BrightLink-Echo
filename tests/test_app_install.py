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
import sys
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
        src = inspect.getsource(app_install._remove_registry_entries)
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


if __name__ == "__main__":
    unittest.main()
