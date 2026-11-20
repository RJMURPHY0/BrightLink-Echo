"""Refine buttons give a result the user accepts first time (2026-11-18).

Ryan's brief: like telling ChatGPT "make this a bit more professional": the
user's own voice and exactly what they said, only polished. Measured on the
offline eval in tools/refine_eval (see docs/decisions/text-formatting.md,
2026-11-18). These tests pin the prompt construction and the output guards
this code controls; the eval proves what the model does with them.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_refiner
from ai_refiner import (REFINE_PROMPTS, AIRefiner, ends_with_bare_signoff,
                        strip_commentary)


class _Capture(AIRefiner):
    """Records what refine() sends and returns a canned model reply."""

    def __init__(self, reply=None):
        super().__init__(openrouter_api_key="test-key")
        self.reply = reply
        self.prompt = self.system = None

    def _refine_via_openrouter(self, text, prompt, mode, system=""):
        self.prompt, self.system = prompt, system
        return text if self.reply is None else self.reply


REWORDING = ("formal", "casual", "concise", "email")


class EssenceTests(unittest.TestCase):
    def test_every_rewording_button_copies_facts_exactly(self):
        for mode in REWORDING:
            p = REFINE_PROMPTS[mode].lower()
            self.assertIn("copied exactly as written", p, mode)
            self.assertIn("digits stays in digits", p, mode)
            self.assertIn("never reformatted", p, mode)

    def test_greeting_and_signoff_are_kept_never_invented(self):
        for mode in REWORDING:
            p = REFINE_PROMPTS[mode].lower()
            self.assertIn("keep its words and the name exactly", p, mode)
            self.assertIn("if it has none, do not add one", p, mode)

    def test_examples_never_name_a_signoff_the_model_could_copy(self):
        # v1 quoted "'Cheers,' never becomes 'Best regards,'" and the model
        # then signed off messages that had no sign-off with "Cheers,".
        for mode in REWORDING:
            self.assertNotIn("Cheers", ai_refiner._KEEP_ESSENCE + REFINE_PROMPTS[mode], mode)

    def test_formal_is_a_light_professional_polish_not_a_letter(self):
        p = REFINE_PROMPTS["formal"]
        self.assertIn("a bit more professional", p)
        self.assertIn("same person on a good day", p)
        for padding in ("'Dear'", "'I am writing to'", "'please do not hesitate'"):
            self.assertIn(padding, p)
        self.assertNotIn("Rewrite this transcribed speech in a formal", p)

    def test_buttons_change_little_when_nothing_needs_changing(self):
        for mode in ("formal", "casual", "concise"):
            self.assertIn("change little", REFINE_PROMPTS[mode], mode)

    def test_no_prompt_bans_hyphens(self):
        # The old ban stripped the hyphen from "ftc-ss.com" and "FTC-2291".
        self.assertNotIn("hyphens", ai_refiner._NO_FORMAT)
        self.assertIn("hyphenated words", ai_refiner._NO_FORMAT)
        self.assertNotIn("flowing sentences", ai_refiner._NO_FORMAT)

    def test_fix_all_stays_a_correction_pass(self):
        self.assertNotIn(ai_refiner._KEEP_ESSENCE, REFINE_PROMPTS["punctuation"])


class StyleSystemPromptTests(unittest.TestCase):
    def test_style_prompt_no_longer_shortens_every_button(self):
        s = AIRefiner._STYLE_SYSTEM_PROMPT.lower()
        self.assertNotIn("keep sentences short", s)
        self.assertIn("british english", s)
        self.assertIn("never use em dashes", s)
        self.assertIn("their voice", s)

    def test_rewording_buttons_get_the_style_prompt(self):
        for mode in REWORDING:
            r = _Capture()
            r.refine("could you send it over on tuesday", mode=mode)
            self.assertTrue(r.system.startswith(AIRefiner._STYLE_SYSTEM_PROMPT), mode)


class SenderNameTests(unittest.TestCase):
    def test_bare_signoffs(self):
        for t in ("Can you send it over? Thanks,", "See you then. Cheers",
                  "Speak Monday.\n\nKind regards,", "ok thanks", "Ta."):
            self.assertTrue(ends_with_bare_signoff(t), t)

    def test_named_or_absent_signoffs(self):
        for t in ("Cheers, Ryan", "Thanks,\nRyan", "Can you send it over?",
                  "Thanks Priya, that's perfect, I'll get it signed tomorrow.", ""):
            self.assertFalse(ends_with_bare_signoff(t), t)

    def test_name_is_offered_only_for_a_bare_signoff(self):
        r = _Capture()
        r.refine("can you send the report over thanks", mode="email", sender_name="Ryan Murphy")
        self.assertIn("Ryan Murphy", r.prompt)
        r = _Capture()
        r.refine("can you send the report over", mode="email", sender_name="Ryan Murphy")
        self.assertNotIn("Ryan Murphy", r.prompt)
        r = _Capture()
        r.refine("can you send the report over cheers Ryan", mode="email", sender_name="Ryan Murphy")
        self.assertNotIn("Ryan Murphy", r.prompt)


class ModelTests(unittest.TestCase):
    def test_default_is_live_and_paid(self):
        self.assertNotIn(AIRefiner.DEFAULT_OPENROUTER_MODEL, AIRefiner.RETIRED_OPENROUTER_MODELS)
        for m in [AIRefiner.DEFAULT_OPENROUTER_MODEL] + AIRefiner.OPENROUTER_FALLBACK_MODELS:
            self.assertFalse(m.endswith(":free"), m)
            self.assertNotIn(m, AIRefiner.RETIRED_OPENROUTER_MODELS)

    def test_a_saved_retired_model_maps_to_the_default(self):
        r = AIRefiner(openrouter_api_key="k", openrouter_model="google/gemini-2.5-flash-lite")
        self.assertEqual(r.openrouter_model, AIRefiner.DEFAULT_OPENROUTER_MODEL)
        r.openrouter_model = "google/gemini-2.0-flash-001"
        self.assertEqual(r.openrouter_model, AIRefiner.DEFAULT_OPENROUTER_MODEL)

    def test_a_chosen_live_model_is_kept(self):
        r = AIRefiner(openrouter_api_key="k", openrouter_model="some/other-model")
        self.assertEqual(r.openrouter_model, "some/other-model")
        r.openrouter_model = ""
        self.assertEqual(r.openrouter_model, AIRefiner.DEFAULT_OPENROUTER_MODEL)

    def test_config_default_is_not_retired(self):
        import config
        self.assertNotIn(config.Config().openrouter_model, AIRefiner.RETIRED_OPENROUTER_MODELS)


class CommentaryGuardTests(unittest.TestCase):
    def test_self_correction_keeps_the_final_answer(self):
        out = ("Can you, like, send it?\n\nWait: \"like\" here is verbal padding, "
               "so it should be removed. The corrected version:\n\nCan you send it?")
        self.assertEqual(strip_commentary("can you like send it", out), "Can you send it?")

    def test_preamble_is_dropped(self):
        self.assertEqual(strip_commentary("x", "Here is the corrected text:\n\nHello there."),
                         "Hello there.")
        self.assertEqual(strip_commentary("x", "Sure, here's the polished version:\nHi Sam,"),
                         "Hi Sam,")

    def test_dictated_lines_are_never_taken_for_commentary(self):
        for out in ("Hi John,\n\nHere's the plan:\n1. Go",
                    "Wait for me at the station, please.\nThanks",
                    "The final version: we ship on Friday."):
            self.assertEqual(strip_commentary("x", out), out)
        said = "here is the edited version:\nfoo"
        self.assertEqual(strip_commentary(said, "Here is the edited version:\nFoo."),
                         "Here is the edited version:\nFoo.")

    def test_a_dictated_wait_line_survives_its_new_full_stop(self):
        # 2026-11-20 audit: refine added the missing full stop, the line no
        # longer matched the original exactly, and it was cut as self-talk
        # along with everything above it.
        said = ("The first load is ready.\nWait until the updated invoice "
                "arrives\nThen send both together.")
        out = ("The first load is ready.\nWait until the updated invoice "
               "arrives.\nThen send both together.")
        self.assertEqual(strip_commentary(said, out), out)
        out2 = "Hi Sam,\nWait for the revised quote before you order.\nThanks"
        self.assertEqual(strip_commentary("x", out2), out2)

    def test_a_said_preamble_survives_a_punctuation_change(self):
        said = "here is the edited version\nfoo"
        self.assertEqual(strip_commentary(said, "Here is the edited version:\nFoo."),
                         "Here is the edited version:\nFoo.")

    def test_nothing_is_cut_when_no_answer_follows(self):
        out = "Hello.\nThe corrected version:"
        self.assertEqual(strip_commentary("x", out), out)

    def test_refine_applies_the_guard(self):
        r = _Capture(reply="Here is the edited text:\nCould you send it over?")
        self.assertEqual(r.refine("could you send it over", mode="formal"),
                         "Could you send it over?")


if __name__ == "__main__":
    unittest.main()
