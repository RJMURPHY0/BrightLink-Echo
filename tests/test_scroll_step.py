"""AppWindow._scroll_step under the cases that could leave a cover stuck or
the wheel dead: a step that raises, a failed paint pass, a page change or a
wheel turn arriving inside a step's paint pass, and a pane whose content
shrinks under a scrolled page. Real Tk, a stand-in cover."""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_window import AppWindow, ScrollPane  # noqa: E402

from test_scroll_pane import _make_pane  # noqa: E402


class _Cover:
    def __init__(self):
        self.refreshes = 0
        self.closed = False

    def refresh(self, _hwnd, _region=None):
        self.refreshes += 1
        return True

    def close(self):
        self.closed = True


class _Wheel:
    delta = -120


def _window(root):
    w = object.__new__(AppWindow)
    w._root = root
    w._scroll_states = {}
    w._hist_cv = None
    w._scroll_cover = None
    w._held_cover = None
    w._in_atomic = False
    w.covers = []

    def _cover_window():
        c = _Cover()
        w.covers.append(c)
        return c
    w._cover_window = _cover_window
    w.handed = []
    w._drop_cover_when_drawn = lambda cover, **_k: w.handed.append(cover)
    w._top_hwnd = lambda: 0
    return w


def _pump(root, ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        root.update()
        time.sleep(0.005)


class ScrollStepTests(unittest.TestCase):
    def setUp(self):
        self.root, self.pane = _make_pane()
        self.w = _window(self.root)

    def tearDown(self):
        self.root.destroy()

    def test_a_step_that_raises_still_hands_the_cover_over(self):
        def boom():
            raise RuntimeError("move failed")
        with self.assertRaises(RuntimeError):
            self.w._scroll_step(self.pane, boom)
        _pump(self.root, 150)
        self.assertEqual(self.w.covers, self.w.handed)
        self.assertIsNone(self.w._scroll_cover)

    def test_a_failed_paint_never_reaches_the_cover(self):
        self.w._paint_now = lambda: False
        self.w._scroll_step(self.pane, lambda: self.pane.yview_moveto(0.5))
        cover = self.w.covers[0]
        self.assertEqual(0, cover.refreshes)
        self.assertEqual([cover], self.w.handed)

    def test_a_page_change_in_the_paint_pass_takes_the_cover(self):
        taken = []
        self.w._paint_now = lambda: taken.append(self.w._cover_page_change()) or True
        self.w._scroll_step(self.pane, lambda: self.pane.yview_moveto(0.5))
        cover = self.w.covers[0]
        self.assertEqual([cover], taken)
        self.assertEqual(0, cover.refreshes)     # the page change owns it now
        self.assertIsNone(self.w._scroll_cover)

    def test_a_wheel_turn_in_the_paint_pass_schedules_one_animation(self):
        scheduled = []
        orig_after = self.pane.after

        def after(ms, fn, *a):
            if getattr(fn, "__name__", "") == "_animate_scroll":
                scheduled.append(ms)
            return orig_after(ms, fn, *a)
        self.pane.after = after
        self.w._paint_now = lambda: (self.w._wheel_scroll(self.pane, _Wheel())
                                     and True)
        self.w._wheel_scroll(self.pane, _Wheel())      # schedules frame 1
        self.assertEqual(1, len(scheduled))
        self.w._animate_scroll(self.pane)              # wheel turn inside
        self.assertEqual(2, len(scheduled))            # one follow-on, not two
        self.assertNotEqual("step", self.w._scroll_states[self.pane]["job"])

    def test_a_step_that_raises_leaves_the_wheel_working(self):
        state = {"current": 0.0, "target": 400.0, "job": None}
        self.w._scroll_states[self.pane] = state

        def boom(_cv, _move):
            raise RuntimeError("step failed")
        self.w._scroll_step = boom
        with self.assertRaises(RuntimeError):
            self.w._animate_scroll(self.pane)
        self.assertIsNone(state["job"])

    def test_content_shrinking_under_a_scrolled_page_is_a_step(self):
        steps = []
        self.pane.stepper = lambda cv, move: (steps.append(cv), move())
        self.pane.yview_moveto(1.0)                    # the bottom: 800px
        self.root.update()
        filler = self.pane.content.winfo_children()[0]
        filler.configure(height=500)                   # max top now 300
        self.root.update()
        self.assertEqual([self.pane], steps[:1])
        self.assertEqual(-300, self.pane.content.winfo_y())

    def test_inside_a_covered_change_a_step_only_moves(self):
        self.w._in_atomic = True
        self.w._scroll_step(self.pane, lambda: self.pane.yview_moveto(0.5))
        self.assertEqual([], self.w.covers)

    def test_every_pane_the_window_builds_has_the_stepper(self):
        import inspect
        src = inspect.getsource(AppWindow)
        self.assertEqual(src.count("ScrollPane("),
                         src.count("stepper=self._scroll_step"))
        self.assertIn("stepper", inspect.signature(ScrollPane).parameters)


if __name__ == "__main__":
    unittest.main()
