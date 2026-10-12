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
