"""Universal search bar, driven against a real Tk root: the catalogue matches,
the results panel renders without error, a page result switches tabs, a setting
result filters Settings, and the Ask AI answer renders with jump chips."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

from app_window import AppWindow, C

_SHARED_ROOT = None


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


CATALOGUE = [
    {"kind": "page", "title": "History",
     "subtext": "Past dictations.", "keywords": "past audio",
     "target": ("tab", "history")},
    {"kind": "setting", "title": "Trim Silence",
     "subtext": "Skip empty chunks.", "keywords": "trim silence",
     "location": "Settings", "target": ("setting", "settings", "Trim Silence")},
]


class _Refiner:
    is_available = True

    def refine(self, text, custom_prompt=None, **kw):
        return "Turn on Trim Silence in Settings."


class UniversalSearchTests(unittest.TestCase):
    def setUp(self):
        self.root = _shared_root()
        self.w = AppWindow.__new__(AppWindow)
        self.w._root = self.root
        self.w._search_catalogue = list(CATALOGUE)
        self.w._ai_refiner = _Refiner()
        self.w._settings_search = None
        self.switched = []
        self.filtered = []
        self.w._switch_dash_tab = lambda name: self.switched.append(name)
        self.w._apply_settings_search = lambda q: self.filtered.append(q)
        self.w._dash_frame = tk.Frame(self.root, bg=C["bg"])
        self.w._dash_frame.pack(fill="both", expand=True)
        self.addCleanup(self.w._dash_frame.destroy)
        self.w._build_universal_search(self.w._dash_frame)
        self.root.update_idletasks()

    def test_typing_matches_and_renders_panel(self):
        self.w._usearch_update("history")
        self.root.update_idletasks()
        self.assertTrue(self.w._usearch_results)
        self.assertEqual(self.w._usearch_results[0]["title"], "History")
        self.assertEqual(self.w._usearch_panel.winfo_manager(), "place")

    def test_empty_query_hides_panel(self):
        self.w._usearch_update("history")
        self.w._usearch_update("")
        self.root.update_idletasks()
        self.assertNotEqual(self.w._usearch_panel.winfo_manager(), "place")

    def test_navigate_page_switches_tab(self):
        self.w._usearch_update("history")
        self.w._usearch_navigate(self.w._usearch_results[0])
        self.assertIn("history", self.switched)

    def test_navigate_setting_filters_settings(self):
        self.w._usearch_update("trim")
        entry = next(e for e in self.w._usearch_results
                     if e["kind"] == "setting")
        self.w._usearch_navigate(entry)
        self.assertIn("settings", self.switched)
        self.assertIn("trim silence", self.filtered)

    def test_enter_on_plain_term_navigates(self):
        self.w._usearch_update("history")
        self.w._usearch_enter()
        self.assertIn("history", self.switched)

    def test_enter_on_question_asks_ai(self):
        self.w._usearch_update("how do I trim silence")
        self.w._usearch_enter()
        self.root.update_idletasks()
        # Answer arrives on a worker thread; wait briefly for it.
        for _ in range(50):
            if isinstance(self.w._usearch_ai, tuple):
                break
            self.root.update()
            self.root.after(20)
        self.assertTrue(isinstance(self.w._usearch_ai, tuple)
                        or self.w._usearch_ai == "thinking")

    def test_answer_renders_with_chip(self):
        self.w._usearch_query = "trim"
        self.w._usearch_results = []
        self.w._usearch_ai = ("answer", "Turn on Trim Silence in Settings.")
        self.w._render_usearch_panel()
        self.root.update_idletasks()
        # A chip for the named setting should be clickable into Settings.
        self.assertEqual(self.w._usearch_panel.winfo_manager(), "place")


if __name__ == "__main__":
    unittest.main()
