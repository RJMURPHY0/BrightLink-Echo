"""Hardening: pasted dictation stays out of clipboard history and cloud sync.

A paste write sets the three documented Windows formats unless Copy to
Clipboard is on. A restore of the user's own data is never marked.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import injector as I


class ClipboardPrivacyFlagTests(unittest.TestCase):
    def test_format_names_and_values(self):
        got = dict(I._PRIVATE_CLIPBOARD_FORMATS)
        self.assertEqual(got["ExcludeClipboardContentFromMonitorProcessing"], 1)
        self.assertEqual(got["CanIncludeInClipboardHistory"], 0)
        self.assertEqual(got["CanUploadToCloudClipboard"], 0)

    def test_paste_write_is_marked_when_copy_setting_off(self):
        self.assertTrue(I._wants_private_clipboard(True, False))

    def test_copy_to_clipboard_on_is_not_marked(self):
        self.assertFalse(I._wants_private_clipboard(True, True))

    def test_restore_write_is_not_marked(self):
        self.assertFalse(I._wants_private_clipboard(False, False))

    def test_mark_sets_every_format(self):
        seen = []
        real = I._set_dword_format
        I._set_dword_format = lambda name, value: seen.append((name, value)) or True
        try:
            I._mark_clipboard_private()
        finally:
            I._set_dword_format = real
        self.assertEqual(tuple(seen), I._PRIVATE_CLIPBOARD_FORMATS)

    def test_clipboard_set_uses_the_gate(self):
        src = open(os.path.join(os.path.dirname(I.__file__), "injector.py"),
                   encoding="utf-8").read()
        self.assertIn("_wants_private_clipboard(bump, Injector.keep_clipboard)", src)

    def test_a_failing_flag_write_never_raises(self):
        real = I._u32.RegisterClipboardFormatW
        try:
            I._u32.RegisterClipboardFormatW = lambda _n: (_ for _ in ()).throw(OSError("x"))
            self.assertFalse(I._set_dword_format("CanIncludeInClipboardHistory", 0))
        finally:
            I._u32.RegisterClipboardFormatW = real


if __name__ == "__main__":
    unittest.main()
