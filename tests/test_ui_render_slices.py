"""The sliced rounded-rect render must be the same picture as the full one.

Every card background on a page is a ui_render.round_rect. Drawn whole at 4x
it cost ~7-17ms a card, so a first visit to Settings (33 cards) spent a
quarter of a second on backgrounds alone (2026-10-28). The sliced render
builds the same image from one small corner tile; these tests hold it to
pixel-identical output so the speed never costs a pixel.
"""

import unittest

from PIL import ImageChops

import ui_render

_CASES = [
    # (w, h, r, fill, outline, width, bg)
    (380, 64, 12, "#1a1a1a", "#2a2a2a", 1, "#0d0d0d"),   # settings card
    (420, 148, 14, "#1c1c1c", "#333333", 1, "#111111"),  # impact card
    (128, 26, 7, "#3a2400", "#f39200", 1, "#1a1a1a"),    # period tile
    (60, 30, 7, "#222222", "#f39200", 2, "#000000"),     # thick outline
    (300, 200, 0, "#222222", "", 1, "#000000"),          # square, no outline
    (200, 40, 20, "#222222", "#444444", 1, "#000000"),   # pill
    (31, 31, 7, "#222222", "#444444", 1, "#000000"),     # too small to slice
    (14, 14, 7, "#222222", "#888888", 1, "#222222"),     # radio-sized
]


class SlicedRoundRectTests(unittest.TestCase):
    def test_sliced_render_is_pixel_identical_to_the_full_render(self):
        for case in _CASES:
            with self.subTest(case=case):
                full = ui_render._rr_full(*case)
                sliced = ui_render._rr_image(*case)
                self.assertEqual(full.size, sliced.size)
                diff = ImageChops.difference(full, sliced)
                self.assertEqual(0, max(hi for _lo, hi in diff.getextrema()))

    def test_every_width_of_a_live_resize_matches(self):
        for w in range(29, 140, 7):
            with self.subTest(w=w):
                case = (w, 52, 12, "#1a1a1a", "#2a2a2a", 1, "#0d0d0d")
                diff = ImageChops.difference(ui_render._rr_full(*case),
                                             ui_render._rr_image(*case))
                self.assertEqual(0, max(hi for _lo, hi in diff.getextrema()))

    def test_round_rect_uses_the_sliced_render(self):
        import inspect
        self.assertIn("_rr_image(", inspect.getsource(ui_render.round_rect))


if __name__ == "__main__":
    unittest.main()
