"""Fix words: a corrected dictation teaches Echo the mishearing, and only that."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vocab_store
import word_fixes
from text_expansion import apply_vocabulary


class FakeConfig:
    def __init__(self):
        self.vocabulary = {}
        self.snippets = {}

    def save_async(self):
        pass


def learned(old, new):
    return [(l["heard"], l["term"]) for l in word_fixes.learn(old, new)["learned"]]


def skipped(old, new):
    return [(s["heard"], s["term"], s["why"])
            for s in word_fixes.learn(old, new)["skipped"]]


class LearnTests(unittest.TestCase):

    def test_a_misheard_name_is_learned(self):
        self.assertEqual(
            [("UNICEF", "Uniserve")],
            learned("Remind me to email UNICEF after lunch.",
                    "Remind me to email Uniserve after lunch."))

    def test_a_split_and_merge_is_one_lesson(self):
        self.assertEqual(
            [("Fear and", "Fearon")],
            learned("I spoke to James Fear and this morning.",
                    "I spoke to James Fearon this morning."))
        self.assertEqual(
            [("Tick Sparkley", "TEDx Berkeley")],
            learned("Tick Sparkley asked for a quote.",
                    "TEDx Berkeley asked for a quote."))

    def test_several_fixes_in_one_edit(self):
        self.assertEqual(
            [("Pharnes", "Phil Barnes"), ("Lester", "Leicester")],
            learned("Please add Pharnes from Lester to the meeting.",
                    "Please add Phil Barnes from Leicester to the meeting."))

    def test_a_casing_fix_teaches_the_capitals(self):
        self.assertEqual([(None, "BrightLink")],
                         learned("I use brightlink every day.",
                                 "I use BrightLink every day."))

    def test_punctuation_teaches_nothing(self):
        out = word_fixes.learn("send it today", "Send it, today.")
        self.assertEqual([], out["learned"])

    def test_a_changed_mind_is_not_a_mishearing(self):
        self.assertEqual([], learned("Let's meet on Monday at ten.",
                                     "Let's meet on Tuesday at ten."))
        self.assertIn(("Monday", "Tuesday", "not a mishearing"),
                      skipped("Let's meet on Monday at ten.",
                              "Let's meet on Tuesday at ten."))

    def test_near_misses_of_a_changed_mind_are_not_learned(self):
        for old, new in (("See you on Friday then.", "See you on Thursday then."),
                         ("It takes ten minutes.", "It takes two minutes."),
                         ("Send the report today.", "Send the proposal today.")):
            with self.subTest(new=new):
                self.assertEqual([], learned(old, new))

    def test_a_name_lower_cased_mid_sentence_is_learned_not_a_sentence_start(self):
        self.assertEqual([(None, "Jason")],
                         learned("Ask jason about it.", "Ask Jason about it."))
        self.assertEqual([], learned("thanks. send it", "Thanks. Send it"))

    def test_everyday_words_never_become_a_rule(self):
        self.assertEqual([], learned("I think the sale is on.",
                                     "I think the sail is on."))

    def test_numbers_are_data_not_sounds(self):
        self.assertEqual([], learned("Call me on 0116 234",
                                     "Call me on 0116 243"))

    def test_a_rewrite_teaches_nothing(self):
        out = word_fixes.learn("Can you send it over by Friday please",
                               "Never mind, I will drop it round myself tomorrow")
        self.assertEqual([], out["learned"])
        self.assertEqual("rewrite", out["skipped"][0]["why"])

    def test_added_or_removed_words_teach_nothing(self):
        self.assertEqual([], learned("Send it to Jason.",
                                     "Send it to Jason and Lee."))


class ApplyTests(unittest.TestCase):

    def setUp(self):
        self.cfg = FakeConfig()

    def entries(self):
        return vocab_store.load(self.cfg, "vocabulary", "ryan@x.com")

    def test_a_new_term_is_added_and_used_on_the_next_dictation(self):
        word_fixes.apply_learned(self.cfg, [{"heard": "UNICEF", "term": "Uniserve"}],
                                 "ryan@x.com")
        [e] = self.entries()
        self.assertEqual(("Uniserve", ["UNICEF"]), (e["term"], e["sounds_like"]))
        self.assertEqual("Email Uniserve today",
                         apply_vocabulary("Email UNICEF today", self.entries()))

    def test_an_existing_term_gains_the_mishearing(self):
        vocab_store.upsert(self.cfg, "vocabulary",
                           vocab_store.new_entry(term="Uniserve", sounds_like=["unisurf"]),
                           "ryan@x.com")
        word_fixes.apply_learned(self.cfg, [{"heard": "UNICEF", "term": "uniserve"}],
                                 "ryan@x.com")
        [e] = self.entries()
        self.assertEqual(["unisurf", "UNICEF"], e["sounds_like"])

    def test_the_same_lesson_twice_changes_nothing(self):
        lesson = [{"heard": "UNICEF", "term": "Uniserve"}]
        word_fixes.apply_learned(self.cfg, lesson, "ryan@x.com")
        undo = word_fixes.apply_learned(self.cfg, lesson, "ryan@x.com")
        self.assertEqual([], undo)
        self.assertEqual(1, len(self.entries()))

    def test_undo_puts_everything_back(self):
        vocab_store.upsert(self.cfg, "vocabulary",
                           vocab_store.new_entry(term="Uniserve", sounds_like=["unisurf"]),
                           "ryan@x.com")
        undo = word_fixes.apply_learned(
            self.cfg, [{"heard": "UNICEF", "term": "Uniserve"},
                       {"heard": "Lester", "term": "Leicester"}], "ryan@x.com")
        word_fixes.undo_learned(self.cfg, undo, "ryan@x.com")
        self.assertEqual([("Uniserve", ["unisurf"])],
                         [(e["term"], e["sounds_like"]) for e in self.entries()])

    def test_summary_is_one_short_line(self):
        self.assertEqual("Learned: UNICEF → Uniserve (+1 more)",
                         word_fixes.summary([{"heard": "UNICEF", "term": "Uniserve"},
                                             {"heard": None, "term": "BrightLink"}]))
        self.assertEqual("Learned: writes BrightLink",
                         word_fixes.summary([{"heard": None, "term": "BrightLink"}]))


if __name__ == "__main__":
    unittest.main()
