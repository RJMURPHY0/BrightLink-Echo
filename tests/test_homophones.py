"""Sound-alike words picked from the rest of the sentence.

Asked for with a real dictation (2026-09-29): "Revenue won this quarter" came
out as "Revenue one this quarter" (whisper small.en) and "Revenue One this
quarter" (Parakeet), while a competitor typed "won". The words around it make
it the verb, so the app should too.

These tests pin BOTH directions. The fix cases are the reported want; the
must-not-fire cases are the worse regression, because this code rewrites words
the user genuinely said. Every must-not-fire case below is a legitimate
reading of the same shape as a rule, which is why the rules need evidence on
both sides of the word.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import homophones


class Base(unittest.TestCase):
    def fixes(self, cases):
        for src, want in cases:
            self.assertEqual(homophones.fix(src), want, src)

    def keeps(self, cases):
        for src in cases:
            self.assertEqual(homophones.fix(src), src, src)


class ReportedCaseTests(Base):

    def test_the_reported_dictation_both_engines(self):
        self.fixes([
            ("Revenue one this quarter.", "Revenue won this quarter."),
            # Parakeet capitalised the mis-picked word as if it were a name;
            # that capital is the mistake and must not survive.
            ("Revenue One this quarter.", "Revenue won this quarter."),
        ])

    def test_same_shape_other_sales_nouns(self):
        self.fixes([
            ("Deals one so far this year", "Deals won so far this year"),
            ("new business one since March", "new business won since March"),
            ("clients one against Acme", "clients won against Acme"),
            ("Tenders one in Q3 were up", "Tenders won in Q3 were up"),
        ])

    def test_enumerations_are_not_the_verb(self):
        self.keeps([
            "Phase one this quarter.",
            "We're shipping deal one this week.",
            "Step one today, step two tomorrow.",
            "We lost two customers one this week and one last week.",
            "We lost two customers one this week.",
            "Two new clients one since Monday.",
        ])


class OneWonTests(Base):

    def test_subject_pronoun(self):
        self.fixes([
            ("We one the Acme tender.", "We won the Acme tender."),
            ("I think they one it.", "I think they won it."),
            ("She one.", "She won."),
        ])

    def test_subject_pronoun_counts_and_pronouns_stay(self):
        self.keeps([
            "Is she one of them?",
            "Am I one?",
            "Are we one team or two?",
            "We one day decided to leave.",
            "I one time went there.",
            "They one by one left the room.",
            "Did we one?",
            "I owe you one.",
            "Can you give me one the same colour?",
        ])

    def test_have_plus_object(self):
        self.fixes([
            ("We have one the contract", "We have won the contract"),
            ("they've one three awards", "they've won three awards"),
            ("she has one it twice", "she has won it twice"),
            ("We've finally one the tender", "We've finally won the tender"),
        ])

    def test_have_one_as_a_count_stays(self):
        self.keeps([
            "I have one.",
            "Can I have one back?",
            "I had one the other day.",
            "I had one again this morning.",
            "I have one every day.",
            "We have one this week.",
            "We have one the whole time.",
            "Do you have one the size of a phone?",
            "I have one deal left.",
            "We have one more to go.",
        ])

    def test_margin_and_outcome_pairs(self):
        self.fixes([
            ("It was one by a landslide", "It was won by a landslide"),
            ("how many deals were one or lost", "how many deals were won or lost"),
            ("deals lost and one", "deals lost and won"),
        ])
        self.keeps(["one by one", "one by the window"])

    def test_closed_won_stage(self):
        self.fixes([
            ("move it to closed one", "move it to closed won"),
            ("Marked as Closed One.", "Marked as Closed Won."),
            ("closed one and closed lost", "closed won and closed lost"),
        ])
        self.keeps(["I closed one yesterday.", "We closed one this week."])

    def test_won_to_one(self):
        self.fixes([
            ("won of the best", "one of the best"),
            ("No won knows.", "No one knows."),
            ("this won is better", "this one is better"),
        ])
        self.keeps([
            "We won of course.",
            "There were no won deals this month.",
            "The bid that won.",
            "This won us the deal.",
            "We won more time.",
        ])


class OtherPairTests(Base):

    def test_than(self):
        self.fixes([
            ("more then a hundred", "more than a hundred"),
            ("better then ever", "better than ever"),
            ("other then that it's fine", "other than that it's fine"),
            ("bigger then expected", "bigger than expected"),
        ])
        self.keeps([
            "See you later then.",
            "Add a bit more then save it.",
            "We'll call each other then.",
            "It gets bigger then smaller.",
            "If we get more then we can start.",
        ])

    def test_modal_of(self):
        self.fixes([("I should of done it", "I should have done it"),
                    ("it could of been worse", "it could have been worse")])
        self.keeps(["In May of last year", "what should of course happen"])

    def test_whether(self):
        self.fixes([("weather or not", "whether or not"),
                    ("I don't know weather we should go", "I don't know whether we should go")])
        self.keeps(["The weather or not much else.", "The weather we had was awful.",
                    "Nice weather we're having."])

    def test_your_youre(self):
        self.fixes([
            ("your going to love it", "you're going to love it"),
            ("your not wrong", "you're not wrong"),
            ("Thanks. Your welcome.", "Thanks. You're welcome."),
            ("do it you're own way", "do it your own way"),
            ("thanks for you're feedback", "thanks for your feedback"),
        ])
        self.keeps([
            "Send your welcome email.",
            "your not-for-profit arm",
            "It's your right to ask.",
            "you're team lead now",
            "you're account manager for Acme",
            "you're number one",
            "your going-away party",
        ])

    def test_its(self):
        self.fixes([("its the newest one", "it's the newest one"),
                    ("its been a while", "it's been a while"),
                    ("it has it's own page", "it has its own page")])
        self.keeps(["its own page", "its really good battery life",
                    "in its time", "its fine print", "its going rate"])

    def test_there_their(self):
        self.fixes([("Their is a problem", "There is a problem"),
                    ("their will be a delay", "there will be a delay"),
                    ("they have there own team", "they have their own team")])
        self.keeps(["their team is great", "Is there going to be a demo?",
                    "Are there all kinds of options?", "over there"])

    def test_too(self):
        self.fixes([("It's way to expensive", "It's way too expensive"),
                    ("that is to late", "that is too late"),
                    ("not to bad", "not too bad")])
        self.keeps([
            "The plan is to close the deal.",
            "The aim is to slow the spread.",
            "The goal is to short the stock.",
            "I went to many places.",
            "we're getting to many customers now",
            "way to go",
            "the idea was to hard-code it",
        ])

    def test_write_right(self):
        self.fixes([
            ("Right an email to John", "Write an email to John"),
            ("can you right me a summary", "can you write me a summary"),
            ("right that down", "write that down"),
        ])
        self.keeps([
            "All right the report is done.",
            "That's right an email came in.",
            "Yeah right a note would help.",
            "Turn right a letter box is there.",
            "right a wrong",
            "right down the road",
            "I'll write now",
        ])

    def test_hear_here(self):
        self.fixes([("I can't here you", "I can't hear you"),
                    ("looking forward to here from you", "looking forward to hear from you"),
                    ("come in hear.", "come in hear.".replace("hear", "here"))])
        self.keeps(["Are you here about the job?", "from there to here it takes an hour",
                    "fly to here from London", "come hear the band"])

    def test_know_no(self):
        self.fixes([("let me no", "let me know"), ("I don't no", "I don't know"),
                    ("you no what", "you know what")])
        self.keeps(["I no longer work there", "let me no longer wait",
                    "don't no matter what"])

    def test_week_weak(self):
        self.fixes([("see you next weak.", "see you next week."),
                    ("a weak ago", "a week ago"), ("two weaks ago", "two weeks ago")])
        self.keeps(["this weak argument", "the last weak point", "every weak link"])

    def test_fixed_phrases(self):
        self.fixes([
            ("for piece of mind", "for peace of mind"),
            ("a peace of code", "a piece of code"),
            ("out of site.", "out of sight."),
            ("don't lose site of it", "don't lose sight of it"),
            ("role out the update", "roll out the update"),
            ("a great roll model", "a great role model"),
            ("we're on a role today", "we're on a roll today"),
            ("the hole team", "the whole team"),
            ("bare with me", "bear with me"),
            ("in the passed.", "in the past."),
            ("take a brake", "take a break"),
            ("Wear is the file?", "Where is the file?"),
        ])
        self.keeps([
            "which role out of these",
            "take on a role that suits you",
            "check the brake pads",
            "dig the hole deeper",
            "What to wear is up to you.",
            "the dice roll",
        ])


class MechanicsTests(Base):

    def test_punctuation_is_the_speakers_boundary(self):
        # A comma or stop between the words ends the shape.
        self.keeps(["Revenue, one this quarter.", "We, one the deal",
                    "we have one, the contract"])

    def test_spacing_and_line_breaks_kept(self):
        src = "Hi John,\n\nRevenue one this quarter.\n\nKind regards,\nRyan"
        self.assertEqual(homophones.fix(src),
                         "Hi John,\n\nRevenue won this quarter.\n\nKind regards,\nRyan")

    def test_sentence_start_and_all_caps(self):
        self.fixes([("Their is one.", "There is one."),
                    ("THEIR IS A BUG", "THERE IS A BUG")])

    def test_not_inside_paths_or_handles(self):
        self.keeps(["open /revenue one this", "tag #their is"])

    def test_empty_and_untouched(self):
        self.assertEqual(homophones.fix(""), "")
        self.keeps(["Hello, my name is Ryan. This is a test."])

    def test_reports_rule_names_without_text(self):
        seen = []
        homophones.set_reporter(lambda ev, d: seen.append((ev, d)))
        try:
            homophones.fix("Revenue one this quarter.", source="assembled")
        finally:
            homophones.set_reporter(None)
        self.assertEqual(seen, [("transcribe_homophone",
                                 {"source": "assembled",
                                  "rules": ["won_after_sales_noun"],
                                  "count": 1})])

    def test_fast_on_a_long_dictation(self):
        # Runs on the stop-to-text path: a 700-word dictation must stay far
        # below anything a person could notice.
        text = ("Okay so we had a really good quarter and I think revenue "
                "one this quarter is up on last year, but there is more then "
                "one thing to do. ") * 25
        t0 = time.perf_counter()
        homophones.fix(text)
        self.assertLess(time.perf_counter() - t0, 0.05)


if __name__ == "__main__":
    unittest.main()
