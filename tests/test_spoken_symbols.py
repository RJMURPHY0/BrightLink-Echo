"""Spoken symbol commands — addresses, percentages, quotes.

The reported wants were two real dictations that came back as prose:

    "Ryan dot murphy at ftc dash ss dot com"  ->  ryan.murphy@ftc-ss.com
    "of fifty four percent"                   ->  of 54%

"dot", "dash" and "at" are ordinary English words, so these tests pin BOTH
directions. The false-negative cases (an address survives as prose) are the
reported want; the false-positive cases are the worse regression, because the
rules rewrite words the user genuinely said. The corpus test at the end fails
if the rules ever touch a real stored transcript that contains no address and
no percentage.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoken_commands import apply_spoken_commands as sc


class AddressTests(unittest.TestCase):
    """A run of word/separator tokens ending in a TLD or file extension."""

    def test_the_reported_email(self):
        self.assertEqual(sc("Ryan dot murphy at ftc dash ss dot com"),
                         "ryan.murphy@ftc-ss.com")

    def test_email_inside_a_sentence(self):
        self.assertEqual(
            sc("Send it to ryan dot murphy at ftc dash ss dot com today"),
            "Send it to ryan.murphy@ftc-ss.com today")

    def test_prose_at_before_the_address(self):
        # The first "at" is prose; the address begins after it.
        self.assertEqual(sc("email me at ryan dot murphy at example dot com"),
                         "email me at ryan.murphy@example.com")

    def test_bare_domain(self):
        self.assertEqual(sc("go to ftc dash ss dot com"), "go to ftc-ss.com")

    def test_multi_label_domain(self):
        self.assertEqual(sc("see example dot co dot uk"), "see example.co.uk")

    def test_underscore_local_part(self):
        self.assertEqual(sc("ryan underscore murphy at example dot org"),
                         "ryan_murphy@example.org")

    def test_filename(self):
        self.assertEqual(sc("open the report dot pdf"), "open the report.pdf")

    def test_trailing_sentence_stop_is_kept(self):
        self.assertEqual(sc("Mail ryan at example dot com."),
                         "Mail ryan@example.com.")


class AddressFalsePositiveTests(unittest.TestCase):
    """Ordinary prose containing "at", "dot" or "dash" must survive intact."""

    def test_plain_at(self):
        for s in ("I looked at the numbers",
                  "meet me at the office",
                  "have a look at this",
                  "back at it again"):
            self.assertEqual(sc(s), s)

    def test_verb_before_at_is_not_an_email(self):
        # "looked" is prose, so the "at" stays and only the filename collapses.
        self.assertEqual(sc("I looked at report dot pdf"),
                         "I looked at report.pdf")

    def test_single_letter_label_is_not_a_domain(self):
        # "in" and "it" are not treated as TLDs, and a one-character label is
        # refused outright — "put a dot in the box" must never become "a.in".
        for s in ("put a dot in the box",
                  "we looked at it",
                  "leave it to me"):
            self.assertEqual(sc(s), s)

    def test_dot_without_a_tld(self):
        self.assertEqual(sc("version one dot two"), "version one dot two")

    def test_dash_alone_is_untouched(self):
        s = "a dash of colour"
        self.assertEqual(sc(s), s)


class PercentTests(unittest.TestCase):
    def test_the_reported_example(self):
        self.assertEqual(sc("a rise of fifty four percent"), "a rise of 54%")

    def test_hyphenated_number(self):
        self.assertEqual(sc("fifty-four percent"), "54%")

    def test_digits_already(self):
        self.assertEqual(sc("up 54 percent this year"), "up 54% this year")

    def test_hundred(self):
        self.assertEqual(sc("one hundred percent sure"), "100% sure")

    def test_bare_scale_word_is_prose(self):
        # "a hundred percent" must not become the nonsense "a 100%".
        s = "a hundred percent sure"
        self.assertEqual(sc(s), s)

    def test_percentage_is_not_a_symbol(self):
        s = "the percentage of users"
        self.assertEqual(sc(s), s)

    def test_currency_words(self):
        self.assertEqual(sc("dollar sign fifty"), "$50")


class QuoteTests(unittest.TestCase):
    def test_open_and_close(self):
        self.assertEqual(sc("open quote hello close quote"), '"hello"')

    def test_unquote(self):
        self.assertEqual(sc("open quote hello unquote"), '"hello"')

    def test_apostrophe(self):
        self.assertEqual(sc("Ryan apostrophe s report"), "Ryan's report")

    def test_exclamation(self):
        self.assertEqual(sc("well done exclamation mark"), "well done!")

    def test_bare_quotation_marks_stay_prose(self):
        # Caught in the real corpus: "research of the other things like
        # quotation marks, dollar signs" must not sprout a stray quote.
        s = "things like quotation marks, dollar signs and the rest"
        self.assertEqual(sc(s), s)


class ExistingBehaviourTests(unittest.TestCase):
    """The rules that shipped before must be unchanged."""

    def test_slash(self):
        self.assertEqual(sc("slash settings"), "/settings")

    def test_underscore(self):
        self.assertEqual(sc("ryan underscore murphy"), "ryan_murphy")

    def test_hashtag(self):
        self.assertEqual(sc("hashtag safety first"), "#safety first")

    def test_brackets(self):
        self.assertEqual(sc("open bracket see attached close bracket"),
                         "(see attached)")

    def test_punctuation_words_are_never_converted(self):
        for s in ("over a period of time",
                  "a question mark over the plan",
                  "a new line of products",
                  "look at sign four"):
            self.assertEqual(sc(s), s)

    def test_newlines_survive(self):
        src = "line one\n\nline two slash three"
        self.assertEqual(sc(src), "line one\n\nline two/three")


class CorpusRegressionTests(unittest.TestCase):
    """Run every real stored transcript through the converter. A transcript
    with no address shape and no percentage must come back byte-identical —
    anything else means a rule has drifted into ordinary prose."""

    def _load(self):
        path = os.path.join(os.environ.get("APPDATA", ""), "FTC Whisper",
                            "history.json")
        if not os.path.exists(path):
            self.skipTest("no local history.json corpus on this machine")
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        return [t for t in (r.get("transcribed_text", "") for r in rows)
                if t and t.strip()]

    def test_plain_prose_is_never_rewritten(self):
        import re
        changed = []
        for text in self._load():
            out = sc(text)
            if out == text:
                continue
            # A change is only allowed where the source carries the shape the
            # rules key off: a symbol name, an address run, or a percentage.
            if re.search(r"\b(slash|underscore|hyphen|hash ?tag|tilde|ampersand"
                         r"|asterisk|caret|semicolon|apostrophe|quote|bracket"
                         r"|brace|paren|percent|dollar sign|pound sign|euro sign"
                         r"|equals? sign|plus sign|pipe symbol|vertical bar"
                         r"|exclamation|quotation|back ?tick|less ?than sign"
                         r"|greater ?than sign|at symbol)\b", text, re.I):
                continue
            if re.search(r"\b\w+\s+(?:dot|dash|at)\s+\w+", text, re.I):
                continue
            changed.append((text, out))
        self.assertEqual(changed, [], f"{len(changed)} corpus rewrite(s) with "
                                      "no symbol, address or percentage in the source")


if __name__ == "__main__":
    unittest.main()
