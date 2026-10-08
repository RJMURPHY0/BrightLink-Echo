"""Borderless windows are placed in REAL pixels.

The app is DPI-unaware, so on a scaled monitor every Win32 number it reads is
scaled (a 150% 1920x1200 laptop reads as 1280x800). Tk's borderless
(overrideredirect) windows are NOT scaled by Windows: they land at the raw
numbers they are given. The pill was placed with scaled maths and drawn in real
pixels, so on Ryan's 150% laptop (below two 100% screens) it opened up and to
the left of the bottom-centre spot, over the middle of the window (2026-10-06).
"""
import ctypes
import ctypes.wintypes as W
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import popup as popup_mod
from popup import FloatingPopup, OverlayMonitor

# Ryan's laptop, measured live: scaled rect vs real rect, taskbar 72px real.
LAPTOP = OverlayMonitor(scaled=(949, 1080, 2229, 1880),
                        real=(949, 1080, 2869, 2280),
                        work=(949, 1080, 2869, 2208))


class OverlayMonitorTests(unittest.TestCase):
    def test_scaled_point_maps_to_real_pixels(self):
        # The exact spot the shipped pill used: scaled (1443,1776) is the
        # bottom-centre of the laptop, which is real (1690,2124).
        self.assertEqual((1690, 2124), LAPTOP.real_point(1443, 1776))

    def test_round_trip(self):
        for pt in ((949, 1080), (1500, 1500), (2229, 1880)):
            self.assertEqual(pt, LAPTOP.scaled_point(*LAPTOP.real_point(*pt)))

    def test_unscaled_monitor_is_identity(self):
        m = OverlayMonitor((0, 0, 1920, 1080), (0, 0, 1920, 1080),
                           (0, 0, 1920, 1032))
        self.assertEqual((812, 976), m.real_point(812, 976))
        self.assertEqual((812, 976), m.scaled_point(812, 976))

    def test_overlay_monitor_returns_none_without_win32(self):
        with mock.patch.object(popup_mod, "_monitor_user32",
                               side_effect=OSError("no user32")):
            self.assertIsNone(popup_mod.overlay_monitor(5, 5))


class _FakeRoot:
    def __init__(self, w=291, h=56):
        self.w, self.h, self.geometries = w, h, []

    def update_idletasks(self):
        pass

    def winfo_reqwidth(self):
        return self.w

    def winfo_reqheight(self):
        return self.h

    def geometry(self, g):
        self.geometries.append(g)

    def winfo_ismapped(self):
        return False

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080


def _popup(root, offset=30, align="centre", height="low"):
    p = FloatingPopup.__new__(FloatingPopup)
    p.root = root
    p._mode = "status"
    p._target_hwnd = 0
    p._popup_hwnd = 0           # no real window: the physical guard skips
    p._popup_align = align
    p._popup_height = height
    p._popup_offset = offset
    p._last_geometry = ""
    return p


# The GIGABYTE laptop alone at 150% (2026-10-07, %TEMP%\ftc_pos_debug.log):
# the pill was asked for (1774,2199) and dragged back up to y=1472.
GIGABYTE = OverlayMonitor(scaled=(0, 0, 1707, 1067),
                          real=(0, 0, 2560, 1600),
                          work=(0, 0, 2560, 1528))


class RepositionRealPixelTests(unittest.TestCase):
    def _place(self, p, *args, mon=LAPTOP, **kw):
        with mock.patch.object(popup_mod, "_overlay_monitor_from_handle",
                               return_value=mon), \
             mock.patch.object(FloatingPopup, "_is_real_pixel_window",
                               lambda self: True), \
             mock.patch.object(popup_mod, "_RealPixels",
                               popup_mod.contextlib.nullcontext), \
             mock.patch.object(popup_mod, "pos_log"):
            p._start_size_watch = lambda: None
            FloatingPopup._reposition(p, *args, **kw)
        return p.root.geometries[-1]

    def _xy(self, g):
        x, y = g.split("+")[1:]
        return int(x), int(y)

    def test_pill_sits_bottom_centre_of_the_laptop_in_real_pixels(self):
        p = _popup(_FakeRoot())
        g = self._place(p, 1522, 1780)
        # centre: 949 + (1920 - 291) // 2; low: 2208 - 56 - 6*1.5 - 30*1.5
        self.assertEqual("291x56+1763+2098", g)

    def test_pill_is_centred_on_the_150_percent_laptop_on_its_own(self):
        # Shipped: x=1774, three quarters of the way across, because the
        # real-pixel work area was multiplied by 1.5 a second time.
        p = _popup(_FakeRoot(), offset=popup_mod._POPUP_OFFSET_DEFAULT)
        x, y = self._xy(self._place(p, 919, 961, mon=GIGABYTE))
        self.assertEqual((2560 - 291) // 2, x)
        self.assertEqual(1528 - 56 - 9 - 12, y)

    def test_every_display_scale_centres_and_keeps_the_same_gap(self):
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 3.0):
            for rw, rh in ((1366, 768), (1920, 1080), (2560, 1600),
                           (3840, 2160), (1280, 1024)):
                sw, sh = round(rw / scale), round(rh / scale)
                bar = round(48 * scale)
                mon = OverlayMonitor((0, 0, sw, sh), (0, 0, rw, rh),
                                     (0, 0, rw, rh - bar))
                with self.subTest(scale=scale, size=(rw, rh)):
                    p = _popup(_FakeRoot(),
                               offset=popup_mod._POPUP_OFFSET_DEFAULT)
                    x, y = self._xy(self._place(p, sw // 2, sh // 2, mon=mon))
                    self.assertLessEqual(abs(x + 291 / 2 - rw / 2), 1)
                    gap_logical = (rh - bar - (y + 56)) / (rh / sh)
                    self.assertAlmostEqual(
                        6 + popup_mod._POPUP_OFFSET_DEFAULT, gap_logical,
                        delta=1.5)

    def test_placement_never_reads_system_metrics(self):
        # GetSystemMetrics and winfo_screenwidth answer in different DPI
        # contexts; their ratio is what shoved the pill off-centre.
        import inspect
        for fn in (FloatingPopup._reposition_now, FloatingPopup._place_xy):
            self.assertNotIn("GetSystemMetrics", inspect.getsource(fn))

    def test_the_pill_keeps_its_unscaled_size(self):
        # Ryan likes the pill's size as it is: placement must not resize it.
        p = _popup(_FakeRoot())
        g = self._place(p, 1522, 1780)
        self.assertTrue(g.startswith("291x56+"), g)

    def test_near_cursor_anchor_is_converted_to_real_pixels(self):
        p = _popup(_FakeRoot(w=200, h=100))
        g = self._place(p, 1443, 1500, near_cursor=True)
        rx, ry = LAPTOP.real_point(1443, 1500)
        self.assertEqual(f"200x100+{rx - 100}+{ry + 42}", g)  # 28 * 1.5


class PillOffsetDefaultTests(unittest.TestCase):
    def _load(self, value):
        import json
        import tempfile
        import config as config_mod
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"popup_offset": value}, f)
        return config_mod.Config.load(path).popup_offset

    def test_config_and_popup_agree_on_the_default(self):
        import config as config_mod
        self.assertEqual(config_mod.POPUP_OFFSET_DEFAULT,
                         popup_mod._POPUP_OFFSET_DEFAULT)
        self.assertEqual(config_mod.POPUP_OFFSET_DEFAULT,
                         config_mod.Config().popup_offset)

    def test_the_old_untouched_default_moves_to_the_new_one(self):
        import config as config_mod
        self.assertEqual(config_mod.POPUP_OFFSET_DEFAULT, self._load(30))

    def test_a_pill_someone_moved_stays_where_they_put_it(self):
        for v in (48, 12, -6, 66):
            self.assertEqual(v, self._load(v))


def _scaled_monitors():
    """Every monitor's rect in this (DPI-unaware) process's scaled space."""
    u32 = ctypes.WinDLL("user32")
    out = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.POINTER(W.RECT), W.LPARAM)

    def cb(_h, _dc, r, _l):
        rr = r.contents
        out.append((rr.left, rr.top, rr.right, rr.bottom))
        return True

    u32.EnumDisplayMonitors(None, None, proc(cb), 0)
    return out


class _LiveBase(unittest.TestCase):
    def _master(self):
        import tkinter as tk
        existing = getattr(tk, "_default_root", None)
        try:
            master = existing or tk.Tk()
        except Exception as e:
            raise unittest.SkipTest(f"Tk unavailable: {e}")
        if existing is None:
            self.addCleanup(master.destroy)
        if not _scaled_monitors():
            raise unittest.SkipTest("no monitors in this window station")
        return master

    def _assert_bottom_centre(self, got, mon, size=None):
        self.assertIsNotNone(got)
        wl, wt, wr, wb = mon.work
        self.assertGreaterEqual(got[0], wl)
        self.assertGreaterEqual(got[1], wt)
        self.assertLessEqual(got[2], wr)
        self.assertLessEqual(got[3], wb)
        mid = (got[0] + got[2]) // 2
        self.assertLessEqual(abs(mid - (wl + wr) // 2), 2,
                             "not horizontally centred")
        self.assertGreater(got[3], wb - 120, "not near the bottom")
        if size is not None:
            self.assertEqual(size, (got[2] - got[0], got[3] - got[1]),
                             "Windows rescaled the pill")


class LivePopupPlacementTests(_LiveBase):
    """The REAL FloatingPopup on this machine's real monitors, with the app's
    other window both shown and hidden (the state Windows keys borderless
    scaling off). On Ryan's rig this includes the 150% laptop."""

    def _popup(self, master):
        p = FloatingPopup()
        p.initialize(master)
        for win, _h in p._windows.values():
            self.addCleanup(win.destroy)
        return p

    def _show_at(self, master, p, cx, cy):
        with mock.patch.object(popup_mod, "pos_log"):
            p.show_status("Recording", recording=True, cursor_x=cx, cursor_y=cy)
            for _ in range(5):
                master.update()
        hwnd = ctypes.WinDLL("user32").GetAncestor(W.HWND(p._popup_hwnd), 2)
        return popup_mod.real_window_rect(hwnd)

    def _run_all_monitors(self, master):
        p = self._popup(master)
        for (l, t, r, b) in _scaled_monitors():
            cx, cy = (l + r) // 2, (t + b) // 2
            with self.subTest(monitor=(l, t, r, b)):
                got = self._show_at(master, p, cx, cy)
                self.assertTrue(p._is_real_pixel_window(),
                                "the pill is not a per-monitor DPI window")
                size = p._content_size()
                self._assert_bottom_centre(got, popup_mod.overlay_monitor(cx, cy),
                                           size)
                p._do_hide()
                master.update()

    def test_lands_bottom_centre_with_the_dashboard_shown(self):
        master = self._master()
        master.deiconify()
        master.geometry("200x100+100+100")
        master.update()
        self._run_all_monitors(master)

    def test_lands_bottom_centre_with_the_dashboard_hidden(self):
        master = self._master()
        master.withdraw()
        master.update()
        self._run_all_monitors(master)

    def test_content_that_grows_without_a_reposition_is_refitted(self):
        # Tk no longer resizes the pill itself (its size is pinned), so the
        # size watch has to catch a status label that changes width.
        master = self._master()
        p = self._popup(master)
        l, t, r, b = _scaled_monitors()[-1]
        cx, cy = (l + r) // 2, (t + b) // 2
        self._show_at(master, p, cx, cy)
        p._status_label.configure(text="Recording a much longer status line")
        import time as _t
        deadline = _t.time() + 2.0
        with mock.patch.object(popup_mod, "pos_log"):
            while _t.time() < deadline:
                master.update()
                if p._pinned_size == p._content_size():
                    break
        hwnd = ctypes.WinDLL("user32").GetAncestor(W.HWND(p._popup_hwnd), 2)
        size = p._content_size()
        self._assert_bottom_centre(popup_mod.real_window_rect(hwnd),
                                   popup_mod.overlay_monitor(cx, cy), size)
        p._do_hide()


class LiveBadgePlacementTests(_LiveBase):
    """The badge and refine panel keep their old window type (Windows sizes
    them exactly as before, Ryan 2026-10-06); only their placement is fixed:
    bottom-centre of the screen being dictated into, whatever Windows does."""

    def _run(self, master):
        p = FloatingPopup()
        p.initialize(master)
        for win, _h in p._windows.values():
            self.addCleanup(win.destroy)
        for (l, t, r, b) in _scaled_monitors():
            cx, cy = (l + r) // 2, (t + b) // 2
            with self.subTest(monitor=(l, t, r, b)),                     mock.patch.object(popup_mod, "pos_log"):
                # inserted=False: the warning badge, which arms no key hook.
                p.show_cursor_icon("hello", inserted=False,
                                   cursor_x=cx, cursor_y=cy)
                for _ in range(5):
                    master.update()
                self.assertFalse(p._is_real_pixel_window(),
                                 "badge must keep its old window type")
                self.assertIs(p.root, p._windows["main"][0])
                self.assertFalse(p._windows["pill"][0].winfo_ismapped(),
                                 "the pill window must hide for the badge")
                hwnd = ctypes.WinDLL("user32").GetAncestor(
                    W.HWND(p._popup_hwnd), 2)
                self._assert_bottom_centre(popup_mod.real_window_rect(hwnd),
                                           popup_mod.overlay_monitor(cx, cy))
                p._do_hide()
                master.update()

    def test_with_the_dashboard_shown(self):
        master = self._master()
        master.deiconify()
        master.geometry("200x100+100+100")
        master.update()
        self._run(master)

    def test_with_the_dashboard_hidden(self):
        master = self._master()
        master.withdraw()
        master.update()
        self._run(master)


def _pill_pieces_off(p):
    """Every mapped piece of the pill whose real rect differs from where Tk
    laid it out (the black patches when Windows rescales a piece)."""
    u32 = ctypes.WinDLL("user32")
    u32.GetParent.restype = ctypes.c_void_p
    u32.GetParent.argtypes = [ctypes.c_void_p]
    u32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(W.RECT)]
    u32.MapWindowPoints.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.POINTER(W.RECT), ctypes.c_uint]
    off = []
    with popup_mod._RealPixels():
        stack = [p._status_frame]
        while stack:
            w = stack.pop()
            if not w.winfo_ismapped():
                continue
            stack.extend(w.winfo_children())
            r = W.RECT()
            hwnd = w.winfo_id()
            u32.GetWindowRect(hwnd, ctypes.byref(r))
            u32.MapWindowPoints(None, u32.GetParent(hwnd), ctypes.byref(r), 2)
            got = (r.left, r.top, r.right - r.left, r.bottom - r.top)
            want = (w.winfo_x(), w.winfo_y(), w.winfo_width(), w.winfo_height())
            if got != want:
                off.append((w.winfo_class(), got, want))
    return off


class LivePillLayoutTests(_LiveBase):
    """The pill's pieces stay where Tk drew them through a real dictation
    (Starting, Recording, Transcribing, twice). On the 150% laptop the label
    flip and the Transcribing layout made Windows rescale pieces 1.5x, which
    showed as black patches (2026-10-06). The heal safety net is switched off
    so it cannot hide a slip."""

    def _pump(self, master, secs):
        import time as _t
        end = _t.time() + secs
        while _t.time() < end:
            master.update()
            _t.sleep(0.01)

    def _run(self, master):
        p = FloatingPopup()
        p.initialize(master)
        for win, _h in p._windows.values():
            self.addCleanup(win.destroy)
        for (l, t, r, b) in _scaled_monitors():
            cx, cy = (l + r) // 2, (t + b) // 2
            with self.subTest(monitor=(l, t, r, b)),                     mock.patch.object(popup_mod, "pos_log"),                     mock.patch.object(FloatingPopup, "_heal_pill_layout",
                                      lambda self: 0):
                for _ in range(2):
                    p.show_status("Starting…", recording=True,
                                  cursor_x=cx, cursor_y=cy)
                    self._pump(master, 0.2)
                    p.set_status_text("Recording")
                    self._pump(master, 0.3)
                    self.assertEqual([], _pill_pieces_off(p), "recording")
                    p.show_status("Transcribing…", recording=False,
                                  cursor_x=cx, cursor_y=cy)
                    self._pump(master, 0.3)
                    self.assertEqual([], _pill_pieces_off(p), "transcribing")
                p._do_hide()
                master.update()

    def test_with_the_dashboard_shown(self):
        master = self._master()
        master.deiconify()
        master.geometry("200x100+100+100")
        master.update()
        self._run(master)

    def test_with_the_dashboard_hidden(self):
        master = self._master()
        master.withdraw()
        master.update()
        self._run(master)


class LiveFallbackPlacementTests(_LiveBase):
    """The fallback for a borderless window Windows may scale (no per-monitor
    DPI window): _reposition measures where it landed and corrects it."""

    def _check(self, master):
        import tkinter as tk
        top = tk.Toplevel(master)
        self.addCleanup(top.destroy)
        top.withdraw()
        top.overrideredirect(True)
        tk.Frame(top, width=291, height=56, bg="#333").pack()
        top.update_idletasks()
        p = _popup(top)
        p._popup_hwnd = top.winfo_id()
        p._repaint_popup = lambda: None
        self.assertFalse(p._is_real_pixel_window())
        hwnd = ctypes.WinDLL("user32").GetAncestor(W.HWND(top.winfo_id()), 2)
        for (l, t, r, b) in _scaled_monitors():
            cx, cy = (l + r) // 2, (t + b) // 2
            with self.subTest(monitor=(l, t, r, b)),                     mock.patch.object(popup_mod, "pos_log"):
                FloatingPopup._reposition(p, cx, cy)
                top.deiconify()
                top.update()
                self._assert_bottom_centre(popup_mod.real_window_rect(hwnd),
                                           popup_mod.overlay_monitor(cx, cy))
                top.withdraw()

    def test_with_the_dashboard_shown(self):
        master = self._master()
        master.deiconify()
        master.geometry("200x100+100+100")
        master.update()
        self._check(master)

    def test_with_the_dashboard_hidden(self):
        master = self._master()
        master.withdraw()
        master.update()
        self._check(master)


class DashboardUntouchedByPopupStartTests(_LiveBase):
    """update_idletasks() flushes every window's pending work. The popup's
    start-up ran it inside _RealPixels, so a dashboard resize still pending
    (the saved window size, a page swap) was applied in real pixels: on the
    150% laptop the dashboard jumped and shrank to 2/3, pages clipped with
    black beyond (2026-10-07)."""

    def test_make_window_flushes_the_app_before_real_pixels(self):
        import inspect
        src = inspect.getsource(FloatingPopup._make_window)
        self.assertLess(src.index("main_root.update_idletasks()"),
                        src.index("_RealPixels()"))

    def test_pending_dashboard_resize_survives_popup_start(self):
        scaled = []
        for (l, t, r, b) in _scaled_monitors():
            mon = popup_mod.overlay_monitor((l + r) // 2, (t + b) // 2)
            if mon is not None and mon.scaled != mon.real:
                scaled.append((l, t))
        if not scaled:
            raise unittest.SkipTest("no scaled monitor on this machine")
        master = self._master()
        for (l, t) in scaled:
            with self.subTest(monitor=(l, t)):
                master.deiconify()
                master.geometry(f"420x600+{l + 100}+{t + 100}")
                master.update()
                master.geometry("460x640")      # still pending, as at start-up
                p = FloatingPopup()
                p.initialize(master)
                for win, _h in p._windows.values():
                    self.addCleanup(win.destroy)
                for _ in range(5):
                    master.update()
                self.assertEqual((master.winfo_width(), master.winfo_height()),
                                 (460, 640), "dashboard resized in real pixels")
                self.assertEqual((master.winfo_x(), master.winfo_y()),
                                 (l + 100, t + 100), "dashboard jumped")


if __name__ == "__main__":
    unittest.main()
