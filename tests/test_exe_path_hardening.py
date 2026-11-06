"""Hardening: icons load only from local paths; telemetry sends a file name only."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_icons


class LocalExePathTests(unittest.TestCase):
    def test_network_paths_refused(self):
        for p in (r"\\server\share\app.exe", r"\\?\UNC\server\share\app.exe",
                  "//server/share/app.exe", r"\\localhost\c$\app.exe"):
            self.assertFalse(app_icons.is_local_exe_path(p), p)

    def test_relative_and_empty_refused(self):
        for p in ("", None, "app.exe", r"..\app.exe", "C:app.exe"):
            self.assertFalse(app_icons.is_local_exe_path(p), repr(p))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_local_drive_path_allowed(self):
        self.assertTrue(app_icons.is_local_exe_path(r"C:\Windows\notepad.exe"))

    def test_mapped_network_drive_refused(self):
        fake = mock.Mock()
        fake.GetDriveTypeW.return_value = 4
        with mock.patch.object(app_icons.ctypes, "windll", mock.Mock(kernel32=fake), create=True):
            self.assertFalse(app_icons.is_local_exe_path(r"Z:\tools\app.exe"))

    def test_unc_path_is_never_touched(self):
        with mock.patch.object(app_icons, "_extract_exe_icon") as extract, \
                mock.patch.object(app_icons.os, "stat") as stat:
            self.assertIsNone(app_icons.get_app_icon(r"\\server\share\app.exe", "#000000"))
            self.assertIsNone(app_icons._get_raw_exe_icon(r"\\server\share\app.exe"))
        extract.assert_not_called()
        stat.assert_not_called()

    def test_extraction_refuses_unc_directly(self):
        with mock.patch.object(app_icons, "_extract_via_private") as private:
            self.assertIsNone(app_icons._extract_exe_icon(r"\\server\share\app.exe"))
        private.assert_not_called()


class TelemetryBasenameTests(unittest.TestCase):
    def test_basename_only(self):
        import app as app_mod
        self.assertEqual(app_mod._exe_basename(r"C:\Users\someone\proj\app.exe"), "app.exe")
        self.assertEqual(app_mod._exe_basename("C:/Users/someone/app.exe"), "app.exe")
        self.assertEqual(app_mod._exe_basename(r"\\server\share\app.exe"), "app.exe")
        self.assertEqual(app_mod._exe_basename(""), "")
        self.assertEqual(app_mod._exe_basename(None), "")

    def test_error_event_uses_it(self):
        import app as app_mod
        fake = mock.Mock()
        holder = mock.Mock(db=fake, _recording_app={
            "app_name": "X", "app_exe": r"C:\Users\someone\proj\app.exe"})
        app_mod.WhisperFlowApp._log_error_event(holder, "inject_failed", {})
        self.assertEqual(fake.log_error_event.call_args.kwargs["app_exe"], "app.exe")


if __name__ == "__main__":
    unittest.main()
