"""Terminal punctuation.

The reported want: stop stamping a full stop on the end of every dictation, but
keep it where the utterance clearly IS a finished sentence. Both directions are
pinned — a missing stop on real prose is as much a regression as an unwanted one
on a fragment, and "always"/"never" must still behave exactly as their names say.

v1.6.79: Parakeet writes a full stop on the end of every utterance ITSELF, and
the first version of this module only ever decided whether to ADD one. So
"never" still ended in a stop and "smart" never judged the engine's stop at all
(172 of 200 real dictations ended in one under both). The inputs below are
therefore written the way the engine actually delivers them: already closed.
"""

import json
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

    def test_a_finished_sentence_keeps_the_engines_stop(self):
        for s in ("I have pushed the change to main.",
                  "Do this and then run it locally so I can see it.",
                  'He said "no."'):
            self.assertEqual(se.apply(s, "smart"), s)

    def test_question_and_exclamation_are_untouched(self):
        for s in ("Really?", "Stop!", "What time?", "and then?"):
            self.assertEqual(se.apply(s, "smart"), s)

    def test_an_abbreviation_dot_is_not_a_stop(self):
        for s in ("See you at 7 p.m.", "Apples, pears, etc."):
            self.assertEqual(se.apply(s, "smart"), s)


class SmartLeavesOpenTests(unittest.TestCase):
    """Fragments and mid-sentence dictations — the reported complaint."""

    def test_hanging_conjunction(self):
        for s in ("and then the invoice for",
                  "we should probably go and",
                  "put it in the",
                  "send that over to"):
            self.assertEqual(se.apply(s, "smart"), s)

    def test_the_engines_stop_comes_off_a_fragment(self):
        # Real dictations, exactly as the engine closed them. Each is the user
        # mid-sentence, a search box or an address. None wants the stop.
        cases = {
            "I also want it to not add a full stop at the.":
                "I also want it to not add a full stop at the",
            "We push all the most recent changes to main, so.":
                "We push all the most recent changes to main, so",
            "Trapezium shape.": "Trapezium shape",
            "ryan.murphy@ftc-ss.com.": "ryan.murphy@ftc-ss.com",
            "Compose.io.": "Compose.io",
            "Consultancy.": "Consultancy",
        }
        for spoken, want in cases.items():
            self.assertEqual(se.apply(spoken, "smart"), want, spoken)

    def test_short_fragments(self):
        for s in ("yes", "one moment", "about half", "roughly"):
            self.assertEqual(se.apply(s, "smart"), s)
        for s in ("Yes.", "One moment.", "About half."):
            self.assertEqual(se.apply(s, "smart"), s[:-1])

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
        self.assertEqual(se.apply("Done.", "always"), "Done.")

    def test_always_replaces_a_trailing_comma_never_stacks(self):
        self.assertEqual(se.apply("then,", "always"), "then.")

    def test_never_adds_nothing(self):
        self.assertEqual(se.apply("this is a finished sentence", "never"),
                         "this is a finished sentence")

    def test_never_removes_the_engines_full_stop(self):
        # The reported dictation, as it was injected with "Never" selected.
        self.assertEqual(
            se.apply("So think that could look good generate it.", "never"),
            "So think that could look good generate it")
        self.assertEqual(se.apply("Done.", "never"), "Done")

    def test_never_only_touches_the_end(self):
        self.assertEqual(se.apply("One thing. Then another.", "never"),
                         "One thing. Then another")
        self.assertEqual(
            se.apply("First paragraph.\n\nSecond paragraph.", "never"),
            "First paragraph.\n\nSecond paragraph")

    def test_never_keeps_question_and_exclamation(self):
        for s in ("Can you do that?", "Stop!"):
            self.assertEqual(se.apply(s, "never"), s)

    def test_never_keeps_ellipses_and_abbreviations(self):
        for s in ("and then...", "and then…", "meet at 7 p.m.",
                  "the U.S.", "apples, pears, etc."):
            self.assertEqual(se.apply(s, "never"), s)

    def test_never_strips_inside_a_closing_quote(self):
        self.assertEqual(se.apply('He said "no."', "never"), 'He said "no"')
        self.assertEqual(se.apply("(see the notes.)", "never"),
                         "(see the notes)")

    def test_never_still_strips_the_pause_artefact(self):
        self.assertEqual(se.apply("finished up here,", "never"),
                         "finished up here")

    def test_a_lone_stop_is_not_emptied(self):
        self.assertEqual(se.apply(".", "never"), ".")

    def test_unknown_mode_falls_back_to_smart(self):
        self.assertEqual(se.apply("one moment", "nonsense"), "one moment")
        self.assertEqual(se.apply("One moment.", "nonsense"), "One moment")

    def test_empty(self):
        self.assertEqual(se.apply("", "smart"), "")
        self.assertEqual(se.apply("   ", "always"), "")


class MatchEndingTests(unittest.TestCase):
    """The AI upgrade must not put back a stop the setting took off."""

    def test_a_stop_the_setting_removed_stays_removed(self):
        self.assertEqual(se.match_ending("Generate it.", "generate it"),
                         "Generate it")

    def test_a_stop_that_was_inserted_is_kept(self):
        self.assertEqual(se.match_ending("It is done", "It is done."),
                         "It is done.")
        self.assertEqual(se.match_ending("Fine, done.", "fine done."),
                         "Fine, done.")

    def test_question_marks_are_the_corrections_call(self):
        self.assertEqual(se.match_ending("Is it done?", "is it done"),
                         "Is it done?")

    def test_empty_inputs_pass_through(self):
        self.assertEqual(se.match_ending("", "x"), "")
        self.assertEqual(se.match_ending("Text.", ""), "Text.")


class CorpusTests(unittest.TestCase):
    """Invariants over whatever the local history happens to hold. Named
    examples live in the tests above; this only checks that the modes never do
    anything but settle the final full stop on real dictation."""

    def setUp(self):
        path = os.path.join(os.environ.get("APPDATA", ""), "FTC Whisper",
                            "history.json")
        try:
            with open(path, encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, ValueError):
            raise unittest.SkipTest("no local history corpus")
        self.texts = [(r.get("transcribed_text") or "").strip()
                      for r in rows if isinstance(r, dict)]
        self.texts = [t for t in self.texts if t]
        if not self.texts:
            raise unittest.SkipTest("empty history corpus")

    def test_never_leaves_no_plain_full_stop_and_changes_nothing_else(self):
        for t in self.texts:
            out = se.apply(t, "never")
            self.assertFalse(se.ends_with_full_stop(out) and out != ".", t)
            self.assertTrue(t.startswith(out), (t, out))
            self.assertLessEqual(len(t) - len(out), 1, (t, out))

    def test_smart_only_ever_settles_the_final_stop(self):
        for t in self.texts:
            out = se.apply(t, "smart")
            if out == t:
                continue
            if t[-1] in ",;:":
                # A stored pause artefact: stripped, never closed.
                self.assertEqual(out, t[:-1].rstrip(), (t, out))
            elif se.ends_with_full_stop(t):
                # Removed: the words did not read as a finished sentence.
                self.assertEqual(out, se.strip_full_stop(t))
                self.assertFalse(se.looks_finished(out), out)
            else:
                # Added (a row stored without one): only to a finished one.
                self.assertEqual(out, t + ".", (t, out))
                self.assertTrue(se.looks_finished(t), t)


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

    def test_ai_upgrades_keep_the_inserted_ending(self):
        # context_fix results are offered in the popup; accepting one must not
        # undo the setting. Every call site in app.py reconciles the ending.
        src = self._src("app.py")
        self.assertEqual(src.count("context_fix("),
                         src.count("sentence_end.match_ending("))

    def test_default_mode_is_smart_in_config(self):
        src = self._src("config.py")
        self.assertIn('end_punctuation: str = "smart"', src)


if __name__ == "__main__":
    unittest.main()
