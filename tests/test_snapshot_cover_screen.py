"""The scroll cover must HIDE the page under it on the real screen.

2026-11-04: after SnapshotCover.refresh() the cover added its pixels onto the
live page instead of replacing it (created per-pixel-alpha, refreshed with
ULW_OPAQUE that DWM ignored, BitBlt alpha bytes 0). Scrolling Settings turned
orange to yellow, lightened every grey and showed each row twice.
tools/scroll_check.py judged only the cover's own buffer, which was right, so
nothing caught it. These tests read the SCREEN.

Needs an interactive desktop; skipped where a window cannot be shown.
"""

import ctypes
import sys
import time
import unittest
from ctypes import wintypes as W

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

import snapshot_cover as sc  # noqa: E402

ORANGE = (243, 146, 0)
BLUE = (0, 90, 200)


def _api():
    u32 = ctypes.WinDLL("user32")
    g32 = ctypes.WinDLL("gdi32")
    u32.GetDC.restype = W.HDC
    u32.GetDC.argtypes = [W.HWND]
    u32.ReleaseDC.argtypes = [W.HWND, W.HDC]
    u32.GetAncestor.restype = W.HWND
    u32.GetAncestor.argtypes = [W.HWND, W.UINT]
    g32.GetPixel.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]
    g32.GetPixel.restype = W.DWORD
    return u32, g32


def _screen_px(x, y):
    u32, g32 = _api()
    dc = u32.GetDC(None)
    try:
        c = g32.GetPixel(dc, x, y)
    finally:
        u32.ReleaseDC(None, dc)
    return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)


def _close(a, b, tol=6):
    return all(abs(p - q) <= tol for p, q in zip(a, b))


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class CoverIsOpaqueOnScreenTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        try:
            self.root = tk.Tk()
        except Exception as exc:
            self.skipTest(f"no display: {exc}")
        # A real title: the desktop popup guard hides untitled 'tk' windows.
        self.root.title("Echo cover check")
        self.root.geometry("200x120+20+20")
        self.root.attributes("-topmost", True)
        self.frame = tk.Frame(self.root, bg="#%02x%02x%02x" % ORANGE)
        self.frame.pack(fill="both", expand=True)
        self.root.update()
        u32, _g = _api()
        self.top = u32.GetAncestor(self.root.winfo_id(), 2)
        # A process started hidden (CI, an agent shell) has its FIRST
        # ShowWindow forced to its start-up mode: show twice.
        u32.ShowWindow.argtypes = [W.HWND, ctypes.c_int]
        u32.ShowWindow(self.top, 5)
        u32.ShowWindow(self.top, 5)
        self.pt = (self.root.winfo_rootx() + 50, self.root.winfo_rooty() + 50)
        # Wait out the window's open animation (up to 3s).
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self.root.update()
            self.pt = (self.root.winfo_rootx() + 50,
                       self.root.winfo_rooty() + 50)
            if _close(_screen_px(*self.pt), ORANGE):
                break
            time.sleep(0.05)
        seen = _screen_px(*self.pt)
        if not _close(seen, ORANGE):
            why = (f"test window not visible on screen: {seen} at {self.pt}, "
                   f"state {self.root.state()}")
            self.root.destroy()
            self.skipTest(why)
        self.cover = None

    def tearDown(self):
        if getattr(self, "cover", None):
            self.cover.close()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _settle(self):
        for _ in range(4):
            self.root.update()
            sc._dwm_flush()
            time.sleep(0.03)

    def test_refresh_shows_the_page_unchanged(self):
        self.cover = sc.SnapshotCover.over(self.top)
        self.assertIsNotNone(self.cover)
        self.assertTrue(self.cover.refresh(self.top))
        self._settle()
        self.assertTrue(_close(_screen_px(*self.pt), ORANGE),
                        f"cover blended: {_screen_px(*self.pt)}")

    def test_cover_hides_changes_under_it_after_refresh(self):
        self.cover = sc.SnapshotCover.over(self.top)
        self.assertIsNotNone(self.cover)
        self.assertTrue(self.cover.refresh(self.top))
        self.frame.configure(bg="#%02x%02x%02x" % BLUE)
        self._settle()
        self.assertTrue(_close(_screen_px(*self.pt), ORANGE),
                        f"page showed through the cover: {_screen_px(*self.pt)}")
        # And a second refresh shows the new frame exactly.
        self.assertTrue(self.cover.refresh(self.top))
        self._settle()
        self.assertTrue(_close(_screen_px(*self.pt), BLUE),
                        f"refresh did not show the new frame: {_screen_px(*self.pt)}")

    def test_partial_refresh_keeps_opaque(self):
        self.cover = sc.SnapshotCover.over(self.top)
        self.assertTrue(self.cover.refresh(self.top))
        self.frame.configure(bg="#%02x%02x%02x" % BLUE)
        self._settle()
        # Region refresh, the path every scroll step takes.
        self.assertTrue(self.cover.refresh(self.top, (0, 0, 120, 80)))
        self._settle()
        self.assertTrue(_close(_screen_px(*self.pt), BLUE),
                        f"partial refresh blended: {_screen_px(*self.pt)}")


class OneBlendModeTests(unittest.TestCase):
    def test_no_per_pixel_alpha_and_no_ulw_opaque(self):
        import inspect
        src = inspect.getsource(sc)
        self.assertNotIn("_Blend(0, 0, 255, 1)", src)
        b = sc._opaque_blend()
        self.assertEqual((b.BlendOp, b.SourceConstantAlpha, b.AlphaFormat),
                         (0, 255, 0))
        body = inspect.getsource(sc.SnapshotCover._refresh)
        self.assertNotIn(", _ULW_OPAQUE", body)


if __name__ == "__main__":
    unittest.main()
