"""Start with Windows' priority slider: the wait at sign-in and its widget maths."""

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

import startup_order
from config import Config
from stop_slider import nearest_stop, stop_positions

ROOT = Path(__file__).resolve().parent.parent


def _wait(argv, stop):
    slept, classes = [], []
    waited = startup_order.wait_at_sign_in(
        argv, sleep=slept.append, set_class=classes.append, stop=stop)
    return waited, slept, classes


class WaitAtSignIn(unittest.TestCase):
    def tearDown(self):
        startup_order._lowered = False

    def test_default_stop_is_todays_behaviour(self):
        self.assertEqual(0, startup_order.DEFAULT_STOP)
        self.assertEqual(0, Config().startup_priority)
        self.assertEqual((0, [], []), _wait(["app", "--startup"], 0))

    def test_a_launch_by_hand_never_waits_at_any_stop(self):
        for stop in range(len(startup_order.STOPS)):
            self.assertEqual((0, [], []), _wait(["app"], stop))

    def test_later_stops_wait_then_load_at_their_own_class(self):
        for stop in range(1, len(startup_order.STOPS)):
            chosen = startup_order.STOPS[stop]
            waited, slept, classes = _wait(["app", "--STARTUP"], stop)
            self.assertEqual(chosen.delay_seconds, waited)
            self.assertEqual([chosen.delay_seconds], slept)
            self.assertEqual([chosen.load_class], classes)

    def test_never_below_normal_which_starves_on_a_busy_pc(self):
        for stop in startup_order.STOPS:
            self.assertIn(stop.load_class, (startup_order.NORMAL, startup_order.ABOVE_NORMAL))

    def test_each_stop_starts_later_than_the_one_before(self):
        delays = [s.delay_seconds for s in startup_order.STOPS]
        self.assertEqual(sorted(set(delays)), delays)

    def test_dictation_goes_back_to_above_normal(self):
        _wait(["app", "--startup"], 2)
        classes = []
        startup_order.restore_dictation_priority(set_class=classes.append)
        self.assertEqual([startup_order.ABOVE_NORMAL], classes)
        startup_order.restore_dictation_priority(set_class=classes.append)
        self.assertEqual(1, len(classes), "restores once only")

    def test_never_touches_priority_when_it_did_not_lower_it(self):
        classes = []
        startup_order.restore_dictation_priority(set_class=classes.append)
        self.assertEqual([], classes)


class SavedStop(unittest.TestCase):
    def _saved(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            return startup_order.saved_stop(p)

    def test_reads_the_saved_stop(self):
        self.assertEqual(2, self._saved(json.dumps({"startup_priority": 2})))

    def test_damage_can_never_hold_the_app_back(self):
        for text in ("", "{", "[]", '"x"', json.dumps({"startup_priority": "soon"}),
                     json.dumps({"startup_priority": None}),
                     json.dumps({"startup_priority": True})):
            self.assertEqual(0, self._saved(text), text)
        self.assertEqual(0, startup_order.saved_stop(os.path.join("missing", "c.json")))

    def test_out_of_range_lands_on_a_real_stop(self):
        self.assertEqual(3, self._saved(json.dumps({"startup_priority": 99})))
        self.assertEqual(0, self._saved(json.dumps({"startup_priority": -4})))

    def test_config_load_clamps_it(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"startup_priority": 99}, f)
            self.assertEqual(3, Config.load(p).startup_priority)

    def test_stays_on_this_pc(self):
        from cloud_sync import SYNCED_SETTINGS
        self.assertNotIn("startup_priority", SYNCED_SETTINGS)


class SliderMaths(unittest.TestCase):
    def test_stops_span_the_track_and_end_stops_are_inset(self):
        self.assertEqual([10, 100, 190], stop_positions(200, 3))
        self.assertEqual(4, len(stop_positions(320, 4)))

    def test_nearest_stop(self):
        xs = stop_positions(300, 4)
        self.assertEqual(0, nearest_stop(-50, xs))
        self.assertEqual(3, nearest_stop(9999, xs))
        for i, x in enumerate(xs):
            self.assertEqual(i, nearest_stop(x, xs))


class Wiring(unittest.TestCase):
    src = (ROOT / "app.py").read_text(encoding="utf-8")

    def test_the_wait_runs_ahead_of_the_heavy_imports(self):
        self.assertLess(self.src.index("startup_order.wait_at_sign_in(sys.argv)"),
                        self.src.index("from config import Config"))

    def test_the_wait_follows_the_foreign_runtime_guard(self):
        self.assertLess(self.src.index("pyi_runtime.relaunch_if_foreign_runtime"),
                        self.src.index("startup_order.wait_at_sign_in(sys.argv)"))

    def test_module_is_stdlib_only(self):
        tree = ast.parse((ROOT / "startup_order.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        self.assertEqual({"ctypes", "json", "os", "sys", "time", "typing"}, names)

    def test_a_second_sign_in_launcher_still_exits_silently(self):
        i = self.src.index("def _ensure_single_instance")
        self.assertIn("_launched_at_sign_in()", self.src[i:i + 900])


if __name__ == "__main__":
    unittest.main()
