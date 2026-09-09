"""Settings search.

The settings page is thirty-odd cards over six sections; finding one by
scrolling is the problem the search bar exists to solve. The filter is pure
pack_forget/pack over an index taken at build time — nothing is rebuilt — so
these tests pin that (a) the index survives the real page, (b) a query hides
what does not match and keeps the section header of what does, and (c) clearing
the query puts every card back in its original order with its original padding.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

from app_window import AppWindow, C, ScrollPane

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


class FilterTests(unittest.TestCase):
    """A stand-in page with the same shape the real builder produces: section
    headers registered in _settings_sections, cards packed between them."""

    def setUp(self):
        self.root = _shared_root()
        self.w = AppWindow.__new__(AppWindow)
        self.w._root = self.root
        self.w._settings_sections = set()
        self.w._settings_query = ""
        self.w._settings_rows = []
        self.host = tk.Frame(self.root, bg=C["bg"])
        self.host.pack(fill="both", expand=True)
        self.addCleanup(self.host.destroy)
        self.w._settings_cv = ScrollPane(self.host, bg=C["bg"])
        self.w._settings_cv.pack(fill="both", expand=True)
        parent = self.w._settings_cv.content

        def section(title):
            row = tk.Frame(parent, bg=C["bg"])
            row.pack(fill="x", padx=22, pady=(16, 6))
            tk.Label(row, text=title, bg=C["bg"]).pack(side="left")
            self.w._settings_sections.add(str(row))

        def card(title, sub):
            box = tk.Frame(parent, bg=C["surface"])
            box.pack(fill="x", padx=20, pady=4)
            tk.Label(box, text=title, bg=C["surface"]).pack(anchor="w")
            tk.Label(box, text=sub, bg=C["surface"]).pack(anchor="w")
            return box

        section("MICROPHONE")
        self.mic = card("Test Mic", "Check the microphone is picking you up")
        section("DICTATION")
        self.punct = card("Sentence Endings", "Full stop on the end")
        self.snips = card("Snippets", "Say a phrase, get a block of text")
        self.root.update_idletasks()
        self.w._index_settings_search()

    def _visible(self):
        return [str(c) for c in self.w._settings_cv.content.pack_slaves()]

    def test_index_covers_every_row(self):
        self.assertEqual(len(self.w._settings_rows), 5)
        self.assertEqual(sum(1 for r in self.w._settings_rows if r["is_section"]), 2)

    def test_query_hides_non_matches(self):
        self.w._apply_settings_search("snippet")
        vis = self._visible()
        self.assertIn(str(self.snips), vis)
        self.assertNotIn(str(self.mic), vis)
        self.assertNotIn(str(self.punct), vis)

    def test_matching_card_keeps_its_section_header(self):
        self.w._apply_settings_search("snippet")
        headers = [r for r in self.w._settings_rows
                   if r["is_section"] and r["show"]]
        self.assertEqual(len(headers), 1)
        self.assertIn("dictation", headers[0]["text"])

    def test_section_name_matches_everything_under_it(self):
        self.w._apply_settings_search("dictation")
        vis = self._visible()
        self.assertIn(str(self.punct), vis)
        self.assertIn(str(self.snips), vis)
        self.assertNotIn(str(self.mic), vis)

    def test_subtext_is_searchable_not_just_the_title(self):
        self.w._apply_settings_search("picking you up")
        self.assertIn(str(self.mic), self._visible())

    def test_clearing_restores_original_order_and_padding(self):
        before = [(str(c), c.pack_info().get("pady"))
                  for c in self.w._settings_cv.content.pack_slaves()]
        self.w._apply_settings_search("snippet")
        self.w._apply_settings_search("")
        after = [(str(c), c.pack_info().get("pady"))
                 for c in self.w._settings_cv.content.pack_slaves()]
        self.assertEqual(before, after)

    def test_no_match_shows_the_empty_state(self):
        self.w._apply_settings_search("zzzznothing")
        self.assertIsNotNone(getattr(self.w, "_settings_empty", None))
        self.assertIn("zzzznothing", self.w._settings_empty.cget("text"))
        self.w._apply_settings_search("")
        self.assertEqual(self.w._settings_empty.winfo_manager(), "")

    def test_repeated_query_is_a_no_op(self):
        self.w._apply_settings_search("snippet")
        first = self._visible()
        self.w._apply_settings_search("snippet")
        self.assertEqual(first, self._visible())


class SourceContractTests(unittest.TestCase):
    """The real builder must create the bar and take the index — a filter with
    no index silently does nothing."""

    def setUp(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "app_window.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("    def _build_settings_tab(")
        self.body = src[start:src.index("    # ── Settings search")]

    def test_search_bar_is_built(self):
        self.assertIn("_apply_settings_search", self.body)
        self.assertIn("self._search_bar(", self.body)

    def test_index_is_taken_after_the_page_is_built(self):
        self.assertIn("self._index_settings_search()", self.body)
        self.assertLess(self.body.index("self._search_bar("),
                        self.body.index("self._index_settings_search()"))

    def test_search_is_packed_above_the_scroll_area(self):
        # Packed before the ScrollPane, so it takes the top strip and does not
        # scroll away with the content.
        self.assertLess(self.body.index("self._search_bar("),
                        self.body.index('self._settings_cv.pack(side="left"'))

    def test_every_section_registers_itself(self):
        self.assertIn("self._settings_sections.add(str(row))", self.body)


if __name__ == "__main__":
    unittest.main()
