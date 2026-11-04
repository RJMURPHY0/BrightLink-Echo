"""tools/_screen_guard.py: a screen recording another program got into is
reported as spoiled, never judged (4 Nov 2026: Chrome and a minimised test
window read as GLITCH on a different page every run)."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))

import _screen_guard as sg  # noqa: E402


class _FakeUser32:
    def __init__(self, iconic=False, visible=True, owner_pid=None):
        self.iconic, self.visible, self.owner_pid = iconic, visible, owner_pid

    def IsIconic(self, _h):
        return self.iconic

    def IsWindowVisible(self, _h):
        return self.visible

    def GetWindowRect(self, _h, rect):
        r = rect._obj
        r.left, r.top, r.right, r.bottom = 100, 100, 500, 700

    def WindowFromPoint(self, _pt):
        return 4242

    def GetWindowThreadProcessId(self, _h, pid):
        pid._obj.value = self.owner_pid

    def GetAncestor(self, h, _flag):
        return h

    def GetWindowTextW(self, _h, buf, _n):
        buf.value = "Inbox - Google Chrome"


class ScreenGuardTests(unittest.TestCase):
    def _check(self, fake):
        with mock.patch.object(sg, "_u32", fake):
            g = sg.ScreenGuard(1)
            g._check()
        return g.spoiled

    def test_own_window_on_top_is_clean(self):
        self.assertEqual(self._check(_FakeUser32(owner_pid=os.getpid())), [])

    def test_another_program_over_the_window_spoils(self):
        spoiled = self._check(_FakeUser32(owner_pid=os.getpid() + 1))
        self.assertEqual(len(spoiled), 1)
        self.assertIn("Inbox - Google Chrome", spoiled[0][1])

    def test_minimised_window_spoils(self):
        spoiled = self._check(_FakeUser32(iconic=True, owner_pid=os.getpid()))
        self.assertIn("minimised", spoiled[0][1])

    def test_hidden_by_echo_itself_is_not_filmed(self):
        # WM_SETREDRAW during a swap clears WS_VISIBLE: not a spoil.
        fake = _FakeUser32(visible=False, owner_pid=os.getpid() + 1)
        self.assertEqual(self._check(fake), [])

    def test_report_names_each_reason_once_with_time(self):
        g = sg.ScreenGuard(1)
        g._note("test window minimised")
        g._note("test window minimised")
        self.assertEqual(len(g.spoiled), 1)
        self.assertRegex(sg.report(g.spoiled, g.spoiled[0][0] - 2.0),
                         r"test window minimised at \+2\.0s")


if __name__ == "__main__":
    unittest.main()
