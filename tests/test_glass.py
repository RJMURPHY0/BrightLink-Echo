"""The pill, pop-up panel and notices share one slightly see-through look.

Ryan (24 Nov 2026): "slightly transparent, not too much". One value, so they
always match, and near-solid so the text reads over any page.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from glass import GLASS_ALPHA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class Glass(unittest.TestCase):

    def test_slightly_see_through_not_too_much(self):
        self.assertGreaterEqual(GLASS_ALPHA, 0.85)
        self.assertLess(GLASS_ALPHA, 0.95)

    def test_popup_windows_use_it(self):
        src = _src("popup.py")
        self.assertIn('win.attributes("-alpha", GLASS_ALPHA)', src)

    def test_notices_fade_in_to_it_not_to_solid(self):
        src = _src("app_window.py")
        self.assertIn("min(GLASS_ALPHA, alpha + step)", src)
        self.assertIn("min(GLASS_ALPHA, a + 0.14)", src)
        self.assertNotIn("min(1.0, alpha + step)", src)
        self.assertNotIn("min(1.0, a + 0.14)", src)


if __name__ == "__main__":
    unittest.main()
