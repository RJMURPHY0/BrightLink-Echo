"""Paste fast paths must not duplicate text or send it to a different app."""
import ctypes
import unittest
from unittest.mock import Mock, patch

import injector as I


class PasteDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.inj = I.Injector()
        self.u32 = Mock()
        self.u32.GetForegroundWindow.return_value = 123
        self.u32.GetAsyncKeyState.return_value = 0
        self.u32.SendInput.side_effect = lambda n, *_: n
        self.saved = Mock()
        self.patches = [
            patch.object(ctypes.windll, "user32", self.u32),
            patch.object(I, "_u32", self.u32),
            patch.object(self.inj, "_clipboard_set", return_value=(True, self.saved)),
            patch.object(self.inj, "_clipboard_restore"),
            patch.object(I, "foreground_is_elevated_blocked", return_value=False),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_verified_paste_has_no_fixed_wait(self):
        for method in (self.inj._clipboard_paste, self.inj._terminal_paste):
            with patch.object(I.time, "sleep") as sleep:
                self.assertTrue(method("dictation"))
                sleep.assert_not_called()

    def test_terminal_releases_modifiers_before_paste(self):
        with patch.object(I, "_release_modifiers") as release:
            self.u32.SendInput.side_effect = lambda n, *_: (
                self.assertTrue(release.called) or n)
            self.assertTrue(self.inj._terminal_paste("dictation"))

    def test_both_paste_routes_refuse_wrong_foreground_and_restore_clipboard(self):
        self.inj._target_hwnd = 456
        with patch.object(I, "_await_foreground", return_value=123):
            for method in (self.inj._clipboard_paste, self.inj._terminal_paste):
                self.assertFalse(method("dictation"))
                self.assertIn("foreground", self.inj._paste_refusal)
        self.u32.SendInput.assert_not_called()
        self.assertEqual(self.inj._clipboard_restore.call_count, 2)

    def test_partial_paste_never_types_a_duplicate(self):
        for cls, total in (("Chrome_WidgetWin_1", 4), ("Notepad", 4),
                           ("CASCADIA_HOSTING_WINDOW_CLASS", 6)):
            self.u32.SendInput.side_effect = lambda n, *_: n - 1
            with patch.object(I, "_get_fg_class", return_value=cls), \
                    patch.object(self.inj, "_direct_inject") as direct, \
                    patch.object(I, "_log_inject_failure"), \
                    patch.object(I, "_get_fg_exe", return_value="test.exe"), \
                    patch.object(I.time, "sleep") as sleep:
                self.assertFalse(self.inj.inject("dictation", release_mods=False))
                direct.assert_not_called()
                sleep.assert_not_called()
                self.assertTrue(self.inj._partial_direct)
                self.assertEqual(self.u32.SendInput.call_args_list[-2].args[0], total)
                self.assertEqual(self.u32.SendInput.call_args.args[0], 3)

    def test_browser_fallback_refuses_another_foreground(self):
        self.inj._target_hwnd = 456
        self.inj._target_child = 789
        with patch.object(I, "_get_fg_class", return_value="Chrome_WidgetWin_1"), \
                patch.object(I, "_send_unicode_counted") as direct:
            self.assertFalse(self.inj._direct_inject("dictation"))
            direct.assert_not_called()
