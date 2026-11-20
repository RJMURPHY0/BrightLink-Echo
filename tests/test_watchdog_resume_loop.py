"""A slow warm-stream reopen must not look like the machine waking from sleep.

Field crash (error_events 3451, v1.8.41, 3294, v1.8.39): under RAM pressure a
reopen took ~20 s. The watchdog measured the wall-clock gap from the top of the
previous tick, so that reopen's own duration counted as "asleep", the next tick
saw a wake, reopened again, and so on. Each cycle ran PortAudio terminate and
initialise, and the process died natively inside sd._terminate.

Fake clock only: no audio device is opened."""
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recorder  # noqa: E402


def _run_watchdog(reopen_seconds: float, real_sleep_at_tick: int | None,
                  ticks: int = 12) -> int:
    """Run the watchdog loop on a fake clock; return how many reopens it made."""
    r = recorder.Recorder.__new__(recorder.Recorder)
    r._warm_enabled = True
    r._monitor_active = r._aux_active = r._probe_active = False
    r._last_resume_ts = 0.0
    r._lock = threading.Lock()
    r._recording = False
    r._last_record_activity_ts = 0.0
    r._stream_looks_alive = lambda: True
    r._stream_is_silently_dead = lambda: False

    clock = {"t": 1000.0, "ticks": 0}
    reopens = []

    def fake_time():
        return clock["t"]

    def fake_sleep(seconds):
        clock["ticks"] += 1
        if clock["ticks"] > ticks:
            raise StopIteration
        clock["t"] += seconds
        if clock["ticks"] == real_sleep_at_tick:
            clock["t"] += 600.0  # the lid really was closed

    def fake_reopen(**kwargs):
        reopens.append(kwargs)
        clock["t"] += reopen_seconds  # the reopen itself takes this long

    r._ensure_warm_stream = fake_reopen
    with mock.patch.object(recorder.time, "time", fake_time), \
            mock.patch.object(recorder.time, "sleep", fake_sleep), \
            mock.patch("builtins.print"):
        with unittest.TestCase().assertRaises(StopIteration):
            r._watchdog_loop()
    return len(reopens)


class WatchdogResumeLoopTests(unittest.TestCase):
    def test_slow_reopen_after_a_real_sleep_reopens_once(self):
        # Before the fix: 11 reopens (every tick after the wake).
        self.assertEqual(1, _run_watchdog(reopen_seconds=22.0,
                                          real_sleep_at_tick=2))

    def test_slow_reopen_alone_never_counts_as_a_wake(self):
        self.assertEqual(0, _run_watchdog(reopen_seconds=22.0,
                                          real_sleep_at_tick=None))

    def test_a_real_sleep_still_reopens_the_stream(self):
        self.assertEqual(1, _run_watchdog(reopen_seconds=0.0,
                                          real_sleep_at_tick=5))


if __name__ == "__main__":
    unittest.main()
