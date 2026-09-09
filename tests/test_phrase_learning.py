"""Learned phrases: what may be learned, what may be rewritten, and the
measured corruptions that shaped both gates.

The corpus test is the real bar. Rewriting genuine speech is a far worse
regression than missing a correction, so it drives the whole store from the
200 real transcripts in history.json, then asks the rescue to run over those
same transcripts with EVERY word marked low-confidence — the most adversarial
condition the feature can ever meet — and fails if a single one changes. The
first draft of this module rewrote 33 of them ("to main" -> "domain",
"really a" -> "really", "actual" -> "actually"); each of those has its own
test below as well, because a corpus test tells you something broke and a
named test tells you what.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import phrase_learning as pl


def _conf_for(text, value=0.95):
    return [value] * len(list(pl._WORD_RE.finditer(text)))


def _store(tmp, email="t@example.com"):
    return pl.PhraseStore(email, directory=tmp)


class WordConfidenceTests(unittest.TestCase):
    def test_tokens_group_on_the_leading_space(self):
        # onnx-asr rewrites the SentencePiece word marker to a space when it
        # loads the vocab, so that space IS the word boundary.
        tokens = [" bright", "link", " pipe", "line"]
        logprobs = [-0.1, -0.1, -2.0, -2.0]
        words = pl.words_from_tokens(tokens, logprobs)
        self.assertEqual(["brightlink", "pipeline"], [w for w, _c in words])
        self.assertGreater(words[0][1], 0.85)
        self.assertLess(words[1][1], 0.2)

    def test_mismatched_lengths_yield_nothing(self):
        self.assertEqual([], pl.words_from_tokens([" a", "b"], [-0.1]))
        self.assertEqual([], pl.words_from_tokens(None, None))

    def test_punctuation_only_tokens_are_dropped(self):
        words = pl.words_from_tokens([" yes", ",", " no"], [-0.1, -0.1, -0.1])
        self.assertEqual(["yes", "no"], [w for w, _c in words])


class AlignmentTests(unittest.TestCase):
    def test_deleted_words_do_not_shift_the_alignment(self):
        # Post-processing strips fillers, so the record legitimately runs
        # ahead of the final text.
        recorded = [("push", 0.9), ("um", 0.2), ("the", 0.9), ("pipeline", 0.7)]
        self.assertEqual([0.9, 0.9, 0.7], pl.align("Push the pipeline", recorded))

    def test_a_rewritten_word_is_unknown_not_guessed(self):
        recorded = [("pipe", 0.4), ("drive", 0.4)]
        self.assertEqual([None], pl.align("Pipedrive", recorded))

    def test_no_record_means_every_word_unknown(self):
        self.assertEqual([None, None], pl.align("two words", []))


class LearningGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_a_confident_repeated_phrase_is_learned(self):
        st = _store(self.tmp)
        text = "Open the Brightlink pipeline now."
        for _ in range(pl.PROMOTE_COUNT):
            st.observe(text, _conf_for(text))
        self.assertIn("brightlink pipeline", st.phrase_texts())

    def test_a_phrase_the_engine_was_unsure_about_is_never_learned(self):
        st = _store(self.tmp)
        text = "Open the Brightlink pipeline now."
        for _ in range(pl.PROMOTE_COUNT * 3):
            st.observe(text, _conf_for(text, 0.40))
        self.assertEqual([], st.phrase_texts())

    def test_unknown_confidence_learns_nothing(self):
        st = _store(self.tmp)
        text = "Open the Brightlink pipeline now."
        for _ in range(pl.PROMOTE_COUNT * 3):
            st.observe(text, [None] * 5)
        self.assertEqual([], st.phrase_texts())

    def test_one_dictation_is_not_enough(self):
        st = _store(self.tmp)
        text = "Open the Brightlink pipeline now."
        self.assertEqual([], st.observe(text, _conf_for(text)))

    def test_function_words_at_the_edges_are_refused(self):
        # Every window of a sentence is offered, so without this the store
        # fills with fragments that are not things anybody says.
        self.assertFalse(pl.is_learnable(["the", "brightlink"]))
        self.assertFalse(pl.is_learnable(["pipeline", "to"]))
        self.assertFalse(pl.is_learnable(["whatever", "you"]))
        self.assertTrue(pl.is_learnable(["brightlink", "pipeline"]))

    def test_numbers_and_all_common_phrases_are_refused(self):
        self.assertFalse(pl.is_learnable(["contact", "42"]))
        self.assertFalse(pl.is_learnable(["all", "of", "them"]))

    def test_short_single_words_are_refused(self):
        self.assertFalse(pl.is_learnable(["scrape"[:4]]))
        self.assertTrue(pl.is_learnable(["brightlink"]))

    def test_a_single_word_needs_the_engine_to_have_fumbled_it(self):
        # A word the recogniser never gets wrong does not need boosting; a
        # slot spent on it is a slot not spent on one that does.
        st = _store(self.tmp)
        text = "Brightlink."
        for _ in range(pl.PROMOTE_COUNT_SINGLE * 2):
            st.observe(text, [0.95])
        self.assertEqual([], st.phrase_texts())

        # Now let it hear something that SOUNDS like it, badly, twice.
        for _ in range(2):
            st.observe("Brightling.", [0.30])
        for _ in range(pl.PROMOTE_COUNT_SINGLE):
            st.observe(text, [0.95])
        self.assertIn("brightlink", st.phrase_texts())


class RescueGateTests(unittest.TestCase):
    PHRASES = [{"phrase": "brightlink pipeline", "count": 9}]

    def test_the_case_this_exists_for(self):
        text = "Push the bright link pipeline to production."
        conf = [0.99, 0.99, 0.30, 0.30, 0.35, 0.99, 0.99]
        self.assertEqual("Push the brightlink pipeline to production.",
                         pl.apply_learned_phrases(text, self.PHRASES, conf))

    def test_a_confident_span_is_never_touched(self):
        text = "Push the bright link pipeline to production."
        conf = [0.99] * 7
        self.assertEqual(text, pl.apply_learned_phrases(text, self.PHRASES, conf))

    def test_unknown_confidence_is_never_touched(self):
        text = "Push the bright link pipeline to production."
        self.assertEqual(text,
                         pl.apply_learned_phrases(text, self.PHRASES, [None] * 7))

    def test_no_phrases_is_a_no_op(self):
        text = "Push the bright link pipeline."
        self.assertEqual(text, pl.apply_learned_phrases(text, [], [0.3] * 5))

    # -- the three measured corruptions ----------------------------------

    def test_to_main_never_becomes_domain(self):
        """Measured on the real corpus: "domain" and "to main" share a
        metaphone code and score jw 0.889. Ryan says "push it to main" in
        almost every dictation, so this one would have been unmissable."""
        text = "Push all the recent changes to main, please."
        out = pl.apply_learned_phrases(
            text, [{"phrase": "domain", "count": 30}], [0.30] * 8)
        self.assertEqual(text, out)

    def test_actual_never_becomes_actually(self):
        """jw 0.95, identical metaphone, and a real different word. Caught by
        the length window: a rescue is a re-spelling, not a new syllable."""
        text = "Give me the actual link."
        out = pl.apply_learned_phrases(
            text, [{"phrase": "actually", "count": 50}], [0.30] * 5)
        self.assertEqual(text, out)

    def test_a_rescue_never_deletes_a_word_the_user_said(self):
        """"really a" -> "really" scores jw 0.97 on the collapsed letters. A
        cross-word-count match may not be SHORTER than the span it replaces."""
        text = "I'm not really a big fan of the orange."
        out = pl.apply_learned_phrases(
            text, [{"phrase": "really", "count": 55}], [0.30] * 9)
        self.assertEqual(text, out)

    def test_a_phrase_that_could_not_be_learned_cannot_rescue(self):
        # A store written by an older build, or hand-edited, must not be able
        # to smuggle a function-word phrase past the learning filter.
        text = "Send it to them now."
        out = pl.apply_learned_phrases(
            text, [{"phrase": "to them", "count": 99}], [0.30] * 5)
        self.assertEqual(text, out)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_it_survives_a_round_trip_to_disk(self):
        st = _store(self.tmp)
        text = "Open the Brightlink pipeline now."
        for _ in range(pl.PROMOTE_COUNT):
            st.observe(text, _conf_for(text))
        self.assertTrue(st.flush())
        again = _store(self.tmp)
        self.assertIn("brightlink pipeline", again.phrase_texts())

    def test_forget_also_drops_the_counter(self):
        # Otherwise a phrase the user rejected climbs straight back over the
        # threshold the following week.
        st = _store(self.tmp)
        text = "Open the Brightlink pipeline now."
        for _ in range(pl.PROMOTE_COUNT):
            st.observe(text, _conf_for(text))
        self.assertTrue(st.forget("brightlink pipeline"))
        st.observe(text, _conf_for(text))
        self.assertNotIn("brightlink pipeline", st.phrase_texts())

    def test_two_accounts_do_not_share_a_store(self):
        a = _store(self.tmp, "one@example.com")
        b = _store(self.tmp, "two@example.com")
        self.assertNotEqual(a.path, b.path)
        text = "Open the Brightlink pipeline now."
        for _ in range(pl.PROMOTE_COUNT):
            a.observe(text, _conf_for(text))
        a.flush()
        self.assertEqual([], _store(self.tmp, "two@example.com").phrase_texts())

    def test_a_corrupt_store_file_is_not_fatal(self):
        st = _store(self.tmp)
        with open(st.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual([], _store(self.tmp).phrase_texts())


class HotwordTests(unittest.TestCase):
    def test_the_cap_is_spent_on_the_most_said_phrases(self):
        rows = [{"phrase": f"phrase{i} thing{i}", "count": i}
                for i in range(pl.MAX_HOTWORDS + 20)]
        out = pl.hotwords(rows).split(", ")
        self.assertEqual(pl.MAX_HOTWORDS, len(out))
        self.assertTrue(out[0].startswith(f"phrase{len(rows) - 1} "))


class WiringTests(unittest.TestCase):
    """Source-level: the confidence record only ever comes from passes whose
    text is KEPT, and Parakeet is deliberately not given learned hotwords."""

    def _src(self, name):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), name)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_the_caption_preview_records_no_confidence(self):
        src = self._src("stream_session.py")
        # Two kept passes in _transcribe_paragraph_parts, and nothing else.
        self.assertEqual(2, src.count("conf_out=self._conf"))
        tick = src[src.index("def _tick"):src.index("def _norm_word")]
        self.assertNotIn("conf_out", tick)

    def test_learned_phrases_reach_whisper_but_not_parakeet(self):
        src = self._src("app.py")
        parakeet = src[src.index("def _get_hotwords"):
                       src.index("def _get_prompt_hotwords")]
        self.assertNotIn("phrase_learning", parakeet)
        whisper = src[src.index("def _get_prompt_hotwords"):
                      src.index("def _load_estate_vocab")]
        self.assertIn("phrase_learning.hotwords", whisper)

    def test_learning_runs_before_snippets(self):
        # A snippet body is text the user typed once, not something they say.
        src = self._src("app.py")
        self.assertLess(src.index("store.observe(fixed, word_conf)"),
                        src.index("fixed = apply_snippets(fixed"))


class SpeedTests(unittest.TestCase):
    def test_a_full_store_over_a_long_dictation_stays_negligible(self):
        # Runs after injection is decided, so this is not stop latency — but a
        # pass that crept into the tens of milliseconds would still be wrong.
        phrases = [{"phrase": f"alpha{i} beta{i}", "count": 5}
                   for i in range(pl.MAX_PHRASES)]
        text = ("Push the bright link pipeline to production and check the "
                "prospect intel report for the lead finder list. ") * 25
        conf = [0.30] * len(list(pl._WORD_RE.finditer(text)))
        start = time.perf_counter()
        pl.apply_learned_phrases(text, phrases, conf)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.25, f"rescue took {elapsed * 1000:.0f}ms")


class CorpusRegressionTests(unittest.TestCase):
    """200 real dictations, a store learned from them, and every word marked
    unsure. Nothing may change. If a threshold change trips this, the change
    is wrong, not the test."""

    def _texts(self):
        import json
        hist = os.path.join(os.environ.get("APPDATA", ""), "FTC Whisper",
                            "history.json")
        if not os.path.exists(hist):
            self.skipTest("no local history cache on this machine")
        with open(hist, encoding="utf-8") as f:
            rows = json.load(f)
        return [r.get("transcribed_text") or "" for r in rows
                if (r.get("transcribed_text") or "").strip()]

    def test_learned_phrases_do_not_rewrite_real_dictation(self):
        texts = self._texts()
        tmp = tempfile.mkdtemp()
        st = pl.PhraseStore("corpus@example.com", directory=tmp)
        for t in texts:
            st.observe(t, _conf_for(t))
        phrases = st.phrases()
        self.assertTrue(phrases, "the corpus should teach it something")

        offenders = []
        for t in texts:
            out = pl.apply_learned_phrases(t, phrases, _conf_for(t, 0.30))
            if out != t:
                offenders.append((t, out))
        self.assertEqual(
            [], offenders,
            f"{len(offenders)} real transcript(s) rewritten, "
            f"e.g. {offenders[:1]}")


if __name__ == "__main__":
    unittest.main()
