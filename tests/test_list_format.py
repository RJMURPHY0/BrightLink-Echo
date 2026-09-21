"""Spoken lists.

Reported with a live example: "Right, so here's a list of three things. first
is like the first thing, second is the second thing." should come out as a
numbered list under a colon.

This changes the SHAPE of what the user said, so both directions are pinned.
The false-negative cases (a clear list stays as prose) are the reported want;
the false-positive cases are the worse regression, because ordinary speech is
full of "first of all" and comma series. The corpus test at the end fails if
any real transcript without an enumeration is ever restructured.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import list_format
from list_format import format_lists as fmt


class NumberedTests(unittest.TestCase):
    def test_the_reported_example(self):
        self.assertEqual(
            fmt("Right, so here's a list of three things. first is like the "
                "first thing, second is the second thing."),
            "Right, so here's a list of three things:\n\n"
            "1. First is like the first thing.\n"
            "2. Second is the second thing.")

    def test_bare_discourse_markers_are_absorbed_by_the_number(self):
        self.assertEqual(
            fmt("There are three things I need to do. First, push the release. "
                "Second, update the docs. Third, tell Ryan."),
            "There are three things I need to do:\n\n"
            "1. Push the release\n2. Update the docs\n3. Tell Ryan")

    def test_a_marker_that_is_part_of_the_sentence_is_kept(self):
        # "1. Is the first thing" would be worse than a little redundancy.
        out = fmt("Here are the two things. first is the colour of the box, "
                  "second is the size of it.")
        self.assertIn("1. First is the colour of the box", out)

    def test_ly_forms(self):
        out = fmt("There are three reasons. Firstly, it is faster. Secondly, "
                  "it is cheaper. Thirdly, it is simpler.")
        self.assertIn("1. It is faster", out)
        self.assertIn("3. It is simpler", out)

    def test_number_one_style(self):
        out = fmt("There are three things to fix. Number one, the login page. "
                  "Number two, the search bar. Number three, the footer.")
        self.assertIn("1. The login page", out)
        self.assertIn("3. The footer", out)

    def test_finally_closes_a_run_but_never_starts_one(self):
        out = fmt("There are three steps. First, open it. Second, edit it. "
                  "Finally, save it.")
        self.assertIn("3. Save it", out)
        s = "Finally I got the thing working after all that effort."
        self.assertEqual(fmt(s), s)

    def test_text_after_the_list_becomes_its_own_paragraph(self):
        out = fmt("There are two reasons for this. First, it is faster. "
                  "Second, it is cheaper. Then we can move on to the next bit.")
        self.assertTrue(out.endswith("\n\nThen we can move on to the next bit."))
        self.assertIn("2. It is cheaper", out)

    def test_three_markers_need_no_announcement(self):
        out = fmt("First, wake up. Second, get dressed. Third, leave the house.")
        self.assertEqual(out, "1. Wake up\n2. Get dressed\n3. Leave the house")

    def test_the_2026_09_21_number_one_example(self):
        # Reported against a competitor's output: the joining "so," goes, the
        # lead-in takes the colon, and "number one" is carried by the "1.".
        self.assertEqual(
            fmt("So, I want to start a list for a few things that I want to "
                "do, so, number one, I want to have good CPU energy. Number "
                "two, I want to have good GPU energy."),
            "So, I want to start a list for a few things that I want to do:"
            "\n\n1. I want to have good CPU energy."
            "\n2. I want to have good GPU energy.")

    def test_the_2026_09_21_and_number_two_example(self):
        # Second report, same evening: "and number two" came with no comma in
        # front of it, so only "number one" was found and nothing happened.
        # Sentence items take a full stop, as the competitor's output did.
        self.assertEqual(
            fmt("So I just want to list a few things, so number one, I want to "
                "just think about one thing and number two i want to think "
                "about another thing"),
            "So I just want to list a few things:\n\n"
            "1. I want to just think about one thing.\n"
            "2. I want to think about another thing.")

    def test_a_slot_said_twice_counts_once(self):
        # Real dictation: "first" and then "number one" for the same item.
        out = fmt("So, I want to have a list, so, first, so like number one, I "
                  "want to have a few different things. Number two, I want to "
                  "have a few other things.")
        self.assertEqual(
            out, "So, I want to have a list:\n\n"
                 "1. I want to have a few different things.\n"
                 "2. I want to have a few other things.")

    def test_for_number_two_leaves_no_dangling_for(self):
        out = fmt("So, I just want to list a few things, so, firstly, I want "
                  "to have this one thing, you know, for number two I want to "
                  "have the second thing")
        self.assertIn("1. I want to have this one thing, you know.\n", out)
        self.assertIn("2. I want to have the second thing.", out)

    def test_the_first_thing_is_the_second_thing_is(self):
        self.assertEqual(
            fmt("There are two things to check, the first thing is the login "
                "page and the second thing is the search bar."),
            "There are two things to check:\n\n"
            "1. The login page\n2. The search bar")

    def test_bare_space_markers_need_an_announcement(self):
        for s in ("We scored number one in the league and number two in the "
                  "cup this year.",
                  "The first thing I noticed was the colour, and the second "
                  "thing I noticed was the size of it.",
                  "I came first and second in the two races this year, which "
                  "was great."):
            self.assertEqual(fmt(s), s)

    def test_number_markers_written_as_digits(self):
        out = fmt("Here are the jobs, number 1, fix the login page. Number 2, "
                  "update the search bar.")
        self.assertIn("\n\n1. Fix the login page\n2. Update the search bar", out)

    def test_two_explicit_number_markers_need_no_announcement(self):
        self.assertEqual(
            fmt("Number one, fix the login page. Number two, update the "
                "search bar."),
            "1. Fix the login page\n2. Update the search bar")

    def test_number_one_inside_a_sentence_is_prose(self):
        for s in ("My number one priority is the release. Then number two on "
                  "the list is docs.",
                  "We scored number one in the league this year and it was "
                  "great."):
            self.assertEqual(fmt(s), s)

    def test_two_markers_without_an_announcement_are_left_alone(self):
        s = ("First of all, thanks very much for coming along today. Second, "
             "let us make a start on the agenda.")
        self.assertEqual(fmt(s), s)


class SpokenBulletTests(unittest.TestCase):
    def test_bullet_point_one_two_three(self):
        self.assertEqual(
            fmt("Things to pack for the trip. Bullet point one, a warm coat. "
                "Bullet point two, some walking boots. Bullet point three, the "
                "travel adapters."),
            "Things to pack for the trip.\n\n- A warm coat\n"
            "- Some walking boots\n- The travel adapters")

    def test_bare_and_next_bullet_point(self):
        self.assertEqual(
            fmt("Here is what I need, bullet point, the new laptop charger. "
                "Next bullet point, a spare mouse for the office."),
            "Here is what I need:\n\n- The new laptop charger\n"
            "- A spare mouse for the office")

    def test_the_2026_09_21_first_bullet_point_is_example(self):
        # Reported against a competitor's output: "the first bullet point is"
        # was not a phrasing the formatter knew, and "and the second" had no
        # comma in front of it. Labels take no full stop.
        self.assertEqual(
            fmt("I just want to list a couple things, so the first bullet point "
                "is CPU energy and the second bullet point is GPU energy"),
            "I just want to list a couple things:\n\n- CPU energy\n- GPU energy")

    def test_bullets_and_numbers_never_mix(self):
        out = fmt("Here are two things. Bullet point one, a warm coat. Number "
                  "two, some walking boots.")
        self.assertNotIn("1.", out)
        self.assertNotIn("\n- ", out)


class BulletTests(unittest.TestCase):
    def test_announced_series(self):
        self.assertEqual(fmt("Here are the three things I need: milk, bread "
                             "and eggs."),
                         "Here are the three things I need:\n\n"
                         "- Milk\n- Bread\n- Eggs")

    def test_oxford_comma(self):
        out = fmt("We need the following. Milk, bread, and eggs.")
        self.assertEqual(out.count("\n- "), 3)

    def test_or_series(self):
        out = fmt("There are three options here: keep it, change it or drop it.")
        self.assertEqual(out.count("\n- "), 3)

    def test_long_items_are_prose_not_bullets(self):
        s = ("Here are the three things I need: a really long and detailed "
             "explanation of the first item, bread and eggs.")
        self.assertEqual(fmt(s), s)

    def test_two_item_series_is_not_a_list(self):
        s = "Here are the two things I need: milk and bread."
        self.assertEqual(fmt(s), s)


class FalsePositiveTests(unittest.TestCase):
    """Ordinary speech. Nothing here may be restructured."""

    def test_plain_comma_series(self):
        for s in ("I went to the shop, the bank and home.",
                  "We use Python, tkinter and PyInstaller for this.",
                  "It was cold, wet and windy all day."):
            self.assertEqual(fmt(s), s)

    def test_discursive_ordinals(self):
        for s in ("First of all I want to say thank you for everything.",
                  "The first thing I noticed was the colour, which was odd.",
                  "He came second in the race and I came third overall.",
                  "That was my first attempt at doing it this way."):
            self.assertEqual(fmt(s), s)

    def test_short_utterances_are_never_touched(self):
        for s in ("First, do it.", "Yes please", "one moment"):
            self.assertEqual(fmt(s), s)

    def test_already_formatted_text_is_left_alone(self):
        s = "Here are three things:\n\n1. One thing\n2. Another thing"
        self.assertEqual(fmt(s), s)
        s2 = "Here are three things:\n\n- One thing\n- Another thing"
        self.assertEqual(fmt(s2), s2)

    def test_items_shorter_than_two_words_block_the_list(self):
        s = "There are three things. First, no. Second, yes. Third, maybe."
        self.assertEqual(fmt(s), s)

    def test_empty_and_none(self):
        self.assertEqual(fmt(""), "")
        self.assertEqual(fmt(None), None)


class WiringTests(unittest.TestCase):
    """It must run ONCE, on the whole utterance, at app.py's post-processing
    point — never inside an engine, which also sees streamed chunks and live
    captions, and never while Live Typing is on."""

    def _src(self, name):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), name)
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_applied_in_app_not_in_an_engine(self):
        app = self._src("app.py")
        self.assertIn("format_lists(transcribed_text)", app)
        for engine in ("asr_engine.py", "transcriber.py", "stream_session.py"):
            self.assertNotIn("list_format", self._src(engine))

    def test_gated_on_the_setting_and_on_live_typing(self):
        app = self._src("app.py")
        block = app[app.index('getattr(self.config, "auto_lists"'):]
        block = block[:block.index("format_lists(transcribed_text)")]
        self.assertIn('getattr(self.config, "live_inject", False)', block)

    def test_runs_before_the_user_libraries(self):
        # A snippet BODY is verbatim and must never be re-shaped.
        app = self._src("app.py")
        self.assertLess(app.index("format_lists(transcribed_text)"),
                        app.index("self._apply_user_libraries(transcribed_text,"))

    def test_default_on_in_config(self):
        self.assertIn("auto_lists: bool = True", self._src("config.py"))


class CorpusRegressionTests(unittest.TestCase):
    """Every real stored transcript. Anything without an enumeration or an
    announced series must come back byte-identical."""

    def _load(self):
        path = os.path.join(os.environ.get("APPDATA", ""), "FTC Whisper",
                            "history.json")
        if not os.path.exists(path):
            self.skipTest("no local history.json corpus on this machine")
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        return [t for t in (r.get("transcribed_text", "") for r in rows)
                if t and t.strip()]

    def test_only_enumerated_transcripts_are_restructured(self):
        offenders = []
        for text in self._load():
            out = fmt(text)
            if out == text:
                continue
            # A change is only legitimate where the source announced a list and
            # carried the markers this feature keys off.
            if (list_format._ANNOUNCE.search(text)
                    and list_format._MARKER_RE.search(text)):
                continue
            # Or where it said "number one … number two" / "bullet point one".
            if any(mk["kind"] in ("num", "bullet")
                   for mk in list_format._markers(text)):
                continue
            offenders.append((text[:120], out[:120]))
        self.assertEqual(offenders, [],
                         f"{len(offenders)} corpus transcript(s) restructured "
                         "without an announced enumeration")

    def test_no_words_are_lost(self):
        """The only deletion allowed is a bare discourse marker and the
        punctuation the number replaces."""
        import re
        allowed = set(list_format._ORDINALS) | {"and", "or"}
        allowed |= {w for c in list_format._CLOSERS for w in c.split()}
        allowed |= {"number"} | set(list_format._NUMBER_WORDS)
        allowed |= {"bullet", "point", "next", "another", "new", "the", "is",
                    "would", "will", "be", "thing", "item", "one", "step",
                    "reason", "last", "final", "for", "like"}
        allowed |= {"then", "also", "but", "so", "now", "okay", "ok", "right"}
        for text in self._load():
            out = fmt(text)
            if out == text:
                continue
            before = re.findall(r"[a-z']+", text.lower())
            after = re.findall(r"[a-z']+", out.lower())
            from collections import Counter
            lost = Counter(before) - Counter(after)
            self.assertFalse(set(lost) - allowed,
                             f"words lost that are not list markers: {lost}")
            self.assertFalse(Counter(after) - Counter(before),
                             "words invented")


class RefinerInteractionTests(unittest.TestCase):
    """The refiner bans lists so the model never invents one. Once the app can
    PRODUCE a list, that ban would flatten its own output on the first refine."""

    def test_existing_list_is_detected(self):
        import ai_refiner
        self.assertTrue(ai_refiner._looks_like_a_list(
            "Here are three:\n\n1. One thing\n2. Two thing"))
        self.assertTrue(ai_refiner._looks_like_a_list(
            "Here are three:\n\n- Milk\n- Bread"))
        self.assertFalse(ai_refiner._looks_like_a_list(
            "Ordinary prose. 1.5 million people, no list here."))

    def test_context_fix_refuses_a_result_that_flattened_the_list(self):
        import ai_refiner
        r = ai_refiner.AIRefiner.__new__(ai_refiner.AIRefiner)
        listed = ("Here are three things:\n\n1. One thing\n2. Two thing\n"
                  "3. Three thing")
        r.refine = lambda text, mode=None: " ".join(listed.split())
        self.assertEqual(r.context_fix(listed), listed)

    def test_source_keeps_the_preserve_clause(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "ai_refiner.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("_looks_like_a_list(text)", src)
        self.assertIn("Do not turn it back into", src)


if __name__ == "__main__":

    unittest.main()
