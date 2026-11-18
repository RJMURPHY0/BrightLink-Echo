"""Start with Windows' priority slider: the wait at sign-in and its widget maths."""

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import startup_order
from config import Config
from stop_slider import nearest_stop, stop_positions

ROOT = Path(__file__).resolve().parent.parent


SIGNED_IN = 1_000_000.0


class _Clock:
    def __init__(self, t):
        self.t = t
        self.slept = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s
        self.slept += s


class _Exit(Exception):
    pass


def _exit(code):
    raise _Exit(code)


class _Watch:
    """Apps opening at the given seconds after sign-in."""

    def __init__(self, clock, opens):
        self.clock, self.opens = clock, opens

    def latest_start(self):
        seen = [SIGNED_IN + s for s in self.opens if SIGNED_IN + s <= self.clock.t]
        return max(seen, default=SIGNED_IN)


class _Cpu:
    def __init__(self, busy_until):
        self.busy_until, self.clock = busy_until, None

    def busy(self):
        return 0.9 if self.clock.t < SIGNED_IN + self.busy_until else 0.05


def _wait(argv, stop, kind=startup_order.STARTUP_APPS, at=40, opens=(),
          present=lambda: False, cpu_busy_until=0):
    clock = _Clock(SIGNED_IN + at)
    classes = []
    cpu = _Cpu(cpu_busy_until)
    cpu.clock = clock
    with mock.patch.object(startup_order, "_hold_wait_mutex") as held:
        waited = startup_order.wait_at_sign_in(
            argv, sleep=clock.sleep, set_class=classes.append, stop=stop, kind=kind,
            clock=clock, signed_in=SIGNED_IN, others_present=present, exit_fn=_exit,
            watch=_Watch(clock, opens), cpu=cpu)
    return waited, clock, classes, held.called


class WaitAtSignIn(unittest.TestCase):
    def tearDown(self):
        startup_order._lowered = False
        startup_order._report = ""

    def test_default_stop_is_todays_behaviour(self):
        self.assertEqual(0, startup_order.DEFAULT_STOP)
        self.assertEqual(0, Config().startup_priority)
        for kind in (startup_order.EARLY, startup_order.STARTUP_APPS):
            waited, clock, classes, _ = _wait(["app", "--startup"], 0, kind=kind, at=3)
            self.assertEqual((0, 0.0, []), (waited, clock.slept, classes))

    def test_a_launch_by_hand_never_waits_at_any_stop(self):
        for stop in range(len(startup_order.STOPS)):
            waited, clock, classes, _ = _wait(["app"], stop, opens=(30, 60, 90))
            self.assertEqual((0, 0.0, []), (waited, clock.slept, classes))

    def test_the_logon_task_steps_aside_for_the_startup_apps_launch(self):
        # 18 Nov 2026: the logon task fired 3 s after sign-in and a fixed 20 s
        # timer put Echo ahead of every other startup app.
        for stop in range(1, len(startup_order.STOPS)):
            arrivals = iter([False] * 20 + [True])
            with self.assertRaises(_Exit):
                _wait(["app", "--startup"], stop, kind=startup_order.EARLY, at=3,
                      present=lambda: next(arrivals))

    def test_the_logon_task_starts_it_if_the_startup_apps_launch_never_comes(self):
        waited, clock, classes, _ = _wait(["app", "--startup"], 1,
                                          kind=startup_order.EARLY, at=3)
        self.assertGreaterEqual(clock.t - SIGNED_IN, startup_order.EARLY_HANDOVER_LIMIT_S)
        self.assertEqual([startup_order.NORMAL], classes)

    def test_with_others_starts_the_moment_windows_opens_startup_apps(self):
        waited, clock, classes, held = _wait(["app", "--STARTUP"], 1, opens=(42, 46))
        self.assertEqual((0, 0.0), (waited, clock.slept))
        self.assertEqual([startup_order.NORMAL], classes)
        self.assertTrue(held, "marks itself queued so the logon task steps aside")

    def test_after_others_waits_until_apps_stop_opening(self):
        # Today's real sign-in: the last startup app opened at +156 s.
        opens = (42, 46, 73, 103, 106, 133, 141, 153, 156)
        stop = startup_order.STOPS[2]
        _, clock, _, _ = _wait(["app", "--startup"], 2, at=42, opens=opens)
        started = clock.t - SIGNED_IN
        self.assertGreaterEqual(started, 156 + stop.quiet_seconds)
        self.assertLess(started, 156 + stop.quiet_seconds + startup_order.POLL_S + 1)

    def test_last_also_waits_for_the_processor(self):
        stop = startup_order.STOPS[3]
        _, clock, _, _ = _wait(["app", "--startup"], 3, at=42, opens=(50,),
                               cpu_busy_until=400)
        self.assertGreaterEqual(clock.t - SIGNED_IN, 400)
        self.assertLessEqual(clock.t - SIGNED_IN, 42 + stop.max_seconds + startup_order.POLL_S)

    def test_a_pc_that_never_settles_still_gets_the_app(self):
        for i in (2, 3):
            stop = startup_order.STOPS[i]
            opens = tuple(range(40, 2000, 10))
            _, clock, _, _ = _wait(["app", "--startup"], i, at=40, opens=opens,
                                   cpu_busy_until=99999)
            self.assertLessEqual(clock.slept, stop.max_seconds + startup_order.POLL_S)

    def test_a_relaunch_long_after_sign_in_never_waits(self):
        # Crash recovery and Windows restart pass --startup too.
        for kind in (startup_order.STARTUP_APPS, startup_order.EARLY):
            waited, clock, classes, _ = _wait(
                ["app", "--startup"], 3, kind=kind, at=startup_order.SIGN_IN_WINDOW_S + 5)
            self.assertEqual((0, 0.0, []), (waited, clock.slept, classes))
        waited, clock, _, _ = _wait(["app", "--startup"], 3, kind=startup_order.OTHER, at=20)
        self.assertEqual((0, 0.0), (waited, clock.slept))

    def test_never_below_normal_which_starves_on_a_busy_pc(self):
        for stop in startup_order.STOPS:
            self.assertIn(stop.load_class, (startup_order.NORMAL, startup_order.ABOVE_NORMAL))

    def test_each_stop_starts_later_than_the_one_before(self):
        for a, b in zip(startup_order.STOPS, startup_order.STOPS[1:]):
            self.assertLessEqual(a.wait_for_others, b.wait_for_others)
            self.assertLessEqual(a.quiet_seconds, b.quiet_seconds)
            self.assertLessEqual(a.min_seconds, b.min_seconds)
            self.assertLessEqual(a.max_seconds, b.max_seconds)
            self.assertLess((a.wait_for_others, a.quiet_seconds, a.cpu_settled),
                            (b.wait_for_others, b.quiet_seconds, b.cpu_settled))

    def test_captions_promise_no_fixed_time(self):
        for stop in startup_order.STOPS:
            self.assertNotRegex(stop.caption, r"\d")

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
        # brand is constants only and imports nothing: safe ahead of the guard.
        tree = ast.parse((ROOT / "startup_order.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        self.assertEqual({"brand", "ctypes", "json", "os", "sys", "time", "typing"}, names)
        brand_tree = ast.parse((ROOT / "brand.py").read_text(encoding="utf-8"))
        self.assertFalse([n for n in brand_tree.body
                          if isinstance(n, (ast.Import, ast.ImportFrom))])

    def test_the_logon_task_is_still_what_svchost_starts(self):
        # launch_kind tells the two sign-in launchers apart by parent process.
        self.assertEqual(startup_order.EARLY, startup_order.classify_launcher("svchost.exe"))
        self.assertEqual(startup_order.STARTUP_APPS,
                         startup_order.classify_launcher("Explorer.EXE"))
        self.assertEqual(startup_order.OTHER, startup_order.classify_launcher(""))
        self.assertEqual(startup_order.OTHER, startup_order.classify_launcher("cmd.exe"))

    def test_crash_recovery_relaunches_never_queue(self):
        src = (ROOT / "crash_watch.py").read_text(encoding="utf-8")
        self.assertIn('"--startup", "--relaunch"', src)
        self.assertIn('"--startup --relaunch"', src)
        for stop in range(len(startup_order.STOPS)):
            waited, clock, classes, _ = _wait(["app", "--startup", "--relaunch"], stop,
                                              kind=startup_order.EARLY, at=5)
            self.assertEqual((0, 0.0, []), (waited, clock.slept, classes))

    def test_a_one_file_build_looks_past_its_own_bootloader(self):
        procs = [(10, 1, "explorer.exe"), (20, 10, "FTC Whisper.exe"),
                 (30, 20, "FTC Whisper.exe"), (40, 2, "svchost.exe"),
                 (50, 40, "BrightLink Echo.exe")]
        self.assertEqual("explorer.exe",
                         startup_order._launcher_name(procs, 30, "FTC Whisper.exe"))
        self.assertEqual("svchost.exe",
                         startup_order._launcher_name(procs, 50, "BrightLink Echo.exe"))
        self.assertEqual("", startup_order._launcher_name(procs, 99, "x.exe"))

    def test_a_second_sign_in_launcher_still_exits_silently(self):
        i = self.src.index("def _ensure_single_instance")
        self.assertIn("_launched_at_sign_in()", self.src[i:i + 900])


if __name__ == "__main__":
    unittest.main()
