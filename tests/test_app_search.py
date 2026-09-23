"""Universal-search matching, question detection and the Ask AI help prompt."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_search


CATALOGUE = [
    {"kind": "page", "title": "Home",
     "subtext": "Your impact, time saved and streak.",
     "keywords": "impact stats", "target": ("tab", "home")},
    {"kind": "page", "title": "History",
     "subtext": "Every past dictation with audio playback.",
     "keywords": "past transcripts audio", "target": ("tab", "history")},
    {"kind": "page", "title": "Custom Vocabulary",
     "subtext": "Names and jargon the app should get right.",
     "keywords": "vocabulary words", "target": ("tab", "vocabulary")},
    {"kind": "setting", "title": "Trim Silence",
     "subtext": "Skip storing chunks that transcribed to nothing.",
     "keywords": "trim silence", "location": "Settings",
     "target": ("setting", "settings", "Trim Silence")},
    {"kind": "setting", "title": "Format Emails",
     "subtext": "Lay a dictation out as an email in Outlook or Gmail.",
     "keywords": "email format", "location": "Settings",
     "target": ("setting", "settings", "Format Emails")},
    {"kind": "setting", "title": "Microphone",
     "subtext": "Choose which microphone to record from.",
     "keywords": "", "location": "Settings",
     "target": ("setting", "settings", "Microphone")},
]


class MatchTests(unittest.TestCase):
    def _titles(self, q, **kw):
        return [e["title"] for e in app_search.match_entries(q, CATALOGUE, **kw)]

    def test_empty_query_returns_nothing(self):
        self.assertEqual(app_search.match_entries("", CATALOGUE), [])
        self.assertEqual(app_search.match_entries("   ", CATALOGUE), [])

    def test_title_match_ranks_first(self):
        self.assertEqual(self._titles("history")[0], "History")

    def test_page_beats_setting_of_equal_name(self):
        # "vocabulary" is a page title and a setting keyword; the page wins.
        self.assertEqual(self._titles("vocabulary")[0], "Custom Vocabulary")

    def test_all_words_required(self):
        # "trim email" shares no single card, so nothing matches.
        self.assertEqual(self._titles("trim email"), [])

    def test_multiword_title(self):
        self.assertIn("Format Emails", self._titles("format email"))

    def test_keyword_only_match(self):
        # "jargon" is only in the subtext of Custom Vocabulary.
        self.assertEqual(self._titles("jargon"), ["Custom Vocabulary"])

    def test_limit_respected(self):
        self.assertLessEqual(len(app_search.match_entries("a", CATALOGUE,
                                                          limit=2)), 2)

    def test_no_match(self):
        self.assertEqual(self._titles("bluetooth pairing wizard"), [])


class QuestionTests(unittest.TestCase):
    def test_question_mark(self):
        self.assertTrue(app_search.looks_like_question("trim silence?"))

    def test_question_word(self):
        for q in ("how do I change my hotkey", "what does trim silence do",
                  "can I dictate offline"):
            self.assertTrue(app_search.looks_like_question(q), q)

    def test_plain_term_is_not_a_question(self):
        for q in ("trim silence", "microphone", "history", "format emails"):
            self.assertFalse(app_search.looks_like_question(q), q)

    def test_long_phrase_reads_as_a_question(self):
        self.assertTrue(app_search.looks_like_question(
            "microphone keeps switching to the wrong device"))

    def test_empty(self):
        self.assertFalse(app_search.looks_like_question(""))


class HelpPromptTests(unittest.TestCase):
    def test_lists_pages_and_settings(self):
        p = app_search.help_prompt(CATALOGUE)
        self.assertIn('Page "History"', p)
        self.assertIn('Setting "Trim Silence" (in Settings)', p)
        # App-scoped and plain-prose instructions are present.
        self.assertIn("BrightLink Echo", p)
        self.assertIn("plain prose", p.lower())

    def test_skips_untitled(self):
        p = app_search.help_prompt([{"kind": "page", "title": "",
                                     "subtext": "x"}])
        self.assertNotIn('Page ""', p)


class LinkedEntriesTests(unittest.TestCase):
    def test_finds_named_entry(self):
        ans = "Turn on Format Emails in Settings to lay it out."
        hits = app_search.linked_entries(ans, CATALOGUE)
        self.assertEqual([e["title"] for e in hits], ["Format Emails"])

    def test_none_when_unnamed(self):
        self.assertEqual(
            app_search.linked_entries("Just speak and it types.", CATALOGUE),
            [])

    def test_limit(self):
        ans = "Trim Silence, Format Emails, Microphone and History all help."
        self.assertLessEqual(
            len(app_search.linked_entries(ans, CATALOGUE, limit=2)), 2)


if __name__ == "__main__":
    unittest.main()
