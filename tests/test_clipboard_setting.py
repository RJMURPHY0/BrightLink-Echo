"""Copy to Clipboard OFF must actually mean off.

A clipboard-paste injection writes the dictation to the clipboard and schedules
a restore of what was there before. When there was NOTHING to restore (an empty
clipboard, or non-text content we could not back up) the old code simply
returned — so the dictation stayed on the clipboard, which is exactly what the
Copy to Clipboard setting is supposed to opt IN to. With the setting off the
clipboard is emptied instead.

v1.6.93: the backup is a full snapshot (images, copied files, rich text), so a
copied image survives a dictation with the setting off, and with the setting on
nothing is restored at all.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import injector as I


class _NoDelay:
    """Collapse the 1.5s paste-settling sleep so the tests stay instant."""

    def __enter__(self):
        self._real = I.time.sleep
        I.time.sleep = lambda _s: None
        return self

    def __exit__(self, *_a):
        I.time.sleep = self._real


class ClipboardRestoreTests(unittest.TestCase):
    def setUp(self):
        self.cleared = 0
        self.restored = []
        self._real_clear = I.Injector._clipboard_clear
        self._real_set = I.Injector._clipboard_set
        self._keep = I.Injector.keep_clipboard

        def _fake_clear():
            self.cleared += 1
            return True

        def _fake_set(text, bump=True):
            self.restored.append(text)
            return True, ""

        I.Injector._clipboard_clear = staticmethod(_fake_clear)
        I.Injector._clipboard_set = staticmethod(_fake_set)

    def tearDown(self):
        I.Injector._clipboard_clear = self._real_clear
        I.Injector._clipboard_set = self._real_set
        I.Injector.keep_clipboard = self._keep

    @staticmethod
    def _settle():
        # The restore/clear runs on a daemon thread.
        for _ in range(200):
            time.sleep(0.005)
            if I.threading.active_count() <= 1:
                break
        time.sleep(0.05)

    def test_nothing_to_restore_clears_the_clipboard_when_the_setting_is_off(self):
        I.Injector.keep_clipboard = False
        with _NoDelay():
            I.Injector._clipboard_restore("", I._clip_gen)
            self._settle()
        self.assertEqual(1, self.cleared)
        self.assertEqual([], self.restored)

    def test_nothing_to_restore_leaves_the_dictation_when_the_setting_is_on(self):
        I.Injector.keep_clipboard = True
        with _NoDelay():
            I.Injector._clipboard_restore("", I._clip_gen)
            self._settle()
        self.assertEqual(0, self.cleared)

    def test_a_newer_paste_supersedes_the_clear(self):
        # The gen guard must cover the clear exactly as it covers a restore, or
        # we would empty a clipboard the NEXT dictation had just written to.
        I.Injector.keep_clipboard = False
        stale_gen = I._clip_gen - 1
        with _NoDelay():
            I.Injector._clipboard_restore("", stale_gen)
            self._settle()
        self.assertEqual(0, self.cleared)

    def test_real_content_is_still_restored_not_cleared(self):
        I.Injector.keep_clipboard = False
        with _NoDelay():
            I.Injector._clipboard_restore("the user's own copy", I._clip_gen)
            self._settle()
        self.assertEqual(0, self.cleared)
        self.assertEqual(["the user's own copy"], self.restored)

    def _with_fake_writer(self, result):
        written = []
        real = I._clipboard_write_snapshot

        def _fake(snap):
            written.append(snap)
            return result
        I._clipboard_write_snapshot = _fake
        self.addCleanup(setattr, I, "_clipboard_write_snapshot", real)
        return written

    def test_a_copied_image_comes_back_when_the_setting_is_off(self):
        # The reported case: copy an image, dictate, the image must still be
        # there to paste afterwards.
        I.Injector.keep_clipboard = False
        written = self._with_fake_writer(True)
        snap = I.ClipboardSnapshot([(8, b"DIB bytes")], "")
        with _NoDelay():
            I.Injector._clipboard_restore(snap, I._clip_gen)
            self._settle()
        self.assertEqual([snap], written)
        self.assertEqual(0, self.cleared)
        self.assertEqual([], self.restored)

    def test_setting_on_never_restores_so_the_dictation_stays(self):
        I.Injector.keep_clipboard = True
        written = self._with_fake_writer(True)
        with _NoDelay():
            I.Injector._clipboard_restore(
                I.ClipboardSnapshot([(8, b"DIB")], ""), I._clip_gen)
            I.Injector._clipboard_restore("old text", I._clip_gen)
            self._settle()
        self.assertEqual([], written)
        self.assertEqual([], self.restored)
        self.assertEqual(0, self.cleared)

    def test_a_failed_snapshot_write_still_puts_the_text_back(self):
        I.Injector.keep_clipboard = False
        self._with_fake_writer(False)
        snap = I.ClipboardSnapshot(
            [(13, "hello\x00".encode("utf-16-le"))], "hello")
        with _NoDelay():
            I.Injector._clipboard_restore(snap, I._clip_gen)
            self._settle()
        self.assertEqual(["hello"], self.restored)

    def test_an_empty_snapshot_clears_like_empty_text(self):
        I.Injector.keep_clipboard = False
        self._with_fake_writer(True)
        with _NoDelay():
            I.Injector._clipboard_restore(I.ClipboardSnapshot([], ""), I._clip_gen)
            self._settle()
        self.assertEqual(1, self.cleared)


@unittest.skipUnless(sys.platform == "win32", "Win32 clipboard")
class RealClipboardRoundTripTests(unittest.TestCase):
    """Against the real Windows clipboard: an image + HTML + text snapshot
    survives a dictation overwriting it. The user's own clipboard is saved
    first and put back afterwards."""

    def setUp(self):
        self._saved = I._clipboard_snapshot()

    def tearDown(self):
        if self._saved:
            I._clipboard_write_snapshot(self._saved)
        else:
            I.Injector._clipboard_clear()

    def test_image_html_and_text_survive_a_paste_overwrite(self):
        import ctypes
        import struct
        hdr = struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 32, 0, 16, 0, 0, 0, 0)
        dib = hdr + bytes([255, 0, 0, 255] * 4)
        html = ctypes.windll.user32.RegisterClipboardFormatW("HTML Format")
        self.assertTrue(I._clipboard_write_snapshot(I.ClipboardSnapshot(
            [(8, dib), (html, b"<b>hi</b>\x00"),
             (13, "caption\x00".encode("utf-16-le"))], "caption")))

        ok, prev = I.Injector._clipboard_set("dictated words")
        self.assertTrue(ok)
        self.assertIsInstance(prev, I.ClipboardSnapshot)
        self.assertEqual("dictated words", I._clipboard_snapshot().text)

        self.assertTrue(I._clipboard_write_snapshot(prev))
        back = dict(I._clipboard_snapshot().formats)
        self.assertEqual(dib, back[8][:len(dib)])
        self.assertTrue(back[html].startswith(b"<b>hi</b>"))
        self.assertEqual("caption", I._clipboard_snapshot().text)

    def test_ole_plumbing_and_gdi_handles_are_never_copied(self):
        self.assertTrue(I._snapshot_skips(2))       # CF_BITMAP
        self.assertTrue(I._snapshot_skips(14))      # CF_ENHMETAFILE
        self.assertTrue(I._snapshot_skips(0x300))   # GDI object range
        self.assertFalse(I._snapshot_skips(8))      # CF_DIB
        self.assertFalse(I._snapshot_skips(15))     # CF_HDROP (copied files)


class SettingWiringTests(unittest.TestCase):
    """The flag has to be mirrored onto the Injector, or the helpers (which are
    static and never see the config) fall back to the default."""

    def test_app_mirrors_the_setting_at_startup_and_on_change(self):
        import inspect
        import app as app_mod
        src = inspect.getsource(app_mod.WhisperFlowApp)
        self.assertIn("Injector.keep_clipboard", src)
        applied = inspect.getsource(app_mod.WhisperFlowApp._apply_runtime_setting)
        self.assertIn("copy_to_clipboard", applied,
                      "toggling the setting must apply live, not on restart")


if __name__ == "__main__":
    unittest.main()
