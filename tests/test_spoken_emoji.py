"""Spoken emoji: "<name> emoji" becomes the emoji.

Ryan's ask (24 Nov 2026): "say like smiling face emoji or like laughing face
emoji ... or like star emoji, literally any emoji". Both directions are pinned:
names turn into emoji, and prose that only talks ABOUT emoji stays as said.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoken_commands import apply_spoken_commands as sc
from spoken_emoji import apply_spoken_emoji as se, lookup

SMILE, LAUGH, STAR = "😊", "😂", "⭐"


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


class EveryOfficialEmoji(unittest.TestCase):
    """Ryan (24 Nov 2026): "make sure absolutely all emojis work"."""

    def test_every_official_name_turns_into_its_emoji(self):
        from emoji_names import NAMES
        from spoken_emoji import _ALIASES
        self.assertGreater(len(NAMES), 4000)
        bad = [k for k, v in NAMES.items()
               if k not in _ALIASES and se(f"{k} emoji") != v]
        self.assertEqual(bad, [])

    def test_every_official_name_works_mid_sentence(self):
        from emoji_names import NAMES
        from spoken_emoji import _ALIASES
        bad = [k for k, v in NAMES.items() if k not in _ALIASES
               and sc(f"Great news {k} emoji see you soon")
               != f"Great news {v} see you soon"]
        self.assertEqual(bad, [])

    def test_flags_skin_tones_keycaps_and_joined(self):
        for said, want in [
            ("united kingdom flag emoji", "\U0001F1EC\U0001F1E7"),
            ("flag: France emoji", "\U0001F1EB\U0001F1F7"),
            ("Côte d'Ivoire flag emoji", "\U0001F1E8\U0001F1EE"),
            ("thumbs up medium skin tone emoji", "\U0001F44D\U0001F3FD"),
            ("thumbs up, medium skin tone emoji", "\U0001F44D\U0001F3FD"),
            ("keycap 7 emoji", "7️⃣"),
            ("man technologist emoji", "\U0001F468‍\U0001F4BB"),
            ("rainbow flag emoji", "\U0001F3F3️‍\U0001F308"),
            ("beaming face with smiling eyes emoji", "\U0001F601"),
            ("grinning squinting face emoji", "\U0001F606"),
            ("a button blood type emoji", "🅰️"),
        ]:
            with self.subTest(said=said):
                self.assertEqual(se(said), want)

    def test_aliases_are_all_real_emoji(self):
        from spoken_emoji import _ALIASES
        self.assertEqual([k for k in _ALIASES if lookup(k) is None], [])

    def test_symbols_that_are_not_emoji_never_come_out(self):
        # Unicode names a few pictographs that are not emoji (they draw as
        # empty boxes): "document" is U+1F5CE.
        for said in ["document emoji", "page emoji", "overlap emoji",
                     "perspective emoji", "screen emoji"]:
            with self.subTest(said=said):
                self.assertEqual(se(said), said)

    def test_table_failure_never_breaks_dictation(self):
        import spoken_emoji as m
        saved = (m._TABLE, m._FULL, m._COMMA_KEYS)
        try:
            m._TABLE = m._FULL = None
            with mock.patch.dict(sys.modules, {"emoji_names": None}):
                self.assertEqual(se("I sent an emoji"), "I sent an emoji")
                self.assertEqual(se("rocket emoji"), "\U0001F680")
        finally:
            m._TABLE, m._FULL, m._COMMA_KEYS = saved


class ProseStaysAsSaid(unittest.TestCase):

    def test_prose_before_a_comma_is_never_part_of_a_name(self):
        for said in ["Okay, hand emoji", "No, entry emoji"]:
            with self.subTest(said=said):
                self.assertEqual(se(said), said)
        self.assertEqual(se("red, heart emoji"), "red, ❤️")
        self.assertEqual(se("family: man, woman, boy emoji"),
                         "👨‍👩‍👦")

    def test_long_dictations_stay_fast(self):
        import time
        text = " ".join(["word"] * 3000) + " laughing face emoji"
        se(text)
        t = time.perf_counter()
        for _ in range(10):
            self.assertTrue(se(text).endswith(LAUGH))
        self.assertLess((time.perf_counter() - t) / 10, 0.05)

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
