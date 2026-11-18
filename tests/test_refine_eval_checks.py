"""The offline refine checker (tools/refine_eval/checks.py) flags what a user
would reject and passes what they would send. Both directions pinned, so a
prompt change is never scored by a checker that has drifted."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "refine_eval"))

import checks  # noqa: E402

CASE = {"id": "t", "text": "Hi Sarah,\n\nUm, the quote is £1,450 for the 14th of March, "
                           "on the M1 site, ref FTC-2291.\n\nCheers,\nRyan",
        "keep": ["Sarah", "£1,450", "14th of March", "M1", "FTC-2291", "Ryan"],
        "greeting": "Hi Sarah,", "signoff": ["Cheers,", "Ryan"]}
GOOD = "Hi Sarah,\n\nThe quote is £1,450 for the 14th of March, on the M1 site, ref FTC-2291.\n\nCheers,\nRyan"


class CheckerTests(unittest.TestCase):
    def test_a_faithful_polish_passes(self):
        r = checks.score(CASE, "formal", GOOD)
        self.assertTrue(r["pass"], r)

    def test_reformatted_date_and_dropped_name_fail_meaning(self):
        r = checks.score(CASE, "formal", GOOD.replace("14th of March", "14 March"))
        self.assertEqual(r["missing"], ["14th of March"])
        self.assertFalse(r["pass"])

    def test_invented_number_and_name_fail(self):
        r = checks.score(CASE, "formal", GOOD.replace("site,", "site with Tom on 3 days,"))
        self.assertIn("3", r["added_numbers"])
        self.assertIn("Tom", r["added_names"])
        self.assertFalse(r["meaning_ok"])

    def test_corporate_padding_and_dashes_fail_tone(self):
        bad = GOOD.replace("The quote", "I hope this email finds you well — the quote")
        r = checks.score(CASE, "formal", bad)
        self.assertTrue(r["fluff"])
        self.assertEqual(r["dashes"], 1)
        self.assertFalse(r["tone_ok"])

    def test_american_spelling_fails(self):
        r = checks.score(CASE, "formal", GOOD.replace("The quote", "To organize it, the quote"))
        self.assertEqual(r["us_spelling"], ["organize"])

    def test_changed_greeting_or_signoff_fails_layout(self):
        r = checks.score(CASE, "email", GOOD.replace("Hi Sarah", "Dear Sarah").replace("Cheers,", "Best regards,"))
        self.assertEqual(len(r["layout"]), 2)

    def test_hyphenated_compound_counts_as_kept(self):
        case = {"id": "h", "text": "the whole 3 year contract", "keep": ["3 year"]}
        self.assertEqual(checks.kept_items(case["keep"], "the whole 3-year contract"), [])

    def test_words_the_speaker_said_are_not_new_names(self):
        self.assertEqual(checks.added_names("ref FTC-2291 on the M1", "The ref is FTC-2291, on the M1."), [])

    def test_voice_retention(self):
        self.assertEqual(checks.voice_retention("send the grey samples", "send the grey samples"), 1.0)
        self.assertLess(checks.voice_retention("send the grey samples", "dispatch charcoal swatches"), 0.5)


if __name__ == "__main__":
    unittest.main()
