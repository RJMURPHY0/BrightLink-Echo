"""Spoken emoji: "<name> emoji" becomes the emoji.

Ryan's ask (24 Nov 2026): "say like smiling face emoji or like laughing face
emoji ... or like star emoji, literally any emoji". Both directions are pinned:
names turn into emoji, and prose that only talks ABOUT emoji stays as said.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoken_commands import apply_spoken_commands as sc
from spoken_emoji import apply_spoken_emoji as se, lookup

SMILE, LAUGH, STAR = "\U0001F60A", "\U0001F602", "⭐️"


class NamesBecomeEmoji(unittest.TestCase):

    def test_the_reported_dictation(self):
        said = ("For Echo, I actually think it could be quite cool if you could "
                "say like smiling face emoji or like laughing face emoji, stuff "
                "like that, or like star emoji, things like literally any emoji")
        self.assertEqual(
            sc(said),
            f"For Echo, I actually think it could be quite cool if you could "
            f"say like {SMILE} or like {LAUGH}, stuff like that, or like "
            f"{STAR}, things like literally any emoji")

    def test_everyday_names(self):
        for said, want in [
            ("laughing face emoji", LAUGH), ("smiling face emoji", SMILE),
            ("star emoji", STAR), ("thumbs up emoji", "\U0001F44D"),
            ("heart emoji", "❤️"), ("fire emoji", "\U0001F525"),
            ("crying laughing emoji", LAUGH), ("party popper emoji", "\U0001F389"),
            ("uk flag emoji", "\U0001F1EC\U0001F1E7"), ("t-rex emoji", "\U0001F996"),
        ]:
            with self.subTest(said=said):
                self.assertEqual(sc(said), want)

    def test_any_emoji_by_its_unicode_name(self):
        for said, want in [
            ("face with rolling eyes emoji", "\U0001F644"),
            ("rocket emoji", "\U0001F680"),
            ("thinking emoji", "\U0001F914"),          # + " face"
            ("ok hand emoji", "\U0001F44C"),
            ("smiling face with sunglasses emoji", "\U0001F60E"),
            ("heavy dollar sign emoji", "\U0001F4B2"),  # before the $ rule
        ]:
            with self.subTest(said=said):
                self.assertEqual(sc(said), want)

    def test_only_the_name_is_replaced(self):
        self.assertEqual(sc("that's hilarious laughing face emoji"),
                         f"that's hilarious {LAUGH}")
        self.assertEqual(sc("a big laughing face emoji"), f"a big {LAUGH}")
        self.assertEqual(sc("Thanks so much, heart emoji, see you Friday"),
                         "Thanks so much, ❤️, see you Friday")

    def test_two_in_a_row(self):
        self.assertEqual(sc("pizza emoji ok hand emoji"), "\U0001F355 \U0001F44C")
        self.assertEqual(sc("fire emoji fire emoji"), "\U0001F525 \U0001F525")

    def test_case_and_plural(self):
        self.assertEqual(sc("Laughing face emoji. Anyway"), f"{LAUGH}. Anyway")
        self.assertEqual(se("star emojis"), STAR)


class ProseStaysAsSaid(unittest.TestCase):

    def test_talking_about_emoji(self):
        for said in ["I sent an emoji", "I would like emoji in Echo",
                     "I love emoji", "Do you use emojis", "custom emoji",
                     "new emoji", "more emoji", "some emoji", "random emoji",
                     "this emoji", "your emoji", "any emoji", "no emoji",
                     "add emoji", "emoji", "the Windows emoji thing",
                     "a good kind of library of like emojis"]:
            with self.subTest(said=said):
                self.assertEqual(se(said), said)

    def test_only_emoji_code_points(self):
        # A Unicode name that is not an emoji never comes back as a character.
        self.assertIsNone(lookup("latin capital letter a"))
        self.assertIsNone(lookup("letter a"))
        self.assertEqual(se("letter a emoji"), "letter a emoji")

    def test_no_trigger_no_change(self):
        for said in ["the star of the show", "laughing face to face",
                     "thumbs up from me", "set the house on fire"]:
            with self.subTest(said=said):
                self.assertEqual(se(said), said)

    def test_real_dictations_only_change_at_a_named_emoji(self):
        try:
            import data_paths
            path = os.path.join(data_paths.roaming_dir(), "history.json")
        except Exception:
            path = ""
        if not path or not os.path.exists(path):
            self.skipTest("no local history.json corpus on this machine")
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
        for it in items:
            text = it.get("transcribed_text") or ""
            out = se(text)
            if out == text:
                continue
            # Every change removes the word "emoji" it was triggered by.
            self.assertLess(out.lower().count("emoji"), text.lower().count("emoji"),
                            text)


if __name__ == "__main__":
    unittest.main()
