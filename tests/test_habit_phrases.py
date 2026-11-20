"""Habit phrases: the whole runs a person says all day ("push everything to
main"), and the one slipped word inside them that the engine gets wrong.

Every fixture below is a real Parakeet output from Ryan's own recordings
(14-18 Nov 2026), written in as a literal because a regression fixture may not
read the rolling history.json. The must-not-fire cases are the false positives
the corpus run produced while the gates were being set; each one is the reason
for a specific rule in apply_habits.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cloud_sync
import phrase_learning as pl

try:
    from metaphone import doublemetaphone  # noqa: F401
    HAVE_DM = True
except Exception:
    HAVE_DM = False


# Ryan's habits as the store would hold them after a few days of dictation.
HABITS = {
    "pushed to main": 30,
    "push everything to main": 20,
    "push it to main": 16,
    "make sure absolutely everything": 12,
    "run the verify before done": 15,
}


def _conf(text, value):
    return [value] * len(list(pl._WORD_RE.finditer(text)))


def _fix(text, value=0.97, habits=HABITS):
    return pl.apply_habits(text, habits, _conf(text, value))


@unittest.skipUnless(HAVE_DM, "metaphone not installed")
class RealSlipTests(unittest.TestCase):
    """Each of these came out of Echo as shown, and was meant as the fix."""

    def test_to_mean_becomes_to_main(self):
        self.assertEqual(_fix("Push everything to mean or whatever."),
                         "Push everything to main or whatever.")

    def test_a_swallowed_n_to_me_becomes_to_main(self):
        # Parakeet was SURE (0.97): only the strong tier can reach this.
        self.assertEqual(_fix("Just push it to me."), "Just push it to main.")
        self.assertEqual(_fix("genuinely been pushed to me. I want to"),
                         "genuinely been pushed to main. I want to")

    def test_domain_is_two_words_run_together(self):
        self.assertEqual(
            _fix("make sure those fixes are pushed domain so, yeah."),
            "make sure those fixes are pushed to main so, yeah.")

    def test_unsure_slip_repairs_once_the_habit_is_established(self):
        habits = {"pushed to main": pl.HABIT_REPAIR_COUNT}
        self.assertEqual(_fix("it was pushed to mean", 0.5, habits),
                         "it was pushed to main")

    def test_the_engine_capital_on_a_slip_is_dropped_mid_sentence(self):
        self.assertEqual(_fix("push everything to Maine now"),
                         "push everything to main now")

    def test_a_sentence_start_keeps_its_capital(self):
        self.assertEqual(_fix("Ppush everything to main.", 0.5),
                         "Push everything to main.")


@unittest.skipUnless(HAVE_DM, "metaphone not installed")
class MustNotFireTests(unittest.TestCase):
    def test_a_different_sentence_is_left_alone(self):
        for text in ("Send it to me.", "Push it to the side.",
                     "pushed to the limit", "push everything aside"):
            self.assertEqual(_fix(text), text)

    def test_a_confident_variant_needs_a_strong_habit(self):
        habits = {"pushed to main": pl.HABIT_STRONG_COUNT - 1}
        self.assertEqual(_fix("it was pushed to me", 0.97, habits),
                         "it was pushed to me")

    def test_a_variant_the_person_also_says_is_left_alone(self):
        habits = dict(HABITS, **{"pushed to me": 5})     # 5 x 8 > 30
        self.assertEqual(_fix("it was pushed to me", 0.97, habits),
                         "it was pushed to me")
        # ...and with the engine unsure, the ratio still protects it.
        habits = {"pushed to main": 8, "pushed to mean": 3}
        self.assertEqual(_fix("pushed to mean", 0.5, habits), "pushed to mean")

    def test_another_form_of_the_word_is_not_a_slip(self):
        # Corpus run: "a push to main deploys" -> "a pushed to main".
        self.assertEqual(_fix("a push to main deploys"), "a push to main deploys")
        # "Ran the verify-before-done gate" -> "run the ...".
        self.assertEqual(_fix("Ran the verify before done gate"),
                         "Ran the verify before done gate")

    def test_an_everyday_word_never_replaces_another(self):
        # Corpus run, every word unsure: was/is, like/look. (rule/real still
        # fires there: "real" is not on the ordinary-words list. Recorded as a
        # known limit in docs/decisions/accuracy-vocabulary.md.)
        habits = {"work is done today": 20, "looks like a little bit": 20}
        for text in ("the work was done today", "looks look a little bit"):
            self.assertEqual(_fix(text, 0.5, habits), text)

    def test_a_merge_never_inserts_a_word(self):
        # Corpus run: "Needs Input Sweep" -> "Needs input dot Sweep".
        habits = {"needs input dot": 20}
        self.assertEqual(_fix("Needs Input Sweep", 0.5, habits),
                         "Needs Input Sweep")
        # "asked" is not "ask it".
        habits = {"decisions are ask it with": 20}
        self.assertEqual(_fix("Decisions are asked with", 0.5, habits),
                         "Decisions are asked with")

    def test_punctuation_breaks_a_window(self):
        self.assertEqual(_fix("I pushed. To me it was fine."),
                         "I pushed. To me it was fine.")

    def test_digits_are_never_touched(self):
        habits = {"deploy version two today": 30}
        self.assertEqual(_fix("deploy version 2 today", 0.5, habits),
                         "deploy version 2 today")

    def test_no_confidence_means_no_repair(self):
        text = "Push everything to mean."
        self.assertEqual(pl.apply_habits(text, HABITS, None), text)
        n = len(_conf(text, 0.5))
        self.assertEqual(pl.apply_habits(text, HABITS, [None] * n), text)


class HabitShapeTests(unittest.TestCase):
    def test_commands_with_small_words_inside_are_habits(self):
        for norm in ("pushed to main", "push everything to main",
                     "push it to main"):
            self.assertTrue(pl.is_habit(norm.split()), norm)

    def test_fragments_and_filler_are_not(self):
        for norm in ("to main", "pushed to", "make sure that", "push",
                     "push it to main now please today", "version 2 today",
                     "with 'verified not"):
            self.assertFalse(pl.is_habit(norm.split()), norm)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _say(self, store, text, n, value=0.95):
        for _ in range(n):
            store.observe(text, _conf(text, value))

    def test_confident_speech_is_counted_unsure_speech_is_not(self):
        s = pl.PhraseStore("a@b.c", directory=self.tmp)
        self._say(s, "I pushed to main today", 3)
        self._say(s, "I pushed to main today", 3, value=0.5)
        self.assertEqual(s.habit_counts().get("pushed to main"), 3)

    def test_habits_survive_disk_but_never_reach_cloud_sync(self):
        s = pl.PhraseStore("a@b.c", directory=self.tmp)
        self._say(s, "I pushed to main today", 6)
        self.assertTrue(s.flush())
        again = pl.PhraseStore("a@b.c", directory=self.tmp)
        self.assertEqual(again.habit_counts().get("pushed to main"), 6)
        # Runs of what was dictated stay on this PC whatever the switch.
        self.assertNotIn("habits", again.snapshot())
        again.replace_with(cloud_sync.merge_phrases(again.snapshot(), {}))
        self.assertEqual(again.habit_counts().get("pushed to main"), 6)

    @unittest.skipUnless(HAVE_DM, "metaphone not installed")
    def test_a_variant_said_confidently_is_counted_and_protects_itself(self):
        # Review repro: "pushed to me" said 30 times was never counted (it ends
        # on a function word, so it is no habit), and the strong tier then
        # rewrote it into "pushed to main".
        s = pl.PhraseStore("a@b.c", directory=self.tmp)
        self._say(s, "it was pushed to main", 15)
        s.habit_index()                       # the app builds it every dictation
        self._say(s, "it was pushed to me", 30)
        counts = s.habit_counts()
        self.assertEqual(counts.get("pushed to me"), 30)
        text = "it was pushed to me"
        self.assertEqual(pl.apply_habits(text, counts, _conf(text, 0.97),
                                         s.habit_index()), text)

    @unittest.skipUnless(HAVE_DM, "metaphone not installed")
    def test_a_repaired_sure_variant_still_counts_in_the_app_order(self):
        # 2026-11-20 audit: the app repairs BEFORE it observes, so a sure
        # "pushed to me" became "pushed to main" every time and was never
        # counted (the repaired word has no confidence). The words really
        # heard are now counted, so the variant builds up and stops being
        # repaired.
        s = pl.PhraseStore("a@b.c", directory=self.tmp)
        self._say(s, "it was pushed to main", 30)
        text = "it was pushed to me"
        conf = _conf(text, 0.97)
        outs = []
        for _ in range(12):
            heard = []
            out = pl.apply_habits(text, s.habit_counts(), conf,
                                  s.habit_index(), s.forgotten_norms(),
                                  heard=heard)
            outs.append(out)
            s.observe(out, pl.align(out, list(zip(text.split(), conf))))
            for run, rc in heard:
                s.observe(run, rc)
        self.assertEqual(outs[0], "it was pushed to main")
        self.assertEqual(outs[-1], text, outs)
        self.assertGreater(s.habit_counts().get("pushed to me", 0), 0)

    def test_an_unsure_repair_reports_nothing_to_count(self):
        heard = []
        text = "it was pushed to mean"
        pl.apply_habits(text, {"pushed to main": pl.HABIT_REPAIR_COUNT},
                        _conf(text, 0.5), heard=heard)
        self.assertEqual(heard, [])

    @unittest.skipUnless(HAVE_DM, "metaphone not installed")
    def test_forget_reaches_habits(self):
        # Review repro: a forgotten phrase went on repairing into itself.
        s = pl.PhraseStore("a@b.c", directory=self.tmp)
        self._say(s, "please deploy brightlink pipeline now", 15)
        self.assertIn("deploy brightlink pipeline", s.habit_counts())
        self.assertTrue(s.forget("brightlink pipeline"))
        self.assertFalse(any("brightlink pipeline" in h for h in s.habit_counts()))
        self._say(s, "please deploy brightlink pipeline now", 15)
        self.assertFalse(any("brightlink pipeline" in h for h in s.habit_counts()))
        text = "please deploy brightling pipeline now"
        self.assertEqual(pl.apply_habits(text, s.habit_counts(), _conf(text, 0.5),
                                         s.habit_index(), s.forgotten_norms()),
                         text)

    def test_clear_drops_habits(self):
        s = pl.PhraseStore("a@b.c", directory=self.tmp)
        self._say(s, "I pushed to main today", 6)
        s.clear()
        self.assertEqual(s.habit_counts(), {})

    def test_the_index_rebuilds_when_a_habit_becomes_usable(self):
        s = pl.PhraseStore("a@b.c", directory=self.tmp)
        self.assertEqual(s.habit_index(), {})
        self._say(s, "I pushed to main today", pl.HABIT_REPAIR_COUNT)
        self.assertIn(("pushed", "to", "*"), s.habit_index())


class SeedBudgetTests(unittest.TestCase):
    """183 of the 200 learned slots on Ryan's PC were starter terms at count
    40-50, so every newly promoted phrase (count 4) was pruned on arrival."""

    def _seed(self, store, n, at="2026-10-26T15:02:33+00:00"):
        for k in range(n):
            store._phrases[f"seedterm{k}"] = {
                "phrase": f"Seedterm{k}", "count": 50, "learned_at": at}
        store._prune()

    def test_a_new_phrase_survives_a_full_seed(self):
        s = pl.PhraseStore("a@b.c", directory=tempfile.mkdtemp())
        self._seed(s, pl.MAX_PHRASES + 50)
        for _ in range(pl.PROMOTE_COUNT):
            s.observe("the lead finder is open", _conf("the lead finder is open", 0.95))
        self.assertIn("lead finder", [r["phrase"] for r in s.phrases()])
        self.assertEqual(len([r for r in s.phrases() if r.get("seeded")]),
                         pl.MAX_PHRASES + 50)

    def test_seeded_flag_survives_cloud_sync_merge(self):
        s = pl.PhraseStore("a@b.c", directory=tempfile.mkdtemp())
        self._seed(s, 25)
        merged = cloud_sync.merge_phrases(s.snapshot(), {})
        self.assertTrue(all(r.get("seeded") for r in merged["phrases"]))

    def test_a_small_real_batch_is_not_mistaken_for_a_seed(self):
        s = pl.PhraseStore("a@b.c", directory=tempfile.mkdtemp())
        for k in range(5):
            s._phrases[f"real{k}"] = {"phrase": f"real{k}", "count": 45,
                                      "learned_at": "2026-11-01T10:00:00+00:00"}
        s._prune()
        self.assertFalse(any(r.get("seeded") for r in s.phrases()))


@unittest.skipUnless(HAVE_DM, "metaphone not installed")
class SpeedTests(unittest.TestCase):
    def test_a_long_dictation_with_a_full_store_stays_cheap(self):
        habits = dict(HABITS)
        for k in range(300):
            habits[f"deploy widget{k} to production"] = 10
        index = pl.build_habit_index(habits)
        text = ("so I think we should push everything to mean and then check "
                "the dashboard again before lunch ") * 40      # ~720 words
        conf = _conf(text, 0.6)
        start = time.perf_counter()
        pl.apply_habits(text, habits, conf, index)
        self.assertLess(time.perf_counter() - start, 0.25)


class WiringTests(unittest.TestCase):
    def test_app_repairs_habits_before_learning_and_snippets(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "app.py"), encoding="utf-8").read()
        a = src.index("phrase_learning.apply_habits(")
        self.assertLess(src.index("phrase_learning.apply_learned_phrases("), a)
        self.assertLess(a, src.index("store.observe(fixed, word_conf)"))
        self.assertLess(a, src.index('apply_snippets(fixed, self._user_entries("snippets"))'))


if __name__ == "__main__":
    unittest.main()
