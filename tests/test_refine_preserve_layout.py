"""The refiner keeps existing line breaks by default: a custom Ask ("make this
better") and Fix All must not flatten a laid-out email, while the explicit
restructure modes (email/formal/casual/concise) still reflow."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_refiner


MULTILINE = "Hi Louise,\n\nHope you are well.\n\nKind regards,\nRyan"
ONELINE = "hi louise hope you are well kind regards ryan"


class _CapturingRefiner(ai_refiner.AIRefiner):
    """Runs refine() far enough to build the prompt, then captures it instead
    of calling the network."""

    def __init__(self):
        super().__init__(openrouter_api_key="test-key")
        self.captured = None

    def _refine_via_openrouter(self, text, prompt, mode, system=""):
        self.captured = prompt
        self.system = system
        return text


PRESERVE = "keep every existing line break"
PRESERVE_PLAIN = "keep every line break exactly where it is"


class PreserveLayoutTests(unittest.TestCase):
    def _prompt(self, text, **kw):
        r = _CapturingRefiner()
        r.refine(text, **kw)
        return (r.captured or "").lower()

    def test_custom_ask_preserves_layout(self):
        p = self._prompt(MULTILINE, custom_prompt="Make this better.")
        self.assertIn(PRESERVE, p)

    def test_fix_all_preserves_layout(self):
        p = self._prompt(MULTILINE, mode="punctuation")
        self.assertIn(PRESERVE_PLAIN, p)

    def test_context_fix_preserves_layout(self):
        p = self._prompt(MULTILINE, mode="context_fix")
        self.assertIn(PRESERVE_PLAIN, p)

    def test_email_mode_is_allowed_to_reflow(self):
        p = self._prompt(MULTILINE, mode="email")
        self.assertNotIn(PRESERVE, p)
        self.assertNotIn(PRESERVE_PLAIN, p)

    def test_reshape_modes_do_not_preserve(self):
        for mode in ("formal", "casual", "concise"):
            p = self._prompt(MULTILINE, mode=mode)
            self.assertNotIn(PRESERVE, p, mode)
            self.assertNotIn(PRESERVE_PLAIN, p, mode)

    def test_single_line_text_gets_no_clause(self):
        p = self._prompt(ONELINE, custom_prompt="Make this better.")
        self.assertNotIn(PRESERVE, p)


if __name__ == "__main__":
    unittest.main()
