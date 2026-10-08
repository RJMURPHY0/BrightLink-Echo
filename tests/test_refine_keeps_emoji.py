import unittest
from unittest import mock

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
        type(r).is_available = property(lambda self: True)
        try:
            out = r.refine("up to you \U0001F60A", "punctuation")
        finally:
            del type(r).is_available
        self.assertIn("emoji", seen["prompt"])
        self.assertIn("\U0001F60A", out)


if __name__ == "__main__":
    unittest.main()
