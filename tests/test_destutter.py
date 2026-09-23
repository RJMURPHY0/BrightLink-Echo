"""Stutter / false-start collapse.

The feature was asked for with a real example: "push all most rec recent
changes" should inject "push all most recent changes" — the aborted fragment
"rec" is dropped, the completed word "recent" kept.

These tests pin BOTH directions. The false-negative cases (a stutter survives)
are the reported want; the false-positive cases (real speech gets rewritten)
are the worse regression, because this code silently deletes words the user
genuinely said. The corpus test at the end fails if the rules ever rewrite real
dictation into a shape none of the two collapse rules explains.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import disfluency


class FalseStartTests(unittest.TestCase):
    """A short fragment immediately followed by the fuller word it aborted."""

    def test_the_reported_example(self):
        self.assertEqual(
            disfluency.destutter("push all most rec recent changes"),
            "push all most recent changes",
        )

    def test_reported_example_in_a_sentence(self):
        self.assertEqual(
            disfluency.destutter("Do this and then push almost rec recent changes to main."),
            "Do this and then push almost recent changes to main.",
        )

    def test_common_fragments(self):
        for src, want in [
            ("prob probably not", "probably not"),
            ("def definitely yes", "definitely yes"),
            ("the config configuration file", "the configuration file"),
            ("trans transcription is slow", "transcription is slow"),
            ("be able to re resize stuff", "be able to resize stuff"),
        ]:
            self.assertEqual(disfluency.destutter(src), want, src)

    def test_leading_capital_carries_to_the_kept_word(self):
        self.assertEqual(disfluency.destutter("Rec recent changes"), "Recent changes")

    def test_fragment_across_a_comma(self):
        self.assertEqual(disfluency.destutter("push rec, recent changes"),
                         "push recent changes")


class FunctionDoubleTests(unittest.TestCase):
    """An exact repeat of a never-validly-doubled function word."""

    def test_common_doubles(self):
        for src, want in [
            ("I I think we should go", "I think we should go"),
            ("the the file is here", "the file is here"),
            ("optimal usage for for this task", "optimal usage for this task"),
            ("right but it it then just", "right but it then just"),
            ("they actually do do something", "they actually do something"),
        ]:
            self.assertEqual(disfluency.destutter(src), want, src)

    def test_triple_collapses_to_one(self):
        self.assertEqual(disfluency.destutter("turn it on on on or off"),
                         "turn it on or off")

    def test_a_restart_capital_mid_sentence_is_lowered(self):
        # "restricted and And if": the engine capitalised the restart after the
        # pause, but the dropped copy shows the word is mid-sentence.
        self.assertEqual(disfluency.destutter("ones you restricted and And if I"),
                         "ones you restricted and if I")
        self.assertEqual(disfluency.destutter("make sure it's also a A thing"),
                         "make sure it's also a thing")

    def test_i_and_acronyms_keep_their_capitals(self):
        self.assertEqual(disfluency.destutter("so i I think"), "so I think")
        self.assertEqual(disfluency.destutter("then it IT said"), "then it IT said")

    def test_wider_never_doubled_words(self):
        # From real dictations (2026-09-21..23).
        for src, want in [
            ("have like if if you can", "have like if you can"),
            ("so it's it's it's much easier", "so it's much easier"),
            ("Yeah, just just just come up with", "Yeah, just come up with"),
            ("What what do you think", "What do you think"),
            ("it would be more more potentially", "it would be more potentially"),
            ("Can you also make make it so", "Can you also make it so"),
            ("an easy transition between between them", "an easy transition between them"),
            ("stuff that I've I've liked", "stuff that I've liked"),
            ("so yeah, maybe maybe leave it", "so yeah, maybe leave it"),
            ("because they’re they’re things", "because they’re things"),
        ]:
            self.assertEqual(disfluency.destutter(src), want, src)


class PhraseRestartTests(unittest.TestCase):
    """A 2-4 word unfinished phrase said twice in a row. All from real
    dictations."""

    def test_restarts_collapse(self):
        for src, want in [
            ("notes or something in the in the CRM", "notes or something in the CRM"),
            ("the thing to be to be like the side", "the thing to be like the side"),
            ("you know, it will it will basically tell you",
             "you know, it will basically tell you"),
            ("Bring that up to fill the fill the space.", "Bring that up to fill the space."),
            ("the home page? Does it does it like slowly change",
             "the home page? Does it like slowly change"),
            ("and then, like, if you're If you're working overtime",
             "and then, like, if you're working overtime"),
            ("I want to I want to go", "I want to go"),
            ("in the in the in the CRM", "in the CRM"),
        ]:
            self.assertEqual(disfluency.destutter(src), want, src)

    def test_a_restart_at_the_start_keeps_its_capital(self):
        self.assertEqual(disfluency.destutter("In the in the morning we go"),
                         "In the morning we go")

    def test_emphasis_and_idioms_survive(self):
        for s in ["I know, I know, it's late.", "come on, come on, hurry up",
                  "thank you thank you so much", "it went on and on and on",
                  "over and over and over again", "breathe in and out, in and out",
                  "you know you know", "It's fine, it's fine.", "do it, do it",
                  "one two one two testing", "much much better",
                  "hold on hold on", "For example. For example, if",
                  "Is it? Is it?", "blah blah blah", "the dot dot dot menu",
                  "yeah yeah and then"]:
            self.assertEqual(disfluency.destutter(s), s, s)


class NeverTouchTests(unittest.TestCase):
    """Real speech that merely resembles a stutter must be returned unchanged."""

    def test_a_word_that_prefixes_the_next_but_is_a_real_word(self):
        for s in ["the theory of everything", "does he help me",
                  "in industry today", "we website today", "part party time",
                  "so sophisticated"]:
            self.assertEqual(disfluency.destutter(s), s, s)

    def test_base_then_inflected_is_two_words(self):
        for s in ["I bought a car cars are expensive", "read reading is fun",
                  "book books on the shelf", "help helped him", "form former self"]:
            self.assertEqual(disfluency.destutter(s), s, s)

    def test_emphatic_and_grammatical_doubles_survive(self):
        for s in ["it was very very important", "no no that is fine",
                  "he had had enough", "I know that that report is late",
                  "really really good", "so so tired"]:
            self.assertEqual(disfluency.destutter(s), s, s)

    def test_sentence_boundary_is_never_crossed(self):
        self.assertEqual(disfluency.destutter("the cat. Cat food is here."),
                         "the cat. Cat food is here.")

    def test_content_word_double_is_not_collapsed(self):
        # Only function words are collapsed on an exact double; a repeated content
        # word may well be emphasis and is left alone.
        self.assertEqual(disfluency.destutter("recent recent thing"),
                         "recent recent thing")

    def test_short_and_empty_inputs(self):
        for s in ["", "hello", "  ", "one two three"]:
            self.assertEqual(disfluency.destutter(s), s, repr(s))


class WhitespaceTests(unittest.TestCase):
    """Only the fragment and the space beside it are removed — paragraph breaks
    and every other byte survive."""

    def test_paragraph_break_survives_a_collapse(self):
        src = "para one has for for this.\n\nPara two is clean."
        self.assertEqual(disfluency.destutter(src),
                         "para one has for this.\n\nPara two is clean.")

    def test_no_qualifying_pair_returns_byte_identical(self):
        src = "line one\n\nline two\twith  odd   spacing"
        self.assertIs(disfluency.destutter(src), src)


class CorpusRegressionTests(unittest.TestCase):
    """Run every real stored transcript through the collapser and prove each
    change it makes is explained by one of the two rules. A change that fits no
    rule means the guards have drifted and real dictation is being corrupted."""

    def _load(self):
        path = os.path.join(os.environ.get("APPDATA", ""), "FTC Whisper",
                            "history.json")
        if not os.path.exists(path):
            self.skipTest("no local history.json corpus on this machine")
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        texts = [r.get("transcribed_text", "") for r in rows]
        return [t for t in texts if t and t.strip()]

    def _explained(self, before: str, after: str) -> bool:
        """The collapser only ever DELETES tokens, never invents or reorders
        them, and every deleted run is a collapsible function word, a
        false-start fragment of some word in the utterance, or one copy of an
        exactly repeated phrase. Compared on token KEYS so a carried capital
        ("Rec" -> "Recent") is not read as a new word.
        """
        a = [disfluency._key(t) for t in before.split()]
        b = [disfluency._key(t) for t in after.split()]
        if len(b) >= len(a):
            return False
        i = j = 0
        while i < len(a):
            if j < len(b) and a[i] == b[j]:
                i += 1
                j += 1
                continue
            # a deleted run starting at a[i]: find where b resumes
            ok = False
            for n in range(1, 5):
                run = a[i:i + n]
                if len(run) < n:
                    break
                repeats = run == a[i - n:i] or run == a[i + n:i + 2 * n]
                single = n == 1 and (
                    run[0] in disfluency._DUP_COLLAPSE
                    or any(disfluency._is_false_start(run[0], f) for f in a))
                if repeats or single:
                    rest = a[i + n:]
                    if rest[:1] == b[j:j + 1] or (not rest and j == len(b))                             or rest[:1] == a[i:i + 1]:
                        i += n
                        ok = True
                        break
            if not ok:
                return False
        return j == len(b)

    def test_every_corpus_change_is_a_known_stutter(self):
        texts = self._load()
        for t in texts:
            out = disfluency.destutter(t)
            if out == t:
                continue
            # No paragraph break may be lost.
            self.assertEqual(t.count("\n"), out.count("\n"),
                             f"newline lost in: {t[:80]!r}")
            self.assertTrue(self._explained(t, out),
                            f"unexplained rewrite:\n  {t!r}\n  {out!r}")

    # The two stutters this feature was built for, kept here VERBATIM as they
    # were dictated. They used to be read out of history.json, which is a
    # rolling 200-row cache of whatever Ryan said most recently — so the test
    # passed until the examples scrolled out of it and then failed for a reason
    # that had nothing to do with the collapser (which the sibling corpus test
    # above proves is still behaving). A regression fixture may not be able to
    # expire; if an example is worth pinning it belongs in the test.
    # One real example per rule, and each must genuinely CHANGE — a fixture
    # asserting "unchanged" pins nothing.
    KNOWN_STUTTERS = (
        # The reported false start.
        ("push all most rec recent changes",
         "push all most recent changes"),
        # A doubled function word, lifted from a real dictation.
        ("I also want to add an option, so if like on the the chat bot.",
         "I also want to add an option, so if like on the chat bot."),
    )

    def test_the_two_known_stutters_are_actually_fixed(self):
        for before, after in self.KNOWN_STUTTERS:
            self.assertNotEqual(before, after, "fixture pins no collapse")
            self.assertEqual(after, disfluency.destutter(before), before)

    def test_no_known_stutter_survives_in_the_live_corpus(self):
        """Belt to the braces: if the machine's cache DOES still hold one of
        them, it must still come out collapsed. Silent when it does not, rather
        than failing over a fixture nobody controls."""
        hits = [t for t in self._load() if "rec recent" in t]
        if not hits:
            self.skipTest("the rolling corpus no longer holds this example")
        for t in hits:
            self.assertNotIn("rec recent", disfluency.destutter(t))


if __name__ == "__main__":
    unittest.main()
