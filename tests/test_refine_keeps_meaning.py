"""Refine changes how something is said, never what was said.

Ryan's rule (2026-09-25): Fix All tidies the speaker's own words (grammar,
punctuation, stutters, false starts) and must still sound like them; the modes
that reword (formal, casual, concise, email) may change the wording and tone
but keep every point; an Ask does what it says and nothing more.

The prompts are instructions, not guarantees, so these tests pin what the
model is TOLD, which is the part this code controls.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_refiner
from ai_refiner import REFINE_PROMPTS


class _Capture(ai_refiner.AIRefiner):
    def __init__(self):
        super().__init__(openrouter_api_key="test-key")
        self.prompt = self.system = None

    def _refine_via_openrouter(self, text, prompt, mode, system=""):
        self.prompt, self.system = prompt, system
        return text


def _run(**kw):
    r = _Capture()
    r.refine("so um can could you send it over on tuesday sorry wednesday", **kw)
    return r


class FixAllTests(unittest.TestCase):
    def test_fix_all_gets_the_proofreader_system_prompt(self):
        # The style prompt says "keep sentences short, avoid filler words",
        # which contradicts "keep every word" and made Fix All reword.
        r = _run(mode="punctuation")
        self.assertEqual(r.system, ai_refiner.AIRefiner._EDITOR_SYSTEM_PROMPT)
        self.assertNotIn("short", r.system.lower())
        self.assertNotIn("filler", r.system.lower())

    def test_fix_all_removes_false_starts_and_hesitations(self):
        p = REFINE_PROMPTS["punctuation"].lower()
        self.assertIn("false starts", p)
        self.assertIn("um, uh", p)

    def test_fix_all_strips_filler_like_and_you_know(self):
        # Ryan's call (2026-09-25): padding "like" / "you know" goes, the way
        # Wispr Flow does it; a "like" or "you know" that means something stays.
        p = REFINE_PROMPTS["punctuation"].lower()
        self.assertIn("filler 'like' and 'you know'", p)
        self.assertIn("keep 'like' whenever it carries meaning", p)
        self.assertIn("'i like it'", p)

    def test_fix_all_keeps_the_speakers_voice(self):
        p = REFINE_PROMPTS["punctuation"].lower()
        self.assertIn("still sound like the speaker", p)
        self.assertIn("so yeah", p)
        self.assertIn("do not tighten, shorten, formalise", p)


class RewordingModeTests(unittest.TestCase):
    def test_rewording_modes_keep_the_essence(self):
        for mode in ("formal", "casual", "concise", "email"):
            self.assertIn(ai_refiner._KEEP_ESSENCE, REFINE_PROMPTS[mode], mode)

    def test_correction_passes_do_not_get_the_rewording_licence(self):
        # "The wording may change" would loosen the passes that must not reword.
        for mode in ("punctuation", "context_fix"):
            self.assertNotIn(ai_refiner._KEEP_ESSENCE, REFINE_PROMPTS[mode], mode)

    def test_rewording_modes_keep_the_style_prompt(self):
        r = _run(mode="formal")
        self.assertEqual(r.system, ai_refiner.AIRefiner._STYLE_SYSTEM_PROMPT)


class AskTests(unittest.TestCase):
    def test_an_ask_keeps_the_style_prompt_not_the_proofreader(self):
        # A custom Ask arrives with the default mode ("punctuation").
        r = _run(custom_prompt="Make this clearer.")
        self.assertEqual(r.system, ai_refiner.AIRefiner._STYLE_SYSTEM_PROMPT)

    def test_an_ask_does_only_what_it_says(self):
        r = _run(custom_prompt="Make this clearer.")
        self.assertIn("nothing more", r.prompt)
        self.assertIn("Keep the speaker's meaning", r.prompt)

    def test_context_fix_keeps_the_corrector(self):
        r = _Capture()
        r.refine("some text here to fix", mode="context_fix")
        self.assertEqual(r.system, ai_refiner.AIRefiner._CORRECTOR_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
