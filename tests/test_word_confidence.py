"""Per-word confidence through to the finished dictation (2026-11-18).

Ryan's real dictations are the fixtures, pinned as LITERALS: the engine's raw
text and its own (word, confidence) record, captured from the stored WAVs with
tools-equivalent Parakeet runs. Never read from the rolling history.json (a
fixture that can scroll out of a cache pins nothing), and never the audio
itself in the repo: it is a public repository and the clips are Ryan's voice.
The audio check at the bottom runs only where the clips exist locally
(ECHO_ACCURACY_WAVS) and the model is installed.

Both directions are pinned: what the engine was unsure of may be corrected,
what it was sure of is never touched, and an unknown confidence counts as sure.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import homophones
import vocab_profiles
import word_confidence
from text_expansion import _dm, apply_vocabulary_fuzzy


def rec(s):
    return [(w, float(c)) for w, c in (x.rsplit(":", 1) for x in s.split())]


# Ryan's vocabulary on the reporting PC (terms only; the bug needs no more).
RYAN_VOCAB = [{"term": t, "sounds_like": []} for t in (
    "FTC Safety Solutions", "RAMS", "Push it", "Vercel", "Pipedrive",
    "Key Drop", "BrightLink")]

# 20261118200520365173.wav: said "push the usage card fixes too".
# Typed before this change: "Push it usage card fixes too."
F_USAGE_CARD = (
    "Push the usage card fixes too.",
    rec("push:0.86 the:0.99 usage:0.93 card:1.00 fixes:0.94 too:0.95"))
# 20261118171555487901.wav. Typed before: "Push it other ready branches as as well."
F_BRANCHES = (
    "Push the other ready branches as as well.",
    rec("push:0.89 the:0.97 other:1.00 ready:0.68 branches:1.00 as:0.98 "
        "uh:0.89 as:1.00 well:0.92"))
# 20261118200500723663.wav: said "push the usage card fixes too and anything
# else in the working tree, just push it".
F_VERSUS = (
    "Push the usage card versus two and anything else in the blocking tree, "
    "just push it.",
    rec("push:0.89 the:1.00 usage:0.99 card:1.00 versus:0.75 two:0.62 um:0.87 "
        "and:1.00 anything:1.00 else:1.00 in:0.99 the:0.94 blocking:0.92 "
        "tree:0.79 just:1.00 push:1.00 it:0.92"))
# Ryan's own dictated report of the same phrase, streamed: "fixes two, but".
F_REPORT = (
    "this is an example that I said like push the usage card fixes two, but "
    "like it reads",
    rec("this:1.00 is:1.00 an:1.00 example:1.00 that:0.90 i:1.00 said:0.88 "
        "like:0.42 push:0.96 the:0.96 usage:1.00 card:0.73 fixes:0.91 "
        "two:0.62 but:1.00 like:0.98 it:0.94 reads:1.00"))


def pipeline(text, conf, vocab=RYAN_VOCAB, managed=()):
    """The two post-passes this change touches, in app.py's order."""
    text = homophones.fix(text, word_conf=conf)
    entries = list(vocab) + [{"term": t, "sounds_like": [], "managed": True}
                             for t in managed]
    return apply_vocabulary_fuzzy(
        text, entries, word_conf=word_confidence.aligned(text, conf))


class FixtureTests(unittest.TestCase):

    def setUp(self):
        if _dm() is None:
            self.skipTest("metaphone encoder unavailable")

    def test_push_the_stays_push_the(self):
        for raw, conf in (F_USAGE_CARD, F_BRANCHES):
            self.assertEqual(pipeline(raw, conf), raw)

    def test_fixes_two_becomes_too(self):
        raw, conf = F_REPORT
        self.assertEqual(
            pipeline(raw, conf),
            raw.replace("fixes two, but", "fixes too, but"))

    def test_versus_two_left_for_the_llm(self):
        # "versus two" is two misheard words; no local rule may guess that.
        # The LLM may, but only for the unsure words (RestrictTests below).
        raw, conf = F_VERSUS
        self.assertEqual(pipeline(raw, conf), raw)


class RestrictTests(unittest.TestCase):

    def test_llm_may_change_only_unsure_words(self):
        raw, conf = F_VERSUS
        proposed = raw.replace("versus two", "fixes too").replace(
            "blocking tree", "working tree")
        got = word_confidence.restrict_to_unsure(raw, proposed, conf)
        # versus (0.75) and two (0.62) were unsure; blocking (0.92) was not.
        self.assertEqual(got, raw.replace("versus two", "fixes too"))

    def test_insertions_and_deletions_refused(self):
        raw, conf = F_VERSUS
        self.assertEqual(word_confidence.restrict_to_unsure(
            raw, raw.replace("anything else", "anything at all else"), conf), raw)
        self.assertEqual(word_confidence.restrict_to_unsure(
            raw, raw.replace("versus two and ", ""), conf), raw)

    def test_no_record_keeps_todays_behaviour(self):
        raw, _ = F_VERSUS
        prop = raw.replace("blocking", "working")
        self.assertEqual(word_confidence.restrict_to_unsure(raw, prop, []), prop)

    def test_layout_and_unchanged_tokens_kept(self):
        raw = "Hi Sam,\n\nthe usage card fixes two now.\n\nThanks"
        conf = rec("hi:1.0 sam:1.0 the:1.0 usage:1.0 card:1.0 fixes:0.9 "
                   "two:0.6 now:1.0 thanks:1.0")
        prop = "Hi Sam, the usage card fixes too now. Thanks!"
        self.assertEqual(word_confidence.restrict_to_unsure(raw, prop, conf),
                         raw.replace("two", "too"))

    def test_one_unsure_half_of_a_compound_never_frees_the_sure_half(self):
        # 2026-11-20 audit: "twenty" was sure, only "two" was not, and the
        # whole token used to be replaceable.
        raw = "Please use twenty-two bolts here."
        conf = rec("please:1.0 use:1.0 twenty:0.99 two:0.2 bolts:1.0 here:1.0")
        self.assertEqual(word_confidence.restrict_to_unsure(
            raw, "Please use thirty-three bolts here.", conf), raw)
        # The unsure half alone may still change.
        self.assertEqual(word_confidence.restrict_to_unsure(
            raw, "Please use twenty-too bolts here.", conf),
            "Please use twenty-too bolts here.")

    def test_unaligned_word_counts_as_sure(self):
        # "BrightLink" was rewritten by the vocabulary, so no record holds it.
        raw = "Open BrightLink now please."
        conf = rec("open:0.4 bright:0.4 link:0.4 now:1.0 please:1.0")
        self.assertEqual(word_confidence.restrict_to_unsure(
            raw, "Open Brightline now please.", conf), raw)


class ManagedGateTests(unittest.TestCase):

    def setUp(self):
        if _dm() is None:
            self.skipTest("metaphone encoder unavailable")

    def _managed(self, text, term, conf):
        return apply_vocabulary_fuzzy(
            text, [{"term": term, "sounds_like": [], "managed": True}],
            word_conf=conf)

    def test_managed_name_needs_an_unsure_word(self):
        text = "We need a new fork lift on site."
        n = len(word_confidence._WORD_RE.findall(text))
        sure = [0.99] * n
        unsure = list(sure)
        unsure[4] = 0.5                      # "fork"
        self.assertEqual(self._managed(text, "forklift", sure), text)
        self.assertEqual(self._managed(text, "forklift", [None] * n), text)
        self.assertEqual(self._managed(text, "forklift", unsure),
                         "We need a new forklift on site.")
        # Without a record the pass behaves as it always has.
        self.assertEqual(self._managed(text, "forklift", None),
                         "We need a new forklift on site.")

    def test_hand_typed_terms_are_not_gated(self):
        text = "Deploy to vercell now."
        self.assertEqual(apply_vocabulary_fuzzy(
            text, [{"term": "Vercel", "sounds_like": []}],
            word_conf=[0.99] * 4), "Deploy to Vercel now.")


class ProfileTests(unittest.TestCase):

    def test_company_profile_from_domain(self):
        terms = vocab_profiles.terms_for("someone@ftc-ss.com")
        self.assertIn("forklift", terms)
        self.assertIn("BrightLink Notetaker", terms)
        self.assertEqual(vocab_profiles.profile_for("x@FTC-SS.com"), "safety")

    def test_other_accounts_get_products_only(self):
        terms = vocab_profiles.terms_for("a@example.com")
        self.assertIn("BrightLink Echo", terms)
        self.assertNotIn("forklift", terms)

    def test_signed_out_gets_nothing(self):
        self.assertEqual(vocab_profiles.terms_for(""), [])

    def test_profile_terms_never_reach_a_decoder_prompt(self):
        # They join _managed_entries, which _get_prompt_hotwords excludes.
        with open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "app.py"), encoding="utf-8") as f:
            src = f.read()
        body = src[src.index("def _get_prompt_hotwords"):]
        body = body[:body.index("\n    def ", 10)]
        self.assertNotIn("_managed_entries", body)
        self.assertNotIn("vocab_profiles", body)


@unittest.skipUnless(os.environ.get("ECHO_ACCURACY_WAVS"),
                     "set ECHO_ACCURACY_WAVS to the folder of Ryan's clips")
class AudioFixtureTests(unittest.TestCase):
    """End to end from the real clips: the batch decode plus the two passes."""

    WANT = {
        "20261118200520365173": "Push the usage card fixes too.",
        "20261118171555487901": "Push the other ready branches as as well.",
    }

    def test_clips(self):
        import wave
        import numpy as np
        import asr_engine
        eng = asr_engine.ParakeetTranscriber()
        if not eng.load_model():
            self.skipTest("Parakeet model not installed")
        folder = os.environ["ECHO_ACCURACY_WAVS"]
        for key, want in self.WANT.items():
            with wave.open(os.path.join(folder, key + ".wav")) as w:
                sr = w.getframerate()
                a = np.frombuffer(w.readframes(w.getnframes()),
                                  dtype=np.int16).astype(np.float32) / 32768.0
            conf = []
            raw = eng.transcribe(a, sr, conf_out=conf)
            self.assertEqual(pipeline(raw, conf), want, key)


if __name__ == "__main__":
    unittest.main()
