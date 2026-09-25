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
_LABELS = ["Today", "Yesterday", "This week", "This month", "Last 6 months",
           "Last 12 months", "All time"]


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


class _Host:
    """Stands in for AppWindow: a section (a plain frame) that the panel is
    swapped in for, exactly like _toggle_range_panel does."""

    H = 204

    def __init__(self, root):
        self.frame = tk.Frame(root, bg=C["bg"], width=384)
        self.frame.pack(fill="x")
        self.section = tk.Frame(self.frame, bg=C["surface"], height=self.H)
        self.section.pack(fill="x")
        self.bar = tk.Frame(self.section, bg=C["surface"])
        self.bar.pack(fill="x")
        self.panel = tk.Canvas(self.frame, bg=C["bg"], highlightthickness=0,
                               bd=0, height=self.H, width=384)
        self.toggles = []

    def toggle(self, show, paint):
        self.toggles.append(show)
        if show:
            self.section.pack_forget()
            self.panel.pack(fill="x")
            self.frame.update_idletasks()
            paint()
        else:
            self.panel.pack_forget()
            self.section.pack(fill="x")


def _picker(test, **kw):
    root = _shared_root()
    host = _Host(root)
    test.addCleanup(host.frame.destroy)
    var = tk.StringVar(value="All time")
    p = RangePicker(host.bar, var, _LABELS, bg=C["surface"],
                    panel=host.panel, on_toggle=host.toggle, **kw)
    p.pack()
    root.update_idletasks()
    test.addCleanup(p.close)
    return root, host, var, p


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.periods = []
        self.spans = []
        self.root, self.host, self.var, self.p = _picker(
            self, on_period=self.periods.append,
            on_custom=lambda a, b: self.spans.append((a, b)))

    def test_it_is_still_a_dropdown(self):
        # The closed control and the dismiss-anywhere binding are inherited,
        # not reimplemented.
        self.assertIsInstance(self.p, Dropdown)
        self.assertTrue(hasattr(self.p, "_on_toplevel_click"))

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
        self.p.open()
        self.p._pick_day(datetime.date(2026, 9, 1))
        self.p._pick_day(datetime.date(2026, 9, 9))
        self.p._apply_custom()
        self.assertEqual(self.spans,
                         [(datetime.date(2026, 9, 1), datetime.date(2026, 9, 9))])
        self.assertEqual(self.var.get(), "1 Sep – 9 Sep")
        self.assertEqual(self.host.toggles, [True, False], "panel left open")

    def test_every_grid_row_is_filled(self):
        # A five-row month (September 2026) used to leave an empty sixth row
        # above Clear / Apply. The neighbouring months fill it now, dimmed.
        self.p._tab = "custom"
        self.p._cal_month = datetime.date(2026, 9, 1)
        self.p.open()
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
        self.p.open()
        self.p._choose_period("This week")
        self.assertEqual(self.periods, ["This week"])
        self.assertEqual(self.var.get(), "This week")
        self.assertIsNone(self.p._menu)

    def test_set_custom_seeds_the_calendar_and_opens_on_that_tab(self):
        a = datetime.date(2026, 3, 4)
        self.p.set_custom(a, datetime.date(2026, 3, 20))
        self.assertEqual(self.p._cal_month, datetime.date(2026, 3, 1))
        self.assertEqual(self.p._tab, "custom")

    def test_control_widens_for_a_span_label(self):
        narrow = self.p._natural_width()
        self.var.set("30 Dec 25 – 2 Jan 26")
        self.assertGreater(self.p._natural_width(), narrow)


class InWindowTests(unittest.TestCase):
    """Reported with screenshots (2026-09-25): the floating panel stayed open
    over the Hotkey tab and hung past the bottom of the app over whatever sat
    behind it. It now opens IN the section it belongs to."""

    def setUp(self):
        self.root, self.host, self.var, self.p = _picker(self)

    def test_it_is_never_a_toplevel(self):
        import inspect
        src = inspect.getsource(RangePicker)
        self.assertNotIn("Toplevel(", src)
        self.assertNotIn(".overrideredirect(", src)
        self.assertNotIn('"-topmost"', src)
        self.p.open()
        self.assertIs(self.p._menu_cv, self.host.panel)
        self.assertIs(self.host.panel.winfo_toplevel(), self.root)

    def test_open_swaps_the_section_for_the_panel_and_back(self):
        self.p.open()
        self.assertTrue(self.host.panel.winfo_ismapped()
                        or self.host.panel.winfo_manager() == "pack")
        self.assertEqual(self.host.section.winfo_manager(), "")
        self.p.close()
        self.assertEqual(self.host.panel.winfo_manager(), "")
        self.assertEqual(self.host.section.winfo_manager(), "pack")

    def test_the_panel_is_never_destroyed_by_close(self):
        self.p.open()
        self.p.close()
        self.assertTrue(self.host.panel.winfo_exists())
        self.p.open()                               # and opens again
        self.assertIsNotNone(self.p._menu)

    def _all_inside(self):
        w, h = self.p._menu_w, self.p._menu_h
        self.assertGreater(w, 100)
        self.assertEqual(h, _Host.H)
        for x0, y0, x1, y1, _fn, _hv in self.p._hits:
            self.assertGreaterEqual(x0, 0)
            self.assertGreaterEqual(y0, 0)
            self.assertLessEqual(x1, w)
            self.assertLessEqual(y1, h)

    def test_both_tabs_fit_the_section(self):
        self.p.open()
        for tab in ("periods", "custom"):
            self.p._set_tab(tab)
            self._all_inside()
        cv = self.p._menu_cv
        for item in cv.find_all():
            x0, y0, x1, y1 = cv.bbox(item)
            self.assertGreaterEqual(y0, -1)
            self.assertLessEqual(y1, _Host.H + 1)

    def test_every_period_is_offered(self):
        self.p.open()
        cv = self.p._menu_cv
        shown = {cv.itemcget(i, "text") for i in cv.find_all()
                 if cv.type(i) == "text"}
        self.assertTrue(set(_LABELS) <= shown)

    def test_calendar_days_do_not_overlap(self):
        self.p._tab = "custom"
        self.p.open()
        days = [h for h in self.p._hits if h[3] - h[1] < 30
                and h[2] - h[0] <= 28 and h[1] > self.p._TAB_H + 40]
        self.assertEqual(len(days), 42)
        for a in days:
            for b in days:
                if a is b:
                    continue
                self.assertFalse(a[0] < b[2] and b[0] < a[2]
                                 and a[1] < b[3] and b[1] < a[3],
                                 "two day cells overlap")

    def test_a_click_in_a_date_field_keeps_it_open(self):
        self.p._tab = "custom"
        self.p.open()
        ent = self.p._entries["start"]
        self.p._on_toplevel_click(type("E", (), {"widget": ent})())
        self.assertIsNotNone(self.p._menu)

    def test_a_click_elsewhere_closes_it(self):
        self.p.open()
        self.p._on_toplevel_click(type("E", (), {"widget": self.root})())
        self.assertIsNone(self.p._menu)

    def test_the_close_control_closes_it(self):
        self.p.open()
        w = self.p._menu_w
        self.p._on_panel_click(type("E", (), {"x": w - 20,
                                              "y": self.p._TAB_H // 2})())
        self.assertIsNone(self.p._menu)

    def test_close_all_closes_it(self):
        # What AppWindow._switch_dash_tab calls on every page change.
        self.p.open()
        Dropdown.close_all()
        self.assertIsNone(self.p._menu)
        self.assertEqual(self.host.section.winfo_manager(), "pack")


class TabSwitchTests(unittest.TestCase):
    def test_switching_page_closes_every_open_list(self):
        import inspect
        from app_window import AppWindow
        src = inspect.getsource(AppWindow._switch_dash_tab)
        self.assertIn("Dropdown.close_all()", src)

    def test_the_host_swaps_the_same_slot_as_the_breakdowns(self):
        import inspect
        from app_window import AppWindow
        src = inspect.getsource(AppWindow._toggle_range_panel)
        self.assertIn("_impact_stack.winfo_height()", src)
        self.assertIn("_impact_today_card.pack_forget()", src)
        self.assertIn("_impact_row.pack_forget()", src)
        self.assertIn("_atomic_ui", src)
        self.assertNotIn("_resize", src)


class NamedWindowTests(unittest.TestCase):
    """Every named window comes from config.named_range_bounds, so the cards
    and the words count agree."""

    TODAY = datetime.date(2026, 9, 25)

    def b(self, key):
        return config_mod.named_range_bounds(key, self.TODAY)

    def test_bounds(self):
        d = datetime.date
        self.assertEqual(self.b("today"), (d(2026, 9, 25), d(2026, 9, 25)))
        self.assertEqual(self.b("yesterday"), (d(2026, 9, 24), d(2026, 9, 24)))
        self.assertEqual(self.b("week"), (d(2026, 9, 21), d(2026, 9, 25)))
        self.assertEqual(self.b("month"), (d(2026, 9, 1), d(2026, 9, 25)))
        self.assertEqual(self.b("6m"), (d(2026, 3, 26), d(2026, 9, 25)))
        self.assertEqual(self.b("12m"), (d(2025, 9, 26), d(2026, 9, 25)))
        self.assertEqual(self.b("year"), (d(2026, 1, 1), d(2026, 9, 25)))
        self.assertIsNone(self.b("all"))

    def test_month_end_clamps(self):
        got = config_mod.named_range_bounds("6m", datetime.date(2026, 8, 31))
        self.assertEqual(got[0], datetime.date(2026, 3, 1))   # 28 Feb + 1

    def test_every_key_is_a_valid_saved_value(self):
        for k in config_mod.IMPACT_RANGES:
            self.assertTrue(config_mod._valid_impact_range(k), k)

    def test_words_buckets_match_the_bounds(self):
        days = {"2026-09-25": {"w": 1}, "2026-09-24": {"w": 10},
                "2026-05-01": {"w": 100}, "2025-12-01": {"w": 1000},
                "2025-01-01": {"w": 10000}}
        t = stats_mod._words_by_range(days, 5, self.TODAY)
        self.assertEqual(t["today"], 1)
        self.assertEqual(t["yesterday"], 10)
        self.assertEqual(t["6m"], 111)
        self.assertEqual(t["12m"], 1111)
        self.assertEqual(t["all"], 11116)


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
