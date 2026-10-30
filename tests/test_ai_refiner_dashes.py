"""The refiner never hands back an em or en dash the speaker did not dictate."""
import unittest

from ai_refiner import drop_new_dashes

EM = "\u2014"
EN = "\u2013"


class DropNewDashesTests(unittest.TestCase):
    def test_a_spaced_dash_becomes_a_comma(self):
        self.assertEqual("Send it, then call me.", drop_new_dashes("Send it then call me.", f"Send it {EM} then call me."))

    def test_an_unspaced_dash_becomes_a_comma(self):
        self.assertEqual("fast, and safe", drop_new_dashes("fast and safe", f"fast{EM}and safe"))

    def test_a_number_range_reads_to(self):
        self.assertEqual("8 to 12 people", drop_new_dashes("eight to twelve people", f"8{EN}12 people"))

    def test_a_dash_at_a_line_edge_goes(self):
        self.assertEqual("one\ntwo", drop_new_dashes("one\ntwo", f"{EM} one\n{EM} two"))

    def test_the_speakers_own_dash_is_left_alone(self):
        said = f"Paris {EM} the city"
        self.assertEqual(said, drop_new_dashes(said, said))

    def test_clean_text_is_untouched(self):
        self.assertEqual("Hello there.", drop_new_dashes("hello there", "Hello there."))


if __name__ == "__main__":
    unittest.main()
