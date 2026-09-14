"""A typed dictation must never press Enter on its own.

Reported with a screenshot (v1.6.79): a dictation with a paragraph break went
into ChatGPT, the message SENT at the break, and the rest of the text landed in
the box after it. Paste cannot do that, so the text had been TYPED: the paste
gate refused, the browser fallback typed it through SendInput, and every "\\n"
was a bare VK_RETURN, which is Send in every chat composer.

Pinned here:
  1. A typed line break is Shift+Enter, and no Enter key-down is ever sent
     without Shift held.
  2. A PARTIAL SendInput is not re-sent in full through WM_CHAR (the keystrokes
     that were accepted would land twice).
  3. The paste gate rides out a foreground flicker instead of refusing, and
     still refuses a real move to another window.
  4. Falling back to typing leaves a reason in the local log.

Pure stubs, no real windows or keystrokes, so safe on any machine.
"""

import ctypes as C
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import injector as I


class _FakeU32:
    def __init__(self, sent_override=None, foreground=None):
        self.batches = []           # list of lists of (vk, scan, flags)
        self.sent_override = sent_override
        self.foreground = list(foreground or [0x1111])
        self.posted = []

    def SendInput(self, n, arr, size):
        self.batches.append([(arr[i].ki.wVk, arr[i].ki.wScan, arr[i].ki.dwFlags)
                             for i in range(n)])
        return n if self.sent_override is None else self.sent_override(n)

    def GetForegroundWindow(self):
        if len(self.foreground) > 1:
            return self.foreground.pop(0)
        return self.foreground[0]

    def GetAsyncKeyState(self, vk):
        return 0

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        self.posted.append(wparam)
        return 1

    def IsWindow(self, h):
        return True

    def GetWindowThreadProcessId(self, hwnd, p):
        return 1

    def GetFocus(self):
        return 0x2222

    def AttachThreadInput(self, a, b, c):
        return 1


class _Patched(unittest.TestCase):
    def patch_u32(self, fake):
        saved_windll, saved_u32 = C.windll, I._u32
        real_kernel32 = saved_windll.kernel32

        class _FakeWinDLL:
            user32 = fake
            kernel32 = real_kernel32

        C.windll = _FakeWinDLL
        I._u32 = fake

        def _restore():
            C.windll = saved_windll
            I._u32 = saved_u32
        self.addCleanup(_restore)


class LineBreakTests(_Patched):
    def _events(self, text):
        fake = _FakeU32()
        self.patch_u32(fake)
        sent, total = I._send_unicode_counted(text)
        self.assertEqual(sent, total)
        return [e for batch in fake.batches for e in batch]

    def test_a_line_break_is_shift_enter(self):
        ev = self._events("a\nb")
        keys = [(vk, flags & I._KEYEVENTF_KEYUP) for vk, _s, flags in ev if vk]
        self.assertEqual(keys, [
            (I._VK_SHIFT, 0), (I._VK_RETURN, 0),
            (I._VK_RETURN, I._KEYEVENTF_KEYUP),
            (I._VK_SHIFT, I._KEYEVENTF_KEYUP),
        ])

    def test_enter_is_never_pressed_without_shift_held(self):
        ev = self._events("One paragraph.\n\nAnother one.\nAnd a line.")
        shift_down = False
        enters = 0
        for vk, _scan, flags in ev:
            up = bool(flags & I._KEYEVENTF_KEYUP)
            if vk == I._VK_SHIFT:
                shift_down = not up
            elif vk == I._VK_RETURN and not up:
                enters += 1
                self.assertTrue(shift_down, "bare Enter sends a chat message")
        self.assertEqual(enters, 3)
        self.assertFalse(shift_down, "Shift must be released at the end")

    def test_windows_line_endings_are_one_break(self):
        ev = self._events("a\r\nb")
        downs = [vk for vk, _s, f in ev
                 if vk == I._VK_RETURN and not f & I._KEYEVENTF_KEYUP]
        self.assertEqual(len(downs), 1)

    def test_characters_still_travel_as_unicode(self):
        ev = self._events("hé")
        scans = [s for vk, s, f in ev
                 if f & I._KEYEVENTF_UNICODE and not f & I._KEYEVENTF_KEYUP]
        self.assertEqual(scans, [ord("h"), ord("é")])


class PartialSendTests(_Patched):
    def _browser_injector(self):
        inj = I.Injector(method="clipboard")
        saved = I._get_fg_class, I._is_browser_class, I._is_game_class
        I._get_fg_class = lambda: "Chrome_WidgetWin_1"
        I._is_browser_class = lambda cls: True
        I._is_game_class = lambda cls: False

        def _restore():
            I._get_fg_class, I._is_browser_class, I._is_game_class = saved
        self.addCleanup(_restore)
        return inj

    def test_a_partial_send_is_not_typed_again(self):
        fake = _FakeU32(sent_override=lambda n: n // 2)
        self.patch_u32(fake)
        inj = self._browser_injector()
        self.assertFalse(inj._direct_inject("hello there"))
        self.assertTrue(inj._partial_direct)
        self.assertEqual(fake.posted, [], "WM_CHAR re-send would duplicate")

    def test_a_send_that_landed_nothing_may_still_fall_back(self):
        fake = _FakeU32(sent_override=lambda n: 0)
        self.patch_u32(fake)
        inj = self._browser_injector()
        self.assertTrue(inj._direct_inject("hi"))
        self.assertFalse(inj._partial_direct)
        self.assertEqual(len(fake.posted), 2)


class PasteGateTests(_Patched):
    TARGET = 0x1111
    OTHER = 0x9999

    def setUp(self):
        saved = I._FOREGROUND_GRACE_SECS
        I._FOREGROUND_GRACE_SECS = 0.2
        self.addCleanup(lambda: setattr(I, "_FOREGROUND_GRACE_SECS", saved))

    def _injector(self):
        inj = I.Injector(method="clipboard")
        inj._target_hwnd = self.TARGET
        inj._clipboard_set = lambda text: (True, "")
        inj._clipboard_restore = lambda *a, **k: None
        return inj

    def test_a_foreground_flicker_still_pastes(self):
        # Our own popup takes the foreground for a moment and hands it back.
        fake = _FakeU32(foreground=[self.OTHER, self.OTHER, self.TARGET])
        self.patch_u32(fake)
        inj = self._injector()
        self.assertTrue(inj._clipboard_paste("para one\n\npara two"))
        ctrl_v = [vk for batch in fake.batches for vk, _s, f in batch
                  if not f & I._KEYEVENTF_KEYUP]
        self.assertEqual(ctrl_v, [0x11, 0x56])

    def test_a_real_move_is_still_refused(self):
        fake = _FakeU32(foreground=[self.OTHER])
        self.patch_u32(fake)
        inj = self._injector()
        self.assertFalse(inj._clipboard_paste("text"))
        self.assertIn("foreground", inj._paste_refusal)
        self.assertEqual(fake.batches, [], "no Ctrl+V into another window")


class FallbackLogTests(_Patched):
    def test_typing_fallback_records_why(self):
        fake = _FakeU32()
        self.patch_u32(fake)
        lines = []
        saved = (I._log_inject_failure, I._get_fg_class, I._is_browser_class,
                 I._is_game_class, I._is_terminal_class, I._get_fg_exe)
        I._log_inject_failure = lines.append
        I._get_fg_class = lambda: "Chrome_WidgetWin_1"
        I._is_browser_class = lambda cls: True
        I._is_game_class = lambda cls: False
        I._is_terminal_class = lambda cls: False
        I._get_fg_exe = lambda: "chrome.exe"

        def _restore():
            (I._log_inject_failure, I._get_fg_class, I._is_browser_class,
             I._is_game_class, I._is_terminal_class, I._get_fg_exe) = saved
        self.addCleanup(_restore)

        inj = I.Injector(method="clipboard")

        def _refuse(text):
            inj._paste_refusal = "foreground 0x9 != target 0x1"
            return False
        inj._clipboard_paste = _refuse
        inj._direct_inject = lambda text: True
        self.assertTrue(inj._inject("one\n\ntwo", release_mods=False))
        self.assertEqual(len(lines), 1)
        self.assertIn("fallback-to-typing: foreground 0x9 != target 0x1",
                      lines[0])
        self.assertIn("line_breaks=2", lines[0])
        self.assertIn("chrome.exe", lines[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
