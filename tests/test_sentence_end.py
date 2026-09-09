"""Terminal punctuation.

The reported want: stop stamping a full stop on the end of every dictation, but
keep it where the utterance clearly IS a finished sentence. Both directions are
pinned — a missing stop on real prose is as much a regression as an unwanted one
on a fragment, and "always"/"never" must still behave exactly as their names say.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sentence_end as se


class SmartAddsTests(unittest.TestCase):
    """Utterances that read as finished sentences."""

    def test_plain_sentence(self):
        self.assertEqual(se.apply("this is a finished sentence", "smart"),
                         "this is a finished sentence.")

    def test_longer_prose(self):
        self.assertEqual(
            se.apply("I have pushed the change to main", "smart"),
            "I have pushed the change to main.")

    def test_already_terminated_is_untouched(self):
        for s in ("Done already.", "Really?", "Stop!", 'He said "no."'):
            self.assertEqual(se.apply(s, "smart"), s)


class SmartLeavesOpenTests(unittest.TestCase):
    """Fragments and mid-sentence dictations — the reported complaint."""

    def test_hanging_conjunction(self):
        for s in ("and then the invoice for",
                  "we should probably go and",
                  "put it in the",
                  "send that over to"):
            self.assertEqual(se.apply(s, "smart"), s)

    def test_short_fragments(self):
        for s in ("yes", "one moment", "about half", "roughly"):
            self.assertEqual(se.apply(s, "smart"), s)

    def test_trailing_comma_is_stripped_not_closed(self):
        self.assertEqual(se.apply("carry on with the next bit,", "smart"),
                         "carry on with the next bit")

    def test_address_never_gets_a_stop(self):
        for s in ("ryan.murphy@ftc-ss.com", "go to ftc-ss.com",
                  "open the report.pdf"):
            self.assertEqual(se.apply(s, "smart"), s)

    def test_open_bracket(self):
        self.assertEqual(se.apply("the total was (", "smart"), "the total was (")


class AlwaysAndNeverTests(unittest.TestCase):
    def test_always_matches_the_old_behaviour(self):
        self.assertEqual(se.apply("one moment", "always"), "one moment.")
        self.assertEqual(se.apply("and then the", "always"), "and then the.")

    def test_always_replaces_a_trailing_comma_never_stacks(self):
        self.assertEqual(se.apply("then,", "always"), "then.")

    def test_never_adds_nothing(self):
        self.assertEqual(se.apply("this is a finished sentence", "never"),
                         "this is a finished sentence")

    def test_never_still_strips_the_pause_artefact(self):
        self.assertEqual(se.apply("finished up here,", "never"),
                         "finished up here")

    def test_unknown_mode_falls_back_to_smart(self):
        self.assertEqual(se.apply("one moment", "nonsense"), "one moment")

    def test_empty(self):
        self.assertEqual(se.apply("", "smart"), "")
        self.assertEqual(se.apply("   ", "always"), "")


class EngineWiringTests(unittest.TestCase):
    """Both engines must route their terminal stop through this module — it is
    the single place the decision is made, for the same reason hallucination
    and disfluency live inside _post_process."""

    def _src(self, name):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), name)
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_parakeet_polish_uses_sentence_end(self):
        src = self._src("asr_engine.py")
        self.assertIn("import sentence_end", src)
        polish = src[src.index("    def polish(self"):]
        polish = polish[:polish.index("\n    @staticmethod")]
        self.assertIn("sentence_end.apply(text, self.end_punctuation)", polish)
        self.assertNotIn('text += "."', polish)

    def test_whisper_post_process_uses_sentence_end(self):
        src = self._src("transcriber.py")
        self.assertIn("import sentence_end", src)
        self.assertIn("sentence_end.apply(text, self.end_punctuation)", src)

    def test_default_mode_is_smart_in_config(self):
        src = self._src("config.py")
        self.assertIn('end_punctuation: str = "smart"', src)


if __name__ == "__main__":
    unittest.main()
