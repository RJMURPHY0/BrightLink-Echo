"""A refined result keeps the EXACT spacing the user had.

Reported with an Outlook email: three blank lines before the last paragraph
came back as one after a refine. The model normalises whitespace however the
prompt is worded, so restore_spacing() re-imposes the original layout. It may
only ever change whitespace, never a word, and must stand back when the
result is a genuine restructure or the Ask is about the layout."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_refiner
from ai_refiner import restore_spacing


ORIGINAL = (
    "Hi Jason,\n\n"
    "I have just seen this never sent from yesterday, but this is the link "
    "to the laptop.\n\n"
    "Laptop - https://www.currys.co.uk/products/laptop.html\n\n\n\n"
    "Ans then the Trade is this much which could be worth doing at some point"
)
REFINED = (
    "Hi Jason,\n\n"
    "I just saw this email from yesterday that was never sent. Here is the "
    "link to the laptop.\n\n"
    "Laptop - https://www.currys.co.uk/products/laptop.html\n\n"
    "The trade-in value is this much, which might be worth doing at some point."
)


def _words(s):
    return s.split()


class RestoreSpacingTests(unittest.TestCase):
    def test_reported_email_keeps_its_big_gap(self):
        out = restore_spacing(ORIGINAL, REFINED)
        self.assertIn(".html\n\n\n\nThe trade-in", out)
        self.assertTrue(out.startswith("Hi Jason,\n\nI just saw"))

    def test_only_whitespace_changes(self):
        out = restore_spacing(ORIGINAL, REFINED)
        self.assertEqual(_words(out), _words(REFINED))

    def test_crlf_selection_round_trips(self):
        orig = ORIGINAL.replace("\n", "\r\n")
        out = restore_spacing(orig, REFINED)
        self.assertIn(".html\r\n\r\n\r\n\r\nThe trade-in", out)
        self.assertNotIn("\r\r", out)
        self.assertEqual(_words(out), _words(REFINED))

    def test_leading_and_trailing_newlines_kept(self):
        out = restore_spacing("\nHi Jo,\n\nthanks\n\n", "Hi Jo,\n\nThanks.")
        self.assertEqual(out, "\nHi Jo,\n\nThanks.\n\n")

    def test_indent_kept(self):
        out = restore_spacing("Items:\n    first one\n    second one",
                              "Items:\nFirst one.\nSecond one.")
        self.assertEqual(out, "Items:\n    First one.\n    Second one.")

    def test_merged_lines_keep_paragraph_gaps(self):
        orig = "Hi Jo,\n\nline one\nline two\n\n\n\nBye"
        res = "Hi Jo,\n\nLine one, line two.\n\nBye."
        out = restore_spacing(orig, res)
        self.assertEqual(out, "Hi Jo,\n\nLine one, line two.\n\n\n\nBye.")

    def test_restructure_left_alone(self):
        orig = "Hi Jo,\n\nthanks for this\n\nKind regards,\nRyan"
        res = "Hi Jo, thanks for this. Kind regards, Ryan"
        self.assertEqual(restore_spacing(orig, res), res)

    def test_single_line_untouched(self):
        self.assertEqual(restore_spacing("hello world ", "Hello world."),
                         "Hello world.")

    def test_empty_inputs(self):
        self.assertEqual(restore_spacing("", "x"), "x")
        self.assertEqual(restore_spacing("a\nb", ""), "")


class _FakeRefiner(ai_refiner.AIRefiner):
    """refine() with the network swapped for a canned reply."""

    def __init__(self, reply):
        super().__init__(openrouter_api_key="test-key")
        self.reply = reply

    def _refine_via_openrouter(self, text, prompt, mode, system=""):
        return self.reply


class RefineWiringTests(unittest.TestCase):
    def test_custom_ask_restores_spacing(self):
        out = _FakeRefiner(REFINED).refine(
            ORIGINAL, custom_prompt="Make this better. Return only the "
                                    "rewritten text, nothing else.")
        self.assertIn(".html\n\n\n\nThe trade-in", out)

    def test_fix_all_restores_spacing(self):
        out = _FakeRefiner(REFINED).refine(ORIGINAL, mode="punctuation")
        self.assertIn(".html\n\n\n\nThe trade-in", out)

    def test_restyle_modes_restore_spacing(self):
        for mode in ("formal", "casual", "concise", "email"):
            out = _FakeRefiner(REFINED).refine(ORIGINAL, mode=mode)
            self.assertIn(".html\n\n\n\nThe trade-in", out, mode)

    def test_layout_ask_is_obeyed(self):
        out = _FakeRefiner(REFINED).refine(
            ORIGINAL, custom_prompt="Remove the extra blank lines.")
        self.assertEqual(out, REFINED)


if __name__ == "__main__":
    unittest.main()
