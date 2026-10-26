"""Seam repair: the full stop Parakeet writes at a streaming commit boundary.

Each committed chunk is decoded as a whole utterance, so a commit that lands on
a breath mid-sentence came out as "to the point where this is. The most
accurate transcription tool" (Ryan, 2026-10-26, v1.8.15). The session now
decodes every join again with audio on both sides and follows that decode at
finalize; with no seam decode a word rule decides. Synthetic fixtures only:
regression fixtures may not read the rolling history.
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stream_session import StreamingSession, repair_seam


class SeamDecodeTests(unittest.TestCase):
    def test_shipped_case_period_dropped_and_lowercased(self):
        self.assertEqual(
            repair_seam("get this to the point where this is.",
                        "The most accurate transcription tool on the planet.",
                        "and we can actually get this to the point where this "
                        "is the most accurate transcription."),
            ("get this to the point where this is",
             "the most accurate transcription tool on the planet."))

    def test_real_sentence_end_kept(self):
        prev, nxt = "We shipped it on Friday.", "The next job is testing."
        self.assertEqual(
            repair_seam(prev, nxt,
                        "we shipped it on Friday. The next job is"),
            (prev, nxt))

    def test_seam_comma_never_replaces_stop(self):
        # A short window heard real sentence ends as commas in testing
        # ("like a hairdryer, I moved"): a stop is dropped or kept, never
        # turned into a comma splice.
        prev, nxt = "It sounded like a hairdryer.", "I moved my files."
        self.assertEqual(
            repair_seam(prev, nxt, "like a hairdryer, I moved my files"),
            (prev, nxt))

    def test_name_after_join_keeps_capital(self):
        self.assertEqual(
            repair_seam("I sent it to.", "Jason this morning.",
                        "I sent it to Jason this morning"),
            ("I sent it to", "Jason this morning."))

    def test_comma_before_capital_conjunction(self):
        # Shipped: "more prominent, And also" at a commit join.
        self.assertEqual(
            repair_seam("a little bit more prominent,", "And also, maybe",
                        "a little bit more prominent and also maybe"),
            ("a little bit more prominent", "and also, maybe"))

    def test_unpunctuated_join_takes_seam_stop(self):
        # Shipped: "adjust that for the light mode Also, just".
        self.assertEqual(
            repair_seam("adjust that for the light mode", "Also, just you know",
                        "for the light mode. Also just you know"),
            ("adjust that for the light mode.", "Also, just you know"))

    def test_seam_question_never_added(self):
        prev, nxt = "so can you check.", "The file now."
        self.assertEqual(repair_seam(prev, nxt, "so can you check? The file"),
                         (prev, nxt))

    def test_acronym_never_lowercased_by_seam(self):
        self.assertEqual(
            repair_seam("this is.", "IT support.", "this is it support"),
            ("this is", "IT support."))

    def test_question_mark_never_touched(self):
        prev, nxt = "Can you check?", "The file is there."
        self.assertEqual(repair_seam(prev, nxt, "can you check the file"),
                         (prev, nxt))

    def test_abbreviation_dot_never_touched(self):
        prev, nxt = "Meet at 7 p.m.", "The room is booked."
        self.assertEqual(repair_seam(prev, nxt, "meet at 7 p.m the room"),
                         (prev, nxt))

    def test_unaligned_seam_falls_back_to_word_rule(self):
        # The seam heard different words at the join: no pair to read, so
        # the word rule decides ("is" can't end a sentence, "the" is safe).
        self.assertEqual(
            repair_seam("the point where this is.", "The most accurate.",
                        "completely different words here"),
            ("the point where this is", "the most accurate."))

    def test_repeated_pair_uses_neighbours(self):
        out = repair_seam("so it is.", "The best one.",
                          "it is. The plan, so it is the best one")
        self.assertEqual(out, ("so it is", "the best one."))


class FallbackRuleTests(unittest.TestCase):
    def test_hanging_word_and_function_word(self):
        self.assertEqual(repair_seam("we went to the.", "Most important bit."),
                         ("we went to the", "most important bit."))

    def test_finished_sentence_kept(self):
        prev, nxt = "That is what it does.", "The rest is fine."
        self.assertEqual(repair_seam(prev, nxt), (prev, nxt))

    def test_capital_content_word_kept(self):
        # "Jason" may be a name: without a seam decode the stop stays.
        prev, nxt = "I gave it to.", "Jason later."
        self.assertEqual(repair_seam(prev, nxt), (prev, nxt))

    def test_pronoun_i_kept(self):
        prev, nxt = "this is.", "I think so."
        self.assertEqual(repair_seam(prev, nxt), (prev, nxt))

    def test_acronym_kept(self):
        prev, nxt = "this is.", "IT support."
        self.assertEqual(repair_seam(prev, nxt), (prev, nxt))


class AssemblyTests(unittest.TestCase):
    def test_seam_applied_by_index(self):
        out = StreamingSession._assemble_paragraphs(
            [("We can get this to where this is.", False),
             ("The most accurate tool.", False)],
            {1: "get this to where this is the most accurate"})
        self.assertEqual(out, "We can get this to where this is the most accurate tool.")

    def test_removed_stop_never_starts_paragraph(self):
        out = StreamingSession._assemble_paragraphs(
            [("We can get this to where this is.", False),
             ("The most accurate tool.", True)],
            {1: "where this is the most accurate"})
        self.assertNotIn("\n\n", out)

    def test_kept_stop_still_breaks_paragraph(self):
        out = StreamingSession._assemble_paragraphs(
            [("First point done.", False), ("New topic now.", True)],
            {1: "first point done. New topic"})
        self.assertEqual(out, "First point done.\n\nNew topic now.")


# --- session level: seam decoded in the background, never at stop -----------

RATE = 16000


class _Recorder:
    def __init__(self, secs):
        rng = np.random.default_rng(0)
        self.a = (rng.standard_normal(int(secs * RATE)) * 0.1).astype(np.float32)
        # A clear pause at 7.4s for the commit point search to find.
        self.a[int(7.2 * RATE):int(7.7 * RATE)] = 0.0
        self.active_sample_rate = RATE
        self.now = 0
        self.dropped_samples = 0
        self.is_recording = True

    def get_audio_range(self, start):
        seg = self.a[start:self.now]
        return seg if len(seg) else None

    def drop_audio_before(self, abs_):
        self.dropped_samples = abs_

    def stop(self):
        self.is_recording = False
        return self.a[self.dropped_samples:]


class _Engine:
    """Seam windows are the only calls without context; of the rest the first
    is the committed chunk and the later one the tail."""
    def __init__(self):
        self.calls = []
        self.kept = 0

    def transcribe(self, audio, rate, **kw):
        self.calls.append(round(len(audio) / rate, 1))
        if "context_words" not in kw:
            return "to the point where this is the most accurate"
        self.kept += 1
        if self.kept == 1:
            return "We can get this to the point where this is."
        return "The most accurate tool."


class SessionSeamTests(unittest.TestCase):
    def _run(self, secs):
        rec, eng = _Recorder(secs), _Engine()
        s = StreamingSession(rec, eng)
        step = int(StreamingSession.TICK_INTERVAL * RATE)
        while rec.now < len(rec.a):
            rec.now = min(len(rec.a), rec.now + step)
            s._tick()
        before = len(eng.calls)
        text, _tail, _rate = s.finalize()
        return text, len(eng.calls) - before, s

    def test_seam_repaired_and_stop_path_pays_one_decode(self):
        text, stop_calls, s = self._run(14.0)
        self.assertEqual(len(s._committed_texts), 1)
        self.assertEqual(
            text, "We can get this to the point where this is the most accurate tool.")
        self.assertEqual(stop_calls, 1, "finalize must decode only the tail")

    def test_seam_upgraded_to_full_context(self):
        _text, _calls, s = self._run(14.0)
        right, _t = s._seam_texts[1]
        self.assertAlmostEqual(right, StreamingSession.SEAM_SIDE, places=3)


if __name__ == "__main__":
    unittest.main()
