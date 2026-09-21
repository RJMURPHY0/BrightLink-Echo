"""The dashboard's tab strip: BrightLink's connected tabs, ported.

The shape and glow numbers are the CRM's and are checked by eye against it;
what is pinned here is the behaviour that a regression would break quietly:
the current tab stands over its neighbours and opens into the page below, the
others stop exactly on the line, a click lands on the tab that is on top where
two overlap, hovering the current tab changes nothing, and all four tabs keep
their icons at the narrowest window the app allows.
"""

import inspect
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk  # noqa: E402

import bookmark_tabs as bt  # noqa: E402
import ui_render  # noqa: E402
import app_window  # noqa: E402
from app_window import AppWindow  # noqa: E402

_ROOT = None


def setUpModule():
    global _ROOT
    try:
        _ROOT = tk.Tk()
        _ROOT.withdraw()
    except tk.TclError:
        _ROOT = None


def tearDownModule():
    ui_render.clear_cache()
    if _ROOT is not None:
        try:
            _ROOT.destroy()
        except tk.TclError:
            pass


def _strip(width, active="home"):
    if _ROOT is None:
        raise unittest.SkipTest("no display")
    picked = []
    s = bt.BookmarkTabs(_ROOT, AppWindow._DASH_TABS, on_select=picked.append,
                        bg="#0d0d0d", line="#2d2d2d")
    s._width = width
    s._relayout()
    s.set_active(active)
    return s, picked


class GeometryTests(unittest.TestCase):
    def test_every_fillet_is_tangent(self):
        # The outline is built from fillets; a wrong centre shows as a kink
        # where a curve meets a side. Each arc's radius must match its target.
        g = bt.TabGeom(20, 100, active=False)
        rim = g.rim
        n = 15                              # _arc returns steps + 1 points
        for k, r in ((0, bt.FOOT_R), (1, bt.TOP_R), (2, bt.TOP_R), (3, bt.FOOT_R)):
            arc = rim[k * n:(k + 1) * n]
            a, mid, b = arc[0], arc[n // 2], arc[-1]
            # Circumradius of three points on the arc.
            ab, bc, ca = (math.dist(a, mid), math.dist(mid, b), math.dist(b, a))
            area = abs((mid[0] - a[0]) * (b[1] - a[1])
                       - (b[0] - a[0]) * (mid[1] - a[1])) / 2
            self.assertAlmostEqual(ab * bc * ca / (4 * area), r, places=3)

    def test_feet_stand_on_the_line(self):
        for active in (True, False):
            g = bt.TabGeom(20, 100, active)
            self.assertAlmostEqual(g.rim[0][1], bt.TAB_H)
            self.assertAlmostEqual(g.rim[-1][1], bt.TAB_H)

    def test_only_the_current_tab_covers_the_line(self):
        # It opens into the page below; the rest stop exactly on the line.
        self.assertEqual(max(y for _x, y in bt.TabGeom(20, 100, True).shape),
                         bt.TAB_H + 1)
        self.assertEqual(max(y for _x, y in bt.TabGeom(20, 100, False).shape),
                         bt.TAB_H)

    def test_inactive_tabs_stand_lower(self):
        self.assertEqual(bt.TabGeom(0, 100, True).y_top, 0)
        self.assertAlmostEqual(bt.TabGeom(0, 100, False).y_top, bt.DROP)

    def test_padding_grows_then_stops(self):
        widths, icons, pad = bt.layout([60, 60], [40, 40], 2000)
        self.assertTrue(icons)
        self.assertAlmostEqual(pad, bt.MAX_PAD)
        self.assertEqual(widths, [60 + 2 * bt.MAX_PAD] * 2)

    def test_icons_go_before_the_padding_does(self):
        widths, icons, pad = bt.layout([90] * 4, [60] * 4, 300)
        self.assertFalse(icons)
        self.assertEqual(len(widths), 4)


class StripTests(unittest.TestCase):
    def test_four_tabs_keep_their_icons_at_the_minimum_window(self):
        s, _ = _strip(app_window.MIN_W)
        self.assertTrue(s._icons_on)
        # ...and the last tab's foot is still inside the window.
        last = s._geoms[AppWindow._DASH_TABS[-1][0]]
        self.assertLess(last.feet[1], app_window.MIN_W)

    def test_every_tab_glyph_exists(self):
        from PIL import Image, ImageDraw
        for _tid, _label, glyph in AppWindow._DASH_TABS:
            im = Image.new("RGBA", (68, 68))
            ui_render._glyph_paint(ImageDraw.Draw(im), 4, glyph, 17, "#ffffff")
            self.assertIsNotNone(im.getbbox(), glyph)

    def test_the_learning_tab_is_the_brain(self):
        self.assertIn(("learning", "Learning", "brain"), AppWindow._DASH_TABS)

    def test_z_order(self):
        s, _ = _strip(420, active="history")
        order = s._z_order("history", "learning")
        self.assertEqual(order[-1], "history")          # current on top
        self.assertEqual(order[-2], "learning")         # then the hovered one
        self.assertEqual(order[:2], ["hotkey", "home"])  # left over right

    def test_order_is_home_learning_hotkey_history(self):
        # Ryan's call: Learning sits next to Home.
        self.assertEqual([t[0] for t in AppWindow._DASH_TABS],
                         ["home", "learning", "hotkey", "history"])

    def test_a_click_in_an_overlap_lands_on_the_tab_on_top(self):
        s, picked = _strip(420, active="history")
        home, nxt = s._geoms["home"], s._geoms[AppWindow._DASH_TABS[1][0]]
        y = bt.TAB_H * 0.6
        # A point inside both: right of the next tab's left side, left of home's right.
        x = (nxt.x_left(y) + home.x_right(y)) / 2
        self.assertTrue(home.contains(x, y) and nxt.contains(x, y))
        self.assertEqual(s._hit(x, y), "home")          # the left one stacks over
        s._on_click(type("E", (), {"x": x, "y": y})())
        self.assertEqual(picked, ["home"])

    def test_hovering_the_current_tab_changes_nothing(self):
        s, _ = _strip(420, active="hotkey")
        self.assertIs(s._photo_for("hotkey", "hotkey"), s._photo_for("hotkey", None))

    def test_no_tab_lit_for_a_page_without_one(self):
        s, _ = _strip(420, active="home")
        s.set_active("settings")
        self.assertIsNone(s.active)
        self.assertFalse(any(g.active for g in s._geoms.values()))

    def test_render_lines_up_with_the_line(self):
        s, _ = _strip(420, active="home")
        img = s._render("home", None)
        self.assertEqual(img.size, (420, bt.HEIGHT))
        # Under an inactive tab the grey line shows; under the current tab it
        # is replaced by the lit orange underline.
        hist = s._geoms["history"]
        x_hist = int(hist.x0 + hist.w / 2)
        self.assertEqual(img.getpixel((x_hist, bt.TAB_H)), (0x2D, 0x2D, 0x2D))
        home = s._geoms["home"]
        r, g, b = img.getpixel((int(home.x0 + home.w / 3), bt.TAB_H))
        self.assertGreater(r, b + 60)
        # Above the tabs is page background.
        self.assertEqual(img.getpixel((1, 0)), (0x0D, 0x0D, 0x0D))

    def test_a_failed_render_never_raises(self):
        s, _ = _strip(420)

        def boom(*_a):
            raise RuntimeError("no numpy")
        s._render = boom
        s._cache.clear()
        self.assertIsNone(s._photo_for("home", "hotkey"))
        s._redraw()                                     # and the widget survives


class WiringTests(unittest.TestCase):
    def test_switching_lights_the_owning_tab(self):
        src = inspect.getsource(AppWindow._switch_dash_tab)
        self.assertIn("self._tab_strip.set_active(self._TAB_OF_PAGE.get(name, name))",
                      src)
        self.assertIn('"learning": self._learning_frame', src)

    def test_the_learning_page_is_built_and_scrolls(self):
        self.assertIn("_build_learning_tab(self._learning_frame)",
                      inspect.getsource(AppWindow._build_dashboard))
        src = inspect.getsource(AppWindow._build_learning_tab)
        self.assertIn("ScrollPane(", src)
        self.assertNotIn("tk.Canvas(", src)
        self.assertIn("_learning_cv", inspect.getsource(AppWindow._route_mousewheel))

    def test_learn_my_phrases_moved_with_its_page(self):
        self.assertIn('"learned_phrases"',
                      inspect.getsource(AppWindow._build_learning_tab))
        self.assertNotIn('"learned_phrases"',
                         inspect.getsource(AppWindow._build_settings_tab))


if __name__ == "__main__":
    unittest.main()
