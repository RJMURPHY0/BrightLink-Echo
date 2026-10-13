import unittest

import ai_refiner
from ai_refiner import _restore_emoji


class RefineKeepsEmoji(unittest.TestCase):
    def test_dropped_emoji_is_restored(self):
        self.assertEqual(_restore_emoji("up to you \U0001F60A", "Up to you."),
                         "Up to you. \U0001F60A")

    def test_kept_emoji_untouched(self):
        t = "Up to you \U0001F60A."
        self.assertEqual(_restore_emoji("up to you \U0001F60A", t), t)

    def test_no_emoji_no_change(self):
        self.assertEqual(_restore_emoji("hello", "Hello."), "Hello.")

    # Emoji the old class missed: only a bare U+FE0F came back for these.
    PLAY = "\u25b6\ufe0f"
    KEYCAP = "#\ufe0f\u20e3"
    ENGLAND = ("\U0001F3F4\U000E0067\U000E0062\U000E0065"
               "\U000E006E\U000E0067\U000E007F")
    FAMILY = "\U0001F468\u200d\U0001F469\u200d\U0001F467"

    def test_wider_emoji_survive_being_dropped(self):
        for emoji in (self.PLAY, self.KEYCAP, self.ENGLAND, self.FAMILY,
                      "\u3030\ufe0f", "\u2934\ufe0f", "\u3299\ufe0f"):
            with self.subTest(emoji=ascii(emoji)):
                self.assertEqual(_restore_emoji(f"play it {emoji}", "Play it."),
                                 f"Play it. {emoji}")

    def test_wider_emoji_kept_in_place_are_untouched(self):
        for emoji in (self.PLAY, self.KEYCAP, self.ENGLAND, self.FAMILY):
            with self.subTest(emoji=ascii(emoji)):
                t = f"Play {emoji} now."
                self.assertEqual(_restore_emoji(f"play {emoji} now", t), t)

    def test_a_lone_joiner_or_selector_is_never_appended(self):
        for glue in ("\ufe0f", "\u200d", "\u200d\ufe0f"):
            with self.subTest(glue=ascii(glue)):
                self.assertEqual(_restore_emoji(f"ok{glue} then", "Ok then."),
                                 "Ok then.")

    def test_plain_text_and_digits_are_unchanged(self):
        for text in ("Call me at 4 on line #2.", "Costs 10*3 = 30.",
                     "It's fine, don't worry."):
            with self.subTest(text=text):
                self.assertEqual(ai_refiner._EMOJI.findall(text), [])
                self.assertEqual(_restore_emoji(text, text.upper()), text.upper())

    def test_refine_prompt_names_emoji_and_result_keeps_it(self):
        r = ai_refiner.AIRefiner.__new__(ai_refiner.AIRefiner)
        r.openrouter_api_key = "x"
        r.api_key = ""
        seen = {}

        def fake(text, prompt, mode, system):
            seen["prompt"] = prompt
            return "Up to you."
        r._refine_via_openrouter = fake
        r._apply_sender_name = lambda out, mode, name: out
        # openrouter_api_key makes is_available True already. This used to
        # overwrite the property on the class and then `del` it, which removed
        # AIRefiner.is_available for every later test in the run: the 23
        # "known" refiner failures on clean main were this, not real bugs.
        out = r.refine("up to you \U0001F60A", "punctuation")
        self.assertIn("emoji", seen["prompt"])
        self.assertIn("\U0001F60A", out)


if __name__ == "__main__":
    unittest.main()
