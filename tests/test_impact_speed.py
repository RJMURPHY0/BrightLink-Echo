import unittest

from app_window import AppWindow


class _Stats:
    def __init__(self, wpm, total_words=500):
        self.wpm = wpm
        self.total_words = total_words

    def snapshot(self, rng="all"):
        return {
            "saved_minutes": 0,
            "avg_wpm": self.wpm,
            "total_words": self.total_words,
            "streak_days": 0,
            "streak_active_today": False,
            "today_words": 0,
            "words": {"today": 0, "week": 0, "month": 0, "year": 0, "all": 0},
        }


class _Label:
    def configure(self, **_kwargs):
        pass


class ImpactSpeedTests(unittest.TestCase):
    def _speed_card(self, wpm, total_words=500):
        window = AppWindow.__new__(AppWindow)
        window._stats = _Stats(wpm, total_words)
        window._impact_cards = {"time": {}, "speed": {}, "streak": {}}
        window._impact_today_lbl = _Label()
        updates = {}
        window._set_impact_card = (
            lambda key, value, unit, sub:
                updates.__setitem__(key, (value, unit, sub))
        )
        window._refresh_impact()
        return updates["speed"]

    def test_measured_speed_shows_typing_multiple(self):
        self.assertEqual(
            ("213", "wpm", "5.3× faster than typing"),
            self._speed_card(213),
        )

    def test_nominal_speed_shows_four_times_typing(self):
        # Words exist but the window is too thin to measure a rate — the
        # v1.6.70 nominal fallback still stands.
        self.assertEqual(
            ("160", "wpm", "4× faster than typing"),
            self._speed_card(0, total_words=500),
        )

    def test_a_fresh_account_does_not_claim_a_dictation_speed(self):
        # Nothing has ever been dictated. 160 wpm is the modelled figure the
        # savings maths uses, not this person's, and showing it as "your
        # dictation speed" on day one is the same untruth the time card told.
        self.assertEqual(
            ("—", "wpm", "Dictate to measure"),
            self._speed_card(0, total_words=0),
        )


class ImpactTimeCardTests(unittest.TestCase):
    """The Time Saved card on a brand-new account.

    Reported live: signing in for the first time announced a saving before a
    word had been dictated. The `m < 1` bucket was catching exactly zero and
    rendering it as "< 1 min", which reads as a claim rather than as nothing.
    """

    def _time_card(self, saved_minutes):
        window = AppWindow.__new__(AppWindow)
        window._stats = _Stats(0, total_words=0)
        window._stats.snapshot = lambda rng="all": {
            "saved_minutes": saved_minutes,
            "avg_wpm": 0,
            "total_words": 0,
            "streak_days": 0,
            "streak_active_today": False,
            "today_words": 0,
            "words": {"today": 0, "week": 0, "month": 0, "year": 0, "all": 0},
        }
        window._impact_cards = {"time": {}, "speed": {}, "streak": {}}
        window._impact_today_lbl = _Label()
        updates = {}
        window._set_impact_card = (
            lambda key, value, unit, sub:
                updates.__setitem__(key, (value, unit, sub))
        )
        window._refresh_impact()
        return updates["time"]

    def test_nothing_dictated_reads_zero_not_under_one(self):
        value, unit, sub = self._time_card(0.0)
        self.assertEqual(("0", "min"), (value, unit))
        self.assertNotIn("<", value)
        self.assertEqual("Dictate to start saving", sub)

    def test_a_real_sub_minute_saving_still_reads_under_one(self):
        # "< 1 min" is honest once something HAS been saved; only exact zero
        # was the lie. Guarding both directions so the fix cannot overshoot.
        value, unit, _sub = self._time_card(0.4)
        self.assertEqual(("< 1", "min"), (value, unit))


if __name__ == "__main__":
    unittest.main()
