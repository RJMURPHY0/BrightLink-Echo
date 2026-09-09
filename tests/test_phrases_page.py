"""The Phrases page, and the voice-training row that sent it here.

Ryan reported the voice-training card's button reading "Import my past" — the
label ran off the right edge of the card. Status and button shared one row and
between them wanted more width than a ~290px card has, so the button was
pushed off. The live test below measures both arrangements: the stacked one
fits, and the old side-by-side one does not, so a revert fails here rather
than in a screenshot three weeks later.
"""

import inspect
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import phrase_learning as pl  # noqa: E402
from app_window import AppWindow  # noqa: E402

_SHARED_ROOT = None


def _shared_root():
    global _SHARED_ROOT
    import tkinter as tk
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
    try:
        import ui_render
        ui_render.clear_cache()
    except Exception:
        pass
    if _SHARED_ROOT is not None:
        try:
            _SHARED_ROOT.destroy()
        except Exception:
            pass
        _SHARED_ROOT = None


class FakeConfig:
    learned_phrases = True

    def save_async(self):
        pass


class SourceInvariantTests(unittest.TestCase):

    def test_the_voice_status_and_button_are_on_separate_rows(self):
        src = inspect.getsource(AppWindow._build_settings_tab)
        block = src[src.index("vt_actions = tk.Frame"):
                    src.index("# ── Save button")]
        self.assertIn('self._voice_status.pack(fill="x")', block)
        self.assertIn("vt_btn_row", block)
        # The status may no longer claim the row the button needs.
        self.assertNotIn('self._voice_status.pack(side="left"', block)

    def test_the_page_scrolls_on_scrollpane_never_a_canvas(self):
        src = inspect.getsource(AppWindow._build_phrases_page)
        self.assertIn("ScrollPane(", src)
        self.assertNotIn("tk.Canvas(", src)

    def test_rendering_the_list_is_one_atomic_frame(self):
        self.assertIn("_atomic_ui", inspect.getsource(AppWindow._render_phrases))

    def test_the_page_is_registered_built_and_reachable(self):
        self.assertIn('"phrases": self._phrases_frame',
                      inspect.getsource(AppWindow._switch_dash_tab))
        self.assertIn("_build_phrases_page(self._phrases_frame)",
                      inspect.getsource(AppWindow._build_dashboard))
        self.assertIn('_link_card("phrases"',
                      inspect.getsource(AppWindow._build_settings_tab))

    def test_back_returns_to_settings(self):
        self.assertIn('_switch_dash_tab("settings")',
                      inspect.getsource(AppWindow._build_phrases_page))

    def test_the_page_is_not_in_the_tab_bar(self):
        src = inspect.getsource(AppWindow._build_dashboard)
        tab_bar = src.split("for name, label, glyph in")[1].split("]")[0]
        self.assertNotIn("phrases", tab_bar)

    def test_the_list_refreshes_on_arrival(self):
        # Phrases are learned in the background, so a list drawn on the last
        # visit is already stale.
        self.assertIn("_render_phrases()",
                      inspect.getsource(AppWindow._switch_dash_tab))

    def test_the_ui_uses_the_apps_store_not_a_second_one(self):
        # Two stores over one file means a phrase forgotten here comes back
        # from the copy still in memory.
        self.assertIn("_phrase_provider",
                      inspect.getsource(AppWindow._phrase_store))
        self.assertNotIn("PhraseStore(",
                         inspect.getsource(AppWindow._phrase_store))

    def test_forget_all_is_two_steps(self):
        src = inspect.getsource(AppWindow._phrases_forget_all)
        self.assertIn("confirm_all", src)


class VoiceCardLayoutTests(unittest.TestCase):
    """Live geometry, at the real window width."""

    @classmethod
    def setUpClass(cls):
        cls.root = _shared_root()

    def setUp(self):
        import tkinter as tk
        from app_window import C
        self.w = AppWindow.__new__(AppWindow)
        self.w._root = self.root
        self.host = tk.Frame(self.root, bg=C["bg"], width=440)
        self.host.pack(fill="both", expand=True)
        self.addCleanup(self.host.destroy)

    def _build(self, stacked):
        import tkinter as tk
        from app_window import C
        card = self.w._card(self.host, margin=(0, 4))
        status_text = "On. Snippets of your voice train FTC Transcribe."
        if stacked:
            row = tk.Frame(card, bg=C["surface"])
            row.pack(fill="x", pady=(8, 0))
            status = tk.Label(row, text=status_text, fg=C["subtext"],
                              bg=C["surface"], font=("Segoe UI", 8),
                              anchor="w", justify="left")
            status.pack(fill="x")
            self.w._autowrap(status)
            btn_row = tk.Frame(card, bg=C["surface"])
            btn_row.pack(fill="x", pady=(8, 0))
            btn = self.w._surface_btn(btn_row, "Import my past dictations",
                                      lambda: None)
            btn.pack(side="right")
        else:                                   # the shipped-broken arrangement
            row = tk.Frame(card, bg=C["surface"])
            row.pack(fill="x", pady=(8, 0))
            status = tk.Label(row, text=status_text, fg=C["subtext"],
                              bg=C["surface"], font=("Segoe UI", 8), anchor="w")
            status.pack(side="left", fill="x", expand=True)
            btn = self.w._surface_btn(row, "Import my past dictations",
                                      lambda: None)
            btn.pack(side="right")
        self.root.update_idletasks()
        self.root.update()
        return card, btn

    def test_the_button_fits_inside_the_card(self):
        card, btn = self._build(stacked=True)
        card_right = card.winfo_rootx() + card.winfo_width()
        btn_right = btn.winfo_rootx() + btn.winfo_reqwidth()
        self.assertLessEqual(
            btn_right, card_right,
            f"button overruns the card by {btn_right - card_right}px")

    def test_the_old_side_by_side_row_really_did_not_fit(self):
        # The control: without this, the test above could pass for a layout
        # that was never broken in the first place.
        card, btn = self._build(stacked=False)
        card_right = card.winfo_rootx() + card.winfo_width()
        btn_right = btn.winfo_rootx() + btn.winfo_reqwidth()
        self.assertGreater(btn_right, card_right)


class PhrasesPageRenderTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = _shared_root()

    def setUp(self):
        import tkinter as tk
        from app_window import C
        self.tmp = tempfile.mkdtemp()
        self.store = pl.PhraseStore("page@example.com", directory=self.tmp)
        self.w = AppWindow.__new__(AppWindow)
        self.w._root = self.root
        self.w._lib = {}
        self.w._config = FakeConfig()
        self.w.set_phrase_provider(lambda: self.store)
        self.frame = tk.Frame(self.root, bg=C["bg"])
        self.frame.pack(fill="both", expand=True)
        self.addCleanup(self.frame.destroy)

    def _learn(self, text, times):
        conf = [0.95] * len(list(pl._WORD_RE.finditer(text)))
        for _ in range(times):
            self.store.observe(text, conf)

    def _labels(self):
        out = []
        stack = [self.frame]
        while stack:
            w = stack.pop()
            try:
                t = w.cget("text")
                if isinstance(t, str) and t.strip():
                    out.append(t)
            except Exception:
                pass
            stack.extend(w.winfo_children())
        return out

    def test_an_empty_store_explains_itself(self):
        self.w._build_phrases_page(self.frame)
        self.root.update()
        self.assertIn("Nothing learned yet", self._labels())

    def test_a_learned_phrase_is_listed_with_its_count(self):
        self._learn("Open the Brightlink pipeline now.", pl.PROMOTE_COUNT)
        self.w._build_phrases_page(self.frame)
        self.root.update()
        labels = self._labels()
        self.assertIn("brightlink pipeline", labels)
        self.assertTrue(any(t.startswith("said ") for t in labels), labels)

    def test_forgetting_a_phrase_removes_it_from_the_list(self):
        self._learn("Open the Brightlink pipeline now.", pl.PROMOTE_COUNT)
        self.w._build_phrases_page(self.frame)
        self.root.update()
        self.w._phrases_forget("brightlink pipeline")
        self.root.update()
        self.assertNotIn("brightlink pipeline", self._labels())

    def test_searching_filters_the_list(self):
        self._learn("Open the Brightlink pipeline now.", pl.PROMOTE_COUNT)
        self._learn("Run the prospect intel report.", pl.PROMOTE_COUNT)
        self.w._build_phrases_page(self.frame)
        self.root.update()
        self.w._lib_state("phrases")["query"] = "prospect"
        self.w._render_phrases()
        self.root.update()
        labels = self._labels()
        self.assertIn("prospect intel", labels)
        self.assertNotIn("brightlink pipeline", labels)

    def test_the_page_survives_the_feature_being_off(self):
        self.w.set_phrase_provider(lambda: None)
        self.w._config.learned_phrases = False
        self.w._build_phrases_page(self.frame)
        self.root.update()
        self.assertIn("Learning is off", self._labels())


if __name__ == "__main__":
    unittest.main()
