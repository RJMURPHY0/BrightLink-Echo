"""The "Your impact" from/to range.

Two halves, pinned separately: the picker (a Dropdown with a second tab holding
a calendar) and the range key it produces, which has to scope every card the
same way the five named windows already do.
"""

import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

import config as config_mod
import stats as stats_mod
from app_window import C, Dropdown, RangePicker, _span_label

_SHARED_ROOT = None
_LABELS = ["Today", "This week", "This month", "This year", "All time"]


def _shared_root():
    global _SHARED_ROOT
    if _SHARED_ROOT is not None and _SHARED_ROOT.winfo_exists():
        return _SHARED_ROOT
    try:
        _SHARED_ROOT = tk.Tk()
    except Exception as e:                          # no window station (CI)
        raise unittest.SkipTest(f"Tk unavailable: {e}")
    _SHARED_ROOT.geometry("440x620")
    return _SHARED_ROOT


def tearDownModule():
    global _SHARED_ROOT
    if _SHARED_ROOT is not None:
        try:
            _SHARED_ROOT.destroy()
        except Exception:
            pass
        _SHARED_ROOT = None


class RangeKeyTests(unittest.TestCase):
    """"custom:<start>:<end>" is the whole contract between the picker, the
    config file and the stats window."""

    def test_round_trip(self):
        self.assertEqual(
            config_mod.parse_custom_range("custom:2026-09-01:2026-09-09"),
            (datetime.date(2026, 9, 1), datetime.date(2026, 9, 9)))

    def test_reversed_span_is_normalised(self):
        self.assertEqual(
            config_mod.parse_custom_range("custom:2026-09-09:2026-09-01"),
            (datetime.date(2026, 9, 1), datetime.date(2026, 9, 9)))

    def test_rubbish_is_rejected(self):
        for bad in ("custom:", "custom:2026-09-01", "custom:a:b", "week", "",
                    None, "custom:2026-13-01:2026-09-09"):
            self.assertIsNone(config_mod.parse_custom_range(bad))

    def test_config_accepts_a_custom_key(self):
        self.assertTrue(config_mod._valid_impact_range("custom:2026-01-01:2026-01-31"))
        self.assertTrue(config_mod._valid_impact_range("week"))
        self.assertFalse(config_mod._valid_impact_range("custom:nonsense"))


class SpanLabelTests(unittest.TestCase):
    def test_two_dates(self):
        self.assertEqual(_span_label(datetime.date(2026, 9, 1),
                                     datetime.date(2026, 9, 9)),
                         "1 Sep – 9 Sep")

    def test_single_day(self):
        d = datetime.date(2026, 9, 9)
        self.assertEqual(_span_label(d, d), "9 Sep")

    def test_crossing_years_shows_the_year(self):
        self.assertEqual(_span_label(datetime.date(2025, 12, 30),
                                     datetime.date(2026, 1, 2)),
                         "30 Dec 25 – 2 Jan 26")


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.root = _shared_root()
        self.host = tk.Frame(self.root, bg=C["bg"])
        self.host.pack()
        self.addCleanup(self.host.destroy)
        self.var = tk.StringVar(value="All time")
        self.periods = []
        self.spans = []
        self.p = RangePicker(self.host, self.var, _LABELS, bg=C["surface"],
                             on_period=self.periods.append,
                             on_custom=lambda a, b: self.spans.append((a, b)))
        self.p.pack()
        self.root.update_idletasks()

    def test_it_is_still_a_dropdown(self):
        # The dismiss-anywhere binding and the lose-foreground watch are
        # inherited, not reimplemented — forking them is how a -topmost list
        # ends up orphaned over another app.
        self.assertIsInstance(self.p, Dropdown)
        self.assertTrue(hasattr(self.p, "_watch_foreground"))
        self.assertTrue(hasattr(self.p, "_on_toplevel_click"))

    def test_custom_tab_is_taller_than_the_period_list(self):
        self.p._tab = "periods"
        short = self.p._panel_height()
        self.p._tab = "custom"
        self.assertGreater(self.p._panel_height(), short)

    def test_two_clicks_make_a_span(self):
        a = datetime.date(2026, 9, 1)
        b = datetime.date(2026, 9, 9)
        self.p._pick_day(a)
        self.assertEqual((self.p._sel_start, self.p._sel_end), (a, None))
        self.p._pick_day(b)
        self.assertEqual((self.p._sel_start, self.p._sel_end), (a, b))

    def test_a_click_before_the_start_restarts_rather_than_inverting(self):
        self.p._pick_day(datetime.date(2026, 9, 9))
        self.p._pick_day(datetime.date(2026, 9, 1))
        self.assertEqual(self.p._sel_start, datetime.date(2026, 9, 1))
        self.assertIsNone(self.p._sel_end)

    def test_apply_reports_the_span_and_labels_the_control(self):
        self.p._pick_day(datetime.date(2026, 9, 1))
        self.p._pick_day(datetime.date(2026, 9, 9))
        self.p._apply_custom()
        self.assertEqual(self.spans,
                         [(datetime.date(2026, 9, 1), datetime.date(2026, 9, 9))])
        self.assertEqual(self.var.get(), "1 Sep – 9 Sep")

    def test_every_grid_row_is_filled(self):
        # A five-row month (September 2026) used to leave an empty sixth row
        # above Clear / Apply. The neighbouring months fill it now, dimmed.
        self.p._tab = "custom"
        self.p._cal_month = datetime.date(2026, 9, 1)
        # The lose-foreground watch closes the panel at once when the test
        # root is not the foreground window (the norm mid-suite).
        self.p._watch_foreground = lambda: None
        self.p.open()
        self.addCleanup(self.p.close)
        cv = self.p._menu_cv
        days = [cv.itemcget(i, "text") for i in cv.find_all()
                if cv.type(i) == "text"
                and cv.itemcget(i, "text").isdigit()]
        self.assertEqual(len(days), 42)
        dim = [cv.itemcget(i, "text") for i in cv.find_all()
               if cv.type(i) == "text"
               and cv.itemcget(i, "fill") == RangePicker._OTHER_MONTH]
        # 31 Aug leads, 1-11 Oct trail.
        self.assertEqual(dim, ["31"] + [str(d) for d in range(1, 12)])

    def test_a_dimmed_day_is_pickable(self):
        self.p._pick_day(datetime.date(2026, 9, 28))
        self.p._pick_day(datetime.date(2026, 10, 2))
        self.assertEqual(self.p._sel_end, datetime.date(2026, 10, 2))

    def test_apply_with_one_date_is_a_single_day(self):
        d = datetime.date(2026, 9, 4)
        self.p._pick_day(d)
        self.p._apply_custom()
        self.assertEqual(self.spans, [(d, d)])

    def test_apply_with_nothing_picked_does_nothing(self):
        self.p._apply_custom()
        self.assertEqual(self.spans, [])

    def test_clear_resets(self):
        self.p._pick_day(datetime.date(2026, 9, 1))
        self.p._clear_custom()
        self.assertIsNone(self.p._sel_start)

    def test_month_stepping_wraps_the_year(self):
        self.p._cal_month = datetime.date(2026, 1, 1)
        self.p._step_month(-1)
        self.assertEqual(self.p._cal_month, datetime.date(2025, 12, 1))
        self.p._step_month(1)
        self.assertEqual(self.p._cal_month, datetime.date(2026, 1, 1))

    def test_period_click_reports_the_label(self):
        self.p._choose_period("This week")
        self.assertEqual(self.periods, ["This week"])
        self.assertEqual(self.var.get(), "This week")

    def test_set_custom_seeds_the_calendar_and_opens_on_that_tab(self):
        a = datetime.date(2026, 3, 4)
        self.p.set_custom(a, datetime.date(2026, 3, 20))
        self.assertEqual(self.p._cal_month, datetime.date(2026, 3, 1))
        self.assertEqual(self.p._tab, "custom")

    def test_control_widens_for_a_span_label(self):
        narrow = self.p._natural_width()
        self.var.set("30 Dec 25 – 2 Jan 26")
        self.assertGreater(self.p._natural_width(), narrow)


class _FakeWindow:
    def __init__(self, top, height):
        self._top, self._height = top, height

    def winfo_rooty(self):
        return self._top

    def winfo_height(self):
        return self._height


class PlacementTests(unittest.TestCase):
    """One way out. Reported with screenshots: Periods opened one way, From / to
    another, and switching back to Periods left the short list floating where
    the tall panel's top had been. The side is now chosen once per open from
    the tallest tab, and the edge next to the control stays glued to it."""

    MONITOR = (0, 0, 1280, 752)         # Ryan's laptop work area

    def setUp(self):
        import app_window
        self.root = _shared_root()
        self.host = tk.Frame(self.root, bg=C["bg"])
        self.host.pack()
        self.addCleanup(self.host.destroy)
        self.var = tk.StringVar(value="All time")
        self.p = RangePicker(self.host, self.var, _LABELS, bg=C["surface"])
        self.p.pack()
        self.root.update_idletasks()
        saved = app_window._monitor_work_area
        app_window._monitor_work_area = lambda _w: self.MONITOR
        self.addCleanup(lambda: setattr(app_window, "_monitor_work_area", saved))
        self.addCleanup(self.p.close)

    def place(self, ctl_top, win_top=60, win_height=658, ctl_left=120):
        self.p.winfo_rooty = lambda: ctl_top
        self.p.winfo_rootx = lambda: ctl_left
        self.p.winfo_height = lambda: 28
        self.p.winfo_toplevel = lambda: _FakeWindow(win_top, win_height)

    def tall(self):
        return max(self.p._panel_height("periods"),
                   self.p._panel_height("custom"))

    def test_a_control_low_in_the_window_opens_above(self):
        self.place(ctl_top=560)
        self.assertTrue(self.p._opens_above(0, 752))

    def test_a_control_high_in_the_window_opens_below(self):
        self.place(ctl_top=140)
        self.assertFalse(self.p._opens_above(0, 752))

    def test_the_open_tab_never_changes_the_side(self):
        # Short Periods fits below this control, tall From / to does not: the
        # old picker dropped Periods DOWN and raised From / to UP.
        self.place(ctl_top=420, win_top=0)
        sides = set()
        for tab in ("periods", "custom"):
            self.p._tab = tab
            sides.add(self.p._opens_above(0, 752))
        self.assertEqual(sides, {True})

    def test_the_monitor_overrides_when_the_tall_tab_cannot_fit(self):
        # Window dragged up off the top of the screen: the control is low in
        # the window, but there is no room above it on the monitor.
        self.place(ctl_top=200, win_top=-400, win_height=658)
        self.assertLess(200 - 4 - self.tall(), 8)
        self.assertFalse(self.p._opens_above(0, 752))

    def test_switching_tabs_keeps_the_bottom_edge_on_the_control(self):
        self.place(ctl_top=560)
        self.p._menu_above = True
        edges = set()
        for tab in ("periods", "custom", "periods"):
            h = self.p._panel_height(tab)
            x, y = self.p._panel_xy(306, h)
            edges.add((x, y + h))
        self.assertEqual(edges, {(120, 556)})

    def test_switching_tabs_keeps_the_top_edge_on_the_control(self):
        self.place(ctl_top=140)
        self.p._menu_above = False
        edges = {self.p._panel_xy(306, self.p._panel_height(tab))[1]
                 for tab in ("periods", "custom")}
        self.assertEqual(edges, {140 + 28 + 4})

    def test_open_and_tab_switches_stay_anchored(self):
        self.place(ctl_top=560)
        self.p._tab = "periods"
        self.p.open()
        self.assertIsNotNone(self.p._menu)

        def bottom():
            geo = self.p._menu.geometry()          # "WxH+X+Y"
            size, x, y = geo.split("+")
            return int(y) + int(size.split("x")[1])

        self.root.update_idletasks()
        first = bottom()
        self.assertEqual(first, 556)
        self.p._set_tab("custom")
        self.assertEqual(bottom(), first)
        self.p._set_tab("periods")
        self.assertEqual(bottom(), first)


class StatsWindowTests(unittest.TestCase):
    """A custom span is a bounded window: it scopes the aggregates and, like
    the named windows, excludes the collapsed carry total."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old = stats_mod._stats_path
        stats_mod._stats_path = lambda: os.path.join(self.tmp.name, "stats.json")
        self.addCleanup(lambda: setattr(stats_mod, "_stats_path", self._old))
        self.store = stats_mod.StatsStore()
        blob = self.store._user_blob()
        blob["carry_words"] = 5000
        for iso, words in (("2026-09-01", 100), ("2026-09-05", 200),
                           ("2026-09-20", 400)):
            blob["days"][iso] = {"w": words, "s": 60.0, "v": 40.0, "vw": words}
        self.store._save_locked()

    def test_span_scopes_the_words(self):
        snap = self.store.snapshot("custom:2026-09-01:2026-09-05")
        self.assertEqual(snap["total_words"], 300)
        self.assertEqual(snap["active_in_range"], 2)

    def test_span_excludes_the_carry_total(self):
        snap = self.store.snapshot("custom:2026-09-01:2026-09-30")
        self.assertEqual(snap["total_words"], 700)      # no 5000 carry

    def test_all_still_includes_the_carry_total(self):
        self.assertEqual(self.store.snapshot("all")["total_words"], 5700)

    def test_footer_count_is_keyed_by_the_range(self):
        key = "custom:2026-09-01:2026-09-05"
        snap = self.store.snapshot(key)
        self.assertEqual(snap["words"][key], 300)
        # The five named totals are still there for the named windows.
        self.assertIn("all", snap["words"])

    def test_a_span_with_no_days_is_empty_not_lifetime(self):
        snap = self.store.snapshot("custom:2020-01-01:2020-01-31")
        self.assertEqual(snap["total_words"], 0)
        self.assertEqual(snap["active_in_range"], 0)


if __name__ == "__main__":
    unittest.main()
