"""History "Fix words": edit a dictation, press Enter, Echo learns the fix."""

import inspect
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vocab_store  # noqa: E402
from app_window import AppWindow  # noqa: E402
from text_expansion import apply_vocabulary  # noqa: E402

_ROOT = None


def tearDownModule():
    global _ROOT
    if _ROOT is not None:
        try:
            _ROOT.destroy()
        except Exception:
            pass
        _ROOT = None


def _root():
    global _ROOT
    import tkinter as tk
    if _ROOT is not None and _ROOT.winfo_exists():
        return _ROOT
    try:
        _ROOT = tk.Tk()
    except Exception as e:                          # no window station (CI)
        raise unittest.SkipTest(f"Tk unavailable: {e}")
    _ROOT.geometry("440x620")
    return _ROOT


class FakeConfig:
    def __init__(self):
        self.vocabulary, self.snippets = {}, {}

    def save_async(self):
        pass


class FixWordsTests(unittest.TestCase):
    EMAIL = "ryan@x.com"

    def setUp(self):
        import tkinter as tk
        from app_window import C
        root = _root()
        self.updates, self.toasts = [], []
        self.item = {"transcribed_text": "Remind me to email UNICEF after lunch.",
                     "created_at": "2026-10-12T09:00:00+00:00"}
        w = AppWindow.__new__(AppWindow)
        w._root = root
        w._dash_frame = tk.Frame(root, bg=C["bg"])
        w._dash_frame.pack(fill="both", expand=True)
        self.addCleanup(w._dash_frame.destroy)
        w._atomic_ui = lambda fn: fn()
        w._auth = types.SimpleNamespace(user_email=self.EMAIL)
        w._config = FakeConfig()
        w._db = types.SimpleNamespace(
            update_transcription=lambda item, text: self.updates.append(text))
        w._hist_all = [self.item]
        w._hist_expanded_key = w._history_item_key(self.item)
        w._hist_confirm_key = None
        w._render_history = lambda: None
        w.refresh_libraries = lambda: None
        w.show_toast = lambda msg, *a, **k: self.toasts.append((msg, None))
        w.show_action_toast = (lambda msg, button, on_click, *a, **k:
                               self.toasts.append((msg, on_click)))
        self.w = w
        self.addCleanup(w._close_word_fix)

    def _fix(self, new_text):
        self.w._open_word_fix({"item": self.item})
        box = self.w._wf["box"]
        box.delete("1.0", "end")
        box.insert("1.0", new_text)
        self._press(box, "<Return>")            # Enter saves

    def _press(self, widget, sequence):
        # Tk only delivers a generated key to a mapped, focused widget.
        widget.update()
        widget.focus_force()
        widget.update()
        widget.event_generate(sequence, when="now")

    def vocab(self):
        return vocab_store.load(self.w._config, "vocabulary", self.EMAIL)

    def test_enter_fixes_the_row_and_learns_the_mishearing(self):
        self._fix("Remind me to email Uniserve after lunch.")
        self.assertEqual(["Remind me to email Uniserve after lunch."], self.updates)
        self.assertEqual("Remind me to email Uniserve after lunch.",
                         self.item["transcribed_text"])
        self.assertEqual([("Uniserve", ["UNICEF"])],
                         [(e["term"], e["sounds_like"]) for e in self.vocab()])
        self.assertEqual("Learned: UNICEF → Uniserve", self.toasts[0][0])
        # The next dictation that mishears it comes out right.
        self.assertEqual("ring Uniserve", apply_vocabulary("ring UNICEF", self.vocab()))
        self.assertIsNone(self.w._wf)            # the editor closed

    def test_undo_puts_back_the_text_and_the_vocabulary(self):
        self._fix("Remind me to email Uniserve after lunch.")
        self.toasts[0][1]()                      # press Undo
        self.assertEqual([], self.vocab())
        self.assertEqual("Remind me to email UNICEF after lunch.",
                         self.item["transcribed_text"])

    def test_a_changed_mind_fixes_the_row_and_learns_nothing(self):
        self._fix("Remind me to email Jason after lunch.")
        self.assertEqual([], self.vocab())
        self.assertEqual("Remind me to email Jason after lunch.",
                         self.item["transcribed_text"])
        self.assertEqual("Fixed. Nothing to learn from that change.", self.toasts[0][0])

    def test_no_change_does_nothing(self):
        self._fix("Remind me to email UNICEF after lunch.")
        self.assertEqual(([], []), (self.updates, self.toasts))

    def test_escape_cancels(self):
        self.w._open_word_fix({"item": self.item})
        self._press(self.w._wf["box"], "<Escape>")
        self.assertIsNone(self.w._wf)
        self.assertEqual([], self.updates)

    def test_the_history_row_offers_the_fix(self):
        src = inspect.getsource(AppWindow._draw_history_extras)
        self.assertIn('"fix"', src)
        self.assertIn('elif action == "fix"', inspect.getsource(AppWindow._on_history_click))


if __name__ == "__main__":
    unittest.main()
