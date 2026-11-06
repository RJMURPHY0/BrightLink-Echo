"""The background AI accuracy check is gated by the ai_accuracy_check setting,
whose default comes from one named constant."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as C
import app as app_mod


class AccuracyCheckTests(unittest.TestCase):
    def test_default_comes_from_the_constant_and_keeps_today_on(self):
        self.assertIs(C.Config().ai_accuracy_check, C.AI_ACCURACY_CHECK_DEFAULT)
        self.assertTrue(C.AI_ACCURACY_CHECK_DEFAULT)

    def _on(self, cfg):
        return app_mod.WhisperFlowApp._ai_accuracy_check_on(SimpleNamespace(config=cfg))

    def test_setting_off_disables_the_check(self):
        self.assertFalse(self._on(SimpleNamespace(ai_accuracy_check=False)))
        self.assertTrue(self._on(SimpleNamespace(ai_accuracy_check=True)))

    def test_missing_setting_uses_the_constant(self):
        self.assertEqual(self._on(SimpleNamespace()), C.AI_ACCURACY_CHECK_DEFAULT)

    def test_both_background_paths_are_gated(self):
        src = open(app_mod.__file__, encoding="utf-8").read()
        self.assertEqual(src.count("self._ai_accuracy_check_on()"), 2)


if __name__ == "__main__":
    unittest.main()
