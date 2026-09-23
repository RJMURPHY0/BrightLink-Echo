"""Settings and Learning card copy, and the order the sections read in.

Ryan's standing rule across all his software: one short line under a heading,
saying what the setting means when it is ON. No paragraph explaining the
mechanism, no bracketed exceptions, no restating what the control already
shows. He has corrected this repeatedly, so it is pinned here — a long
description fails in CI rather than in a screenshot weeks later.

The section ORDER is pinned for the same reason. "Dictation" had grown to
twelve cards covering two unrelated concerns (how the text comes out, and
where the pill sits on screen); splitting them is the change most likely to
be undone by accident.
"""

import inspect
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_window import AppWindow  # noqa: E402

# Long enough for a real sentence, short enough to refuse a paragraph. The
# longest line that currently ships is ~70 characters.
_MAX_DESC = 90


def _strip_comments(src):
    """Drop whole-line comments.

    These tests assert on what the app SAYS and DOES, and the code explaining
    why a phrase was removed necessarily quotes that phrase. Without this, a
    comment recording "the card used to claim X" fails the test asserting the
    card no longer claims X.
    """
    return "\n".join(l for l in src.split("\n")
                     if not l.lstrip().startswith("#"))


def _settings_src():
    return _strip_comments(inspect.getsource(AppWindow._build_settings_tab))


def _learning_src():
    return _strip_comments(
        inspect.getsource(AppWindow._build_learning_tab)
        + inspect.getsource(AppWindow._build_voice_training))


def _toggle_descriptions(src):
    """(title, description) for every _toggle_card / _link_card in `src`.

    Reads the call's string arguments as Python literals so implicit
    concatenation across lines is joined exactly as the app sees it.
    """
    found = []
    pattern = re.compile(
        r"_(?:toggle|link)_card\(\s*(?P<args>.*?)\)\s*$",
        re.DOTALL | re.MULTILINE)
    for call in pattern.finditer(src):
        args = call.group("args")
        # Every string literal in the call, in order.
        strings = re.findall(r'((?:"(?:[^"\\]|\\.)*"\s*)+)', args)
        literals = []
        for chunk in strings:
            try:
                literals.append(eval(chunk))            # noqa: S307 - test-only
            except Exception:
                literals.append("")
        # _toggle_card(parent?, key, title, subtext, ...) — the title is the
        # literal followed by the longest one (the description).
        if len(literals) >= 3:
            found.append((literals[1], literals[2]))
    return found


class CopyLengthTests(unittest.TestCase):

    def _check(self, src, where, minimum=4):
        rows = _toggle_descriptions(src)
        self.assertGreaterEqual(len(rows), minimum,
                                f"parsed too few cards in {where}")
        for title, desc in rows:
            with self.subTest(card=title):
                self.assertLessEqual(
                    len(desc), _MAX_DESC,
                    f"{where} card {title!r} has a {len(desc)}-character "
                    f"description; one short line is the rule:\n  {desc!r}")

    def test_settings_card_copy_is_one_short_line(self):
        self._check(_settings_src(), "Settings", minimum=12)

    def test_learning_card_copy_is_one_short_line(self):
        # Four helper-built cards; Voice Training is hand-built and checked
        # separately below.
        self._check(_learning_src(), "Learning", minimum=4)

    def test_the_voice_training_line_is_short_too(self):
        # Hand-built, so the _toggle_card parser above never sees it. It was
        # the longest description in the app: a five-line paragraph about
        # where the audio goes. The privacy fact still shows — the status line
        # under the card states it in both states.
        src = _learning_src()
        desc = re.search(r'_vt_desc_text = ("(?:[^"\\]|\\.)*")', src)
        self.assertIsNotNone(desc, "voice-training description not found")
        text = eval(desc.group(1))                       # noqa: S307 - test-only
        self.assertLessEqual(len(text), _MAX_DESC, text)
        self.assertNotIn("never uploaded", text)

    def test_no_card_spells_out_a_bracketed_exception(self):
        # "(never breaks mid-sentence thinking pauses)", "(it still appears if
        # injection fails)" — mechanism notes the user did not ask for.
        for where, src in (("Settings", _settings_src()),
                           ("Learning", _learning_src())):
            for title, desc in _toggle_descriptions(src):
                with self.subTest(card=f"{where}:{title}"):
                    self.assertNotRegex(
                        desc, r"\([^)]{25,}\)",
                        f"{title!r} explains an exception in brackets")


class SoundCopyTests(unittest.TestCase):

    def test_the_beep_copy_no_longer_claims_a_third_cue(self):
        # v1.6.51 made transcription_complete SILENT — two cues per dictation,
        # not three. The card had claimed a beep "when transcription finishes"
        # ever since, which is simply untrue.
        src = _settings_src()
        self.assertNotIn("transcription finishes", src)
        self.assertIn("A beep when recording starts and stops.", src)


class SectionOrderTests(unittest.TestCase):

    def _sections(self):
        src = _settings_src()
        return re.findall(r'_section\(\s*"[a-z]+"\s*,\s*"([^"]+)"\s*\)', src)

    def test_sections_read_in_the_intended_order(self):
        self.assertEqual(
            ["Microphone", "Dictation", "Live Typing", "Popup", "Sounds",
             "Account"],
            self._sections())

    def test_updates_is_still_the_first_thing_on_the_page(self):
        # Ryan's explicit call: Updates keeps the top of Settings. It is a
        # card, not a _section(), so it is checked by position instead.
        src = _settings_src()
        self.assertLess(src.index('text="Updates"'),
                        src.index('_section("mic", "Microphone")'))

    def test_the_popup_cards_left_dictation(self):
        src = _settings_src()
        popup_at = src.index('_section("wand", "Popup")')
        for key in ("show_popup", "show_pill_arrows", "badge_dismiss_on_key",
                    "hide_popup_in_screenshots"):
            with self.subTest(card=key):
                self.assertGreater(
                    src.index(f'"{key}"'), popup_at,
                    f"{key} is still above the Popup heading")

    def test_the_text_cards_stayed_in_dictation(self):
        src = _settings_src()
        dictation_at = src.index('_section("book", "Dictation")')
        live_at = src.index('_section("keyboard", "Live Typing")')
        for key in ("auto_paragraphs", "auto_lists", "email_format",
                    "trailing_space", "auto_enter", "copy_to_clipboard"):
            with self.subTest(card=key):
                pos = src.index(f'"{key}"')
                self.assertTrue(
                    dictation_at < pos < live_at,
                    f"{key} is no longer inside the Dictation section")


class SaveButtonTests(unittest.TestCase):

    def test_the_page_has_no_save_button(self):
        # The mic dropdown was the only control that waited for it; every
        # toggle has always applied on touch. app.py applies input_device
        # fully live, so the button asked the user to save one setting out of
        # thirty and said nothing about the rest.
        src = _settings_src()
        self.assertNotIn("Save Settings", src)
        self.assertNotIn("save_btn", src)

    def test_the_mic_applies_on_selection(self):
        src = _settings_src()
        self.assertIn('mic_var.trace_add("write", _apply_mic)', src)
        self.assertIn('self._on_settings_change("input_device", value)', src)

    def test_the_mic_never_applies_while_the_menu_is_still_filling(self):
        # _populate_mic_menu writes to mic_var itself. Applying those writes
        # would save a device the user never chose — and a pinned mic that has
        # since been unplugged would silently rewrite the config to auto.
        src = _settings_src()
        self.assertIn("if not self._mic_menu_ready:", src)
        self.assertIn("self._mic_menu_ready = True", src)


class LiveMicApplyTests(unittest.TestCase):
    """The mic dropdown, built for real.

    The source checks above say the wiring exists; these say it behaves. The
    dangerous half is the SILENT one: _populate_mic_menu writes to the var
    itself, and those writes must not reach _on_settings_change or a user who
    only opened Settings would have their config rewritten.
    """

    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        try:
            cls.root = tk.Tk()
        except Exception as e:                       # no window station (CI)
            raise unittest.SkipTest(f"Tk unavailable: {e}")
        cls.root.geometry("440x680")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        import tkinter as tk
        import types
        from app_window import C
        defaults = dict(end_punctuation="smart", popup_height="low",
                        input_device="", sound_feedback=True)

        class FakeConfig:
            def __getattr__(self, n):
                return defaults.get(n, False)

            def save_async(self):
                pass

        self.applied = []
        w = AppWindow.__new__(AppWindow)
        w._root = self.root
        w._config = FakeConfig()
        w._auth = types.SimpleNamespace(user_email="a@b.com")
        w._db = None
        w._lib = {}
        w._lib_count_labels = {}
        w._search_catalogue = []
        w._setting_pills = {}
        w._setting_vars = {}
        w._recorder = None
        w._version = "test"
        w._voice_trainer = None
        w._get_input_devices = lambda: []
        w._atomic_ui = lambda fn: fn()
        w._ui_after = lambda ms, fn: fn()
        w._scrollbar_command = lambda pane, *a: None
        w._on_settings_change = lambda k, v: self.applied.append((k, v))
        w._surface_btn = AppWindow._surface_btn.__get__(w)
        self.w = w
        self.host = tk.Frame(self.root, bg=C["bg"])
        self.host.pack(fill="both", expand=True)
        self.addCleanup(self.host.destroy)
        w._build_settings_tab(self.host)
        self.root.update_idletasks()
        self.root.update()

    def _mic_var(self):
        """The Dropdown in the mic card owns the var the trace watches."""
        import tkinter as tk
        from app_window import Dropdown
        found = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, Dropdown):
                    found.append(child._var)
                walk(child)

        walk(self.host)
        self.assertTrue(found, "no Dropdown found on the settings page")
        return found[0]

    def test_building_the_page_saves_nothing(self):
        # Opening Settings is not a change. _populate_mic_menu sets the var
        # while filling the list, and applying that would persist a device the
        # user never chose.
        self.assertEqual([], [k for k, _ in self.applied if k == "input_device"])

    def test_choosing_a_device_applies_it_immediately(self):
        var = self._mic_var()
        var.set("Some USB Microphone")
        self.root.update_idletasks()
        self.assertIn(("input_device", "Some USB Microphone"), self.applied)

    def test_auto_detect_is_saved_as_auto_whatever_its_label_says(self):
        # The label carries the resolved device, e.g. "Auto-detect (Array…)".
        var = self._mic_var()
        var.set("Some USB Microphone")
        self.root.update_idletasks()
        var.set("Auto-detect (Microphone Array)")
        self.root.update_idletasks()
        self.assertEqual(("input_device", "auto"), self.applied[-1])

    def test_relabelling_auto_detect_is_not_a_change(self):
        var = self._mic_var()
        var.set("Auto-detect (Headset)")
        self.root.update_idletasks()
        before = len(self.applied)
        var.set("Auto-detect (Webcam)")        # same value: still "auto"
        self.root.update_idletasks()
        self.assertEqual(before, len(self.applied))


if __name__ == "__main__":
    unittest.main()
