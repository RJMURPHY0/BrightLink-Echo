"""Every mic_press_recovered report says why the stream was stale, and the
watchdog reopens the warm stream as soon as it sees the machine wake.

Fake streams only: no audio device is opened."""
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recorder  # noqa: E402


class StaleContextTests(unittest.TestCase):
    def _rec(self):
        r = recorder.Recorder.__new__(recorder.Recorder)
        r._lock = threading.Lock()
        r._last_callback_ts = 0.0
        r._stream_opened_ts = 0.0
        r._last_resume_ts = 0.0
        return r

    def test_numbers_only_and_unknowns_left_out(self):
        r = self._rec()
        ctx = r._stale_context(float("inf"))
        self.assertEqual({"heartbeat_age_ms": -1}, ctx)

    def test_stream_age_and_time_since_resume(self):
        r = self._rec()
        now = time.monotonic()
        r._stream_opened_ts = now - 84
        r._last_resume_ts = now - 30
        ctx = r._stale_context(1.5)
        self.assertEqual(1500, ctx["heartbeat_age_ms"])
        self.assertIn(ctx["stream_age_s"], (83, 84, 85))
        self.assertIn(ctx["since_resume_s"], (29, 30, 31))
        for v in ctx.values():
            self.assertIsInstance(v, int)

    def test_start_puts_the_context_into_every_recovery_mode(self):
        import inspect
        src = inspect.getsource(recorder.Recorder.start)
        self.assertEqual(src.count("self.last_start_recovery = {"),
                         src.count("**stale_ctx"))


class ResumeReopenTests(unittest.TestCase):
    def test_a_wall_clock_jump_reopens_the_warm_stream(self):
        r = recorder.Recorder.__new__(recorder.Recorder)
        r._warm_enabled = True
        r._monitor_active = r._aux_active = r._probe_active = False
        r._last_resume_ts = 0.0
        r._lock = threading.Lock()
        r._recording = False
        calls = []
        r._ensure_warm_stream = lambda **kw: calls.append(kw)
        r._stream_looks_alive = lambda: True
        r._stream_is_silently_dead = lambda: False
        r._last_record_activity_ts = 0.0

        walls = iter([1000.0, 1002.0, 1002.0 + 600.0])
        sleeps = {"n": 0}

        def fake_sleep(_s):
            sleeps["n"] += 1
            if sleeps["n"] > 2:
                raise StopIteration

        with mock.patch.object(recorder.time, "time", lambda: next(walls)), \
                mock.patch.object(recorder.time, "sleep", fake_sleep), \
                mock.patch("builtins.print"):
            with self.assertRaises(StopIteration):
                r._watchdog_loop()
        self.assertEqual([{"force_fresh": True}], calls)
        self.assertGreater(r._last_resume_ts, 0.0)

    def test_a_normal_tick_does_not_reopen(self):
        r = recorder.Recorder.__new__(recorder.Recorder)
        r._warm_enabled = True
        r._monitor_active = r._aux_active = r._probe_active = False
        r._last_resume_ts = 0.0
        r._lock = threading.Lock()
        r._recording = False
        calls = []
        r._ensure_warm_stream = lambda **kw: calls.append(kw)
        r._stream_looks_alive = lambda: True
        r._stream_is_silently_dead = lambda: False
        r._last_record_activity_ts = 0.0
        walls = iter([1000.0, 1002.1, 1004.2])
        n = {"n": 0}

        def fake_sleep(_s):
            n["n"] += 1
            if n["n"] > 2:
                raise StopIteration

        with mock.patch.object(recorder.time, "time", lambda: next(walls)), \
                mock.patch.object(recorder.time, "sleep", fake_sleep):
            with self.assertRaises(StopIteration):
                r._watchdog_loop()
        self.assertEqual([], calls)
        self.assertEqual(0.0, r._last_resume_ts)


if __name__ == "__main__":
    unittest.main()
