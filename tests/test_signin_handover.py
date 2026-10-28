"""Sign-in to dashboard hand-over (2026-10-28).

Captured frame by frame, the old swap showed a half-drawn dashboard for
200-800ms (the old page through the cards, white bands, a doubled header) and
the splash path also resized 560 to 670 and re-centred the window. The fix:
the splash and login page open at the dashboard's size, and the swap runs
behind a still picture of the page (snapshot_cover) that is dropped only once
the window has stopped changing.
"""
import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

import app_window
import snapshot_cover
from app_window import AppWindow, DASH_H, WINDOW_W


class _Config(SimpleNamespace):
    def __init__(self, **kw):
        super().__init__(window_sizes={}, dashboard_gaps=None, **kw)

    def save_async(self):
        pass


class _Root:
    def __init__(self, w=460, h=700, mapped=True, state="normal"):
        self.w, self.h, self.mapped, self._state = w, h, mapped, state
        self.jobs = []

    def winfo_ismapped(self):
        return self.mapped

    def winfo_width(self):
        return self.w

    def winfo_height(self):
        return self.h

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def state(self):
        return self._state

    def after(self, ms, fn, *args):
        self.jobs.append((ms, fn, args))
        return len(self.jobs)

    def after_idle(self, fn, *args):
        fn(*args)               # the fake loop is always idle

    def run_next(self):
        ms, fn, args = self.jobs.pop(0)
        fn(*args)
        return ms


def _window(email="", last_email="", sizes=None, root=None):
    w = object.__new__(AppWindow)
    w._auth = SimpleNamespace(user_email=email, last_email=last_email,
                              is_authenticated=bool(email))
    w._config = _Config()
    if sizes:
        w._config.window_sizes = dict(sizes)
    w._root = root if root is not None else _Root()
    return w


class _Cover:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


class HandoverSizeTests(unittest.TestCase):
    def test_signed_out_uses_the_last_accounts_dashboard_size(self):
        w = _window(last_email="Ryan@Example.com",
                    sizes={"ryan@example.com": "500x760", "_default": "430x690"})
        self.assertEqual((500, 760), w._handover_size())

    def test_signed_in_uses_this_accounts_size(self):
        w = _window(email="a@example.com", last_email="b@example.com",
                    sizes={"a@example.com": "480x720", "b@example.com": "520x800"})
        self.assertEqual((480, 720), w._handover_size())

    def test_no_saved_size_is_the_natural_dashboard(self):
        self.assertEqual((WINDOW_W, DASH_H), _window()._handover_size())

    def test_splash_opens_at_the_dashboard_size_not_its_own(self):
        src = inspect.getsource(AppWindow._switch_to_signing_in)
        self.assertIn("self._resize(*self._handover_size())", src)
        self.assertNotIn("560", src)

    def test_login_page_holds_the_handover_shape(self):
        self.assertIn("self._handover_size()",
                      inspect.getsource(AppWindow._switch_to_login))
        self.assertIn("self._handover_size()[0]",
                      inspect.getsource(AppWindow._resize_login_page))
        self.assertIn("self._handover_size()[1]",
                      inspect.getsource(AppWindow._build_embedded_login))


class ShowingAtTests(unittest.TestCase):
    def test_same_size_on_screen_is_not_resized_again(self):
        w = _window(root=_Root(460, 700))
        self.assertTrue(w._showing_at((460, 700)))

    def test_other_size_hidden_zoomed_or_pending_all_resize(self):
        self.assertFalse(_window(root=_Root(460, 700))._showing_at((460, 701)))
        self.assertFalse(_window(root=_Root(mapped=False))._showing_at((460, 700)))
        self.assertFalse(_window(root=_Root(state="zoomed"))._showing_at((460, 700)))
        w = _window(root=_Root(460, 700))
        w._pending_geometry = "460x800+0+0"
        self.assertFalse(w._showing_at((460, 700)))

    def test_show_dashboard_skips_the_recentre_when_already_that_size(self):
        src = inspect.getsource(AppWindow._show_dashboard)
        self.assertIn("if self._showing_at(size):", src)


class _Frame:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def pack(self, **_kw):
        self.log.append(f"pack {self.name}")

    def pack_forget(self):
        self.log.append(f"forget {self.name}")


def _swap_window(root):
    log = []
    w = _window(email="a@example.com", root=root)
    w._login_frame = _Frame(log, "login")
    w._signing_in_frame = _Frame(log, "splash")
    w._header_outer = _Frame(log, "header")
    w._cancel_signing_in = lambda: None
    w._show_dashboard = lambda: log.append("show dashboard")
    w._top_hwnd = lambda: 1234
    w._atomic_ui = lambda fn: (log.append("freeze"), fn(), log.append("present"))
    w._drop_cover_when_drawn = lambda c: log.append(("drop", c))
    return w, log


class SwitchToDashboardTests(unittest.TestCase):
    def test_cover_goes_up_before_the_swap_and_comes_down_after(self):
        w, log = _swap_window(_Root())
        cover = _Cover()

        def _over(hwnd):
            log.append(("cover", hwnd))
            return cover

        with mock.patch.object(snapshot_cover.SnapshotCover, "over",
                               staticmethod(_over)):
            w._switch_to_dashboard()
        self.assertEqual(("cover", 1234), log[0])
        self.assertEqual(("drop", cover), log[-1])
        self.assertLess(log.index("freeze"), log.index("show dashboard"))
        self.assertFalse(w._login_visible)

    def test_hidden_or_minimised_window_swaps_without_a_cover(self):
        for root in (_Root(mapped=False), _Root(state="iconic")):
            w, log = _swap_window(root)
            with mock.patch.object(snapshot_cover.SnapshotCover, "over") as over:
                w._switch_to_dashboard()
            over.assert_not_called()
            self.assertIn("show dashboard", log)
            self.assertFalse([e for e in log if isinstance(e, tuple)])

    def test_cover_failure_falls_back_to_the_plain_swap(self):
        w, log = _swap_window(_Root())
        with mock.patch.object(snapshot_cover.SnapshotCover, "over",
                               staticmethod(lambda _h: None)):
            w._switch_to_dashboard()
        self.assertIn("show dashboard", log)
        self.assertFalse([e for e in log if isinstance(e, tuple)])


class DropCoverTests(unittest.TestCase):
    def _run(self, readings, max_steps=50):
        root = _Root()
        w = _window(root=root)
        w._top_hwnd = lambda: 99
        cover = _Cover()
        seq = iter(readings)
        with mock.patch.object(snapshot_cover, "window_fingerprint",
                               lambda _h: next(seq)):
            w._drop_cover_when_drawn(cover)
            polls = 0
            # Run the poll chain only; the deadline job is checked separately.
            while cover.closed == 0 and polls < max_steps:
                polls_jobs = [j for j in root.jobs
                              if j[0] == app_window._COVER_POLL_MS]
                if not polls_jobs:
                    break
                root.jobs.remove(polls_jobs[0])
                polls_jobs[0][1](*polls_jobs[0][2])
                polls += 1
        return cover, root, polls

    def test_closes_once_the_window_has_stopped_changing(self):
        stable = app_window._COVER_STABLE_READS
        cover, _root, polls = self._run([1, 2, 3] + [3] * stable)
        self.assertEqual(1, cover.closed)
        self.assertEqual(3 + stable, polls)

    def test_unreadable_window_closes_at_once(self):
        cover, _root, polls = self._run([None])
        self.assertEqual(1, cover.closed)
        self.assertEqual(1, polls)

    def test_deadline_closes_a_window_that_never_settles(self):
        root = _Root()
        w = _window(root=root)
        w._top_hwnd = lambda: 99
        cover = _Cover()
        w._drop_cover_when_drawn(cover)
        deadline = [j for j in root.jobs if j[0] == app_window._COVER_MAX_MS]
        self.assertEqual(1, len(deadline))
        deadline[0][1]()
        deadline[0][1]()            # a second close is a no-op
        self.assertEqual(1, cover.closed)
        self.assertLessEqual(app_window._COVER_MAX_MS, 2000)


class SnapshotCoverSafetyTests(unittest.TestCase):
    def test_uses_private_dlls_never_the_shared_windll(self):
        src = inspect.getsource(snapshot_cover)
        self.assertNotRegex(src, r"ctypes\.windll\.\w")
        self.assertIn('ctypes.WinDLL("user32"', src)

    def test_cover_never_takes_focus_or_clicks(self):
        src = inspect.getsource(snapshot_cover.SnapshotCover._over)
        for flag in ("_WS_EX_NOACTIVATE", "_WS_EX_TRANSPARENT",
                     "_SWP_NOACTIVATE", "_SW_SHOWNOACTIVATE"):
            self.assertIn(flag, src)

    def test_failures_mean_no_cover(self):
        self.assertIsNone(snapshot_cover.SnapshotCover.over(0))
        with mock.patch.object(snapshot_cover.SnapshotCover, "_over",
                               side_effect=OSError("boom")):
            self.assertIsNone(snapshot_cover.SnapshotCover.over(5))
        with mock.patch.object(snapshot_cover, "_client_pixels",
                               side_effect=OSError("boom")):
            self.assertIsNone(snapshot_cover.window_fingerprint(5))

    def test_reads_the_window_dc_before_printwindow(self):
        # PrintWindow cost 35-100ms a read on the UI thread (2026-10-28), so
        # every covered change waited ~300ms on its own stability checks.
        src = inspect.getsource(snapshot_cover._client_pixels)
        self.assertIn("u32.GetDC(top_hwnd)", src)
        self.assertLess(src.index("g32.BitBlt("), src.index("u32.PrintWindow("))


class PageChangeCoverTests(unittest.TestCase):
    """Tab clicks showed 2 to 6 frames over ~150ms with the old page's cards
    under the new one (captured 2026-10-28). Page changes now run behind the
    same SnapshotCover as the sign-in hand-over."""

    def test_the_tab_switch_runs_behind_a_cover(self):
        self.assertIn("self._covered_change(_swap)",
                      inspect.getsource(AppWindow._switch_dash_tab))
        # Closing the range picker redraws the cards: covered too.
        self.assertIn("self._covered_change(_swap)",
                      inspect.getsource(AppWindow._toggle_range_panel))
        src = inspect.getsource(AppWindow._covered_change)
        self.assertIn("self._cover_page_change()", src)
        self.assertIn("self._covered_ui(fn)", src)
        self.assertIn("max_ms=_PAGE_COVER_MAX_MS", src)
        self.assertIn("poll_ms=_PAGE_COVER_POLL_MS", src)
        # Uncovered (hidden window, Win32 failure) it is the old freeze.
        self.assertIn("self._atomic_ui(fn)", src)

    def test_the_cap_is_a_safety_net_not_a_timer(self):
        # At 600ms a slow moment dropped the cover over a half-drawn page.
        self.assertGreaterEqual(app_window._PAGE_COVER_MAX_MS, 1500)
        self.assertLess(app_window._PAGE_COVER_POLL_MS,
                        app_window._COVER_POLL_MS)

    def test_reads_wait_for_tk_to_be_idle(self):
        src = inspect.getsource(AppWindow._drop_cover_when_drawn)
        self.assertIn("self._root.after_idle(_poll)", src)
        self.assertNotIn("after(poll_ms, _poll)", src)

    def test_a_fast_second_click_takes_the_cover_over(self):
        root = _Root()
        w = _window(root=root)
        w._top_hwnd = lambda: 99
        first = _Cover()
        w._drop_cover_when_drawn(first, max_ms=1500, poll_ms=10)
        with mock.patch.object(snapshot_cover.SnapshotCover, "over") as over:
            self.assertIs(first, w._cover_page_change())
        over.assert_not_called()
        # The first watch is over: its deadline no longer closes the cover
        # the second change now owns.
        for ms, fn, args in [j for j in root.jobs if j[0] == 1500]:
            fn(*args)
        self.assertEqual(0, first.closed)
        w._drop_cover_when_drawn(first, max_ms=1500, poll_ms=10)
        root.jobs[-1][1]()
        self.assertEqual(1, first.closed)

    def test_no_held_cover_means_a_fresh_picture(self):
        w = _window(root=_Root())
        w._top_hwnd = lambda: 99
        fresh = _Cover()
        with mock.patch.object(snapshot_cover.SnapshotCover, "over",
                               staticmethod(lambda _h: fresh)):
            self.assertIs(fresh, w._cover_page_change())

    def test_covered_ui_joins_nested_changes_and_defers_the_resize(self):
        w = _window(root=_Root())
        w._root.update_idletasks = lambda: None
        geos, repaints, log = [], [], []
        w._root.geometry = lambda g: geos.append(g)
        w._repaint_all = lambda erase=False: repaints.append(erase)

        def inner():
            log.append(("inner", w._in_atomic))

        def change():
            w._atomic_ui(inner)          # joins: never presents half-way
            w._pending_geometry = "420x700"
            log.append(("outer", w._in_atomic))

        w._covered_ui(change)
        self.assertEqual([("inner", True), ("outer", True)], log)
        self.assertFalse(w._in_atomic)
        self.assertEqual(["420x700"], geos)
        self.assertEqual([True], repaints)

    def test_covered_ui_never_freezes_or_repaints_a_plain_swap(self):
        src = inspect.getsource(AppWindow._covered_ui)
        self.assertNotIn("SendMessageW", src)
        w = _window(root=_Root())
        w._root.update_idletasks = lambda: None
        w._repaint_all = mock.Mock()
        w._covered_ui(lambda: None)
        w._repaint_all.assert_not_called()


if __name__ == "__main__":
    unittest.main()
