"""Checks for the Echo updated card and its contained confetti."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import update_card  # noqa: E402


class Card(unittest.TestCase):
    def test_card_size_and_button_fit(self):
        img = update_card.render_card("1.8.37", "1.8.38", "BrightLink Echo")
        rows = update_card.card_rows("1.8.37", "1.8.38")
        self.assertEqual(img.size, (300, update_card.card_height(len(rows))))
        x0, y0, x1, y1 = update_card.button_box(len(rows))
        self.assertTrue(0 < x0 < x1 < img.width and 0 < y0 < y1 < img.height)
        self.assertEqual(img.getpixel((x0 + 6, (y0 + y1) // 2))[:3], (0xf3, 0x92, 0x00))

    def test_no_previous_version_drops_its_row(self):
        self.assertEqual([k for k, _ in update_card.card_rows("", "2.0.0")],
                         ["Version", "Updates"])

    def test_see_through_corners_have_a_hard_edge(self):
        img = update_card.render_card("1", "2", "BrightLink Echo", key_colour="#010102")
        self.assertEqual(img.getpixel((0, 0))[:3], (1, 1, 2))
        self.assertEqual(img.getchannel("A").getextrema(), (255, 255))


class Confetti(unittest.TestCase):
    def test_every_drawn_shape_stays_inside_card_and_animation_ends(self):
        w, h = 300, update_card.card_height(3)
        conf = update_card.Confetti((w, h), seed=7)
        self.assertTrue(all(conf._inside(piece) for piece in conf.pieces))
        for frame in range(700):
            active = conf.step(1 / 60)
            for piece in conf.pieces:
                shape = conf.shape(piece)
                points = ((shape[0], shape[1]), (shape[2], shape[3])) if piece["round"] else zip(shape[::2], shape[1::2])
                for x, y in points:
                    self.assertTrue(0 <= x <= w and 0 <= y <= h, (frame, piece))
                self.assertTrue(conf._inside(piece))
            if not active:
                break
        else:
            self.fail("Confetti never ended")
        self.assertFalse(conf.pieces)
        self.assertGreaterEqual(conf.emitted["left"], 16)
        self.assertGreaterEqual(conf.emitted["right"], 16)
        self.assertGreaterEqual(conf.emitted["centre"], 18)
        self.assertGreaterEqual(conf.emitted["rain"], 25)

    def test_timed_emissions(self):
        conf = update_card.Confetti((300, update_card.card_height(3)), seed=2)
        self.assertEqual((conf.emitted["left"], conf.emitted["right"]), (16, 16))
        self.assertEqual(conf.emitted["centre"], 0)
        for _ in range(17):
            conf.step(1 / 60)
        self.assertEqual(conf.emitted["centre"], 18)
        for _ in range(150):
            conf.step(1 / 60)
        self.assertGreater(conf.emitted["rain"], 0)
        self.assertTrue({p["colour"] for p in conf.pieces} <= set(update_card.CONFETTI_COLOURS))


if __name__ == "__main__":
    unittest.main()
