"""The speech model is kept in memory between dictations, at no cost to them."""

import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import memory_guard
import model_warmth
from asr_engine import ParakeetTranscriber
from model_warmth import IDLE_STOP_SECONDS, PRESS_STALE_SECONDS, REFRESH_SECONDS, ModelKeepWarm

ROOT = Path(__file__).resolve().parent.parent


class FakeEngine:
    def __init__(self, last_used=0.0, ms=200):
        self.last_used = last_used
        self.ms = ms
        self.passes = 0

    def keep_warm(self):
        self.passes += 1
        return self.ms


def make(now=1000.0, last_used=0.0, busy=False, idle=0.0, battery=False, active=True,
         ms=200, paged=None):
    eng = FakeEngine(last_used, ms)
    return eng, ModelKeepWarm(
        eng, is_busy=lambda: busy, is_active=lambda: active, on_paged_in=paged,
        idle_seconds=lambda: idle, battery=lambda: battery, monotonic=lambda: now)


class Decisions(unittest.TestCase):
    def test_refreshes_when_stale(self):
        eng, kw = make(last_used=1000.0 - REFRESH_SECONDS)
        self.assertEqual(200, kw.tick())
        self.assertEqual(1, eng.passes)

    def test_leaves_a_recently_used_model_alone(self):
        eng, kw = make(last_used=1000.0 - REFRESH_SECONDS + 1)
        self.assertIsNone(kw.tick())
        self.assertEqual(0, eng.passes)

    def test_never_during_a_dictation(self):
        eng, kw = make(busy=True)
        self.assertIsNone(kw.tick())
        self.assertEqual(0, eng.passes)

    def test_stops_when_the_person_is_away_and_resumes_when_back(self):
        eng, kw = make(idle=IDLE_STOP_SECONDS)
        self.assertIsNone(kw.tick())
        kw._idle_seconds = lambda: 1.0
        self.assertEqual(200, kw.tick())

    def test_never_refreshes_on_battery(self):
        eng, kw = make(battery=True)
        self.assertIsNone(kw.tick())
        self.assertEqual(0, eng.passes)

    def test_nothing_while_another_engine_is_in_charge(self):
        eng, kw = make(active=False)
        kw.note_press()
        self.assertIsNone(kw.tick())
        self.assertEqual(0, eng.passes)
        self.assertFalse(kw._press_pending)


class Press(unittest.TestCase):
    def test_a_press_after_a_quiet_spell_warms_even_on_battery_and_while_busy(self):
        eng, kw = make(last_used=1000.0 - PRESS_STALE_SECONDS, busy=True, battery=True,
                       idle=IDLE_STOP_SECONDS)
        kw.note_press()
        self.assertEqual(200, kw.tick())
        self.assertEqual(1, eng.passes)
        self.assertIsNone(kw.tick(), "one pass per press")

    def test_back_to_back_dictations_cost_nothing(self):
        eng, kw = make(last_used=1000.0 - PRESS_STALE_SECONDS + 1)
        kw.note_press()
        self.assertFalse(kw._press_pending)
        self.assertIsNone(kw.tick())

    def test_note_press_never_runs_a_pass_itself(self):
        eng, kw = make()
        kw.note_press()
        self.assertEqual(0, eng.passes)


class PagedInEvidence(unittest.TestCase):
    def test_reports_a_slow_pass(self):
        seen = []
        _eng, kw = make(ms=model_warmth.PAGED_IN_MS,
                        paged=lambda ms, reason: seen.append((ms, reason)))
        kw.tick()
        self.assertEqual([(model_warmth.PAGED_IN_MS, "refresh")], seen)

    def test_a_normal_pass_says_nothing(self):
        seen = []
        _eng, kw = make(ms=model_warmth.PAGED_IN_MS - 1,
                        paged=lambda ms, reason: seen.append(ms))
        kw.tick()
        self.assertEqual([], seen)


def _engine_with(model):
    eng = ParakeetTranscriber(vad_gate=False)
    eng._model = model
    return eng


class EnginePass(unittest.TestCase):
    def test_returns_time_and_updates_last_used(self):
        model = mock.Mock()
        eng = _engine_with(model)
        self.assertIsInstance(eng.keep_warm(), int)
        self.assertGreater(eng.last_used, 0.0)
        audio = model.recognize.call_args[0][0]
        self.assertEqual(16000, len(audio))
        self.assertEqual(np.float32, audio.dtype)

    def test_never_waits_for_a_real_decode(self):
        model = mock.Mock()
        eng = _engine_with(model)
        with eng._transcribe_lock:
            self.assertIsNone(eng.keep_warm())
        model.recognize.assert_not_called()

    def test_releases_the_lock_when_the_model_fails(self):
        model = mock.Mock()
        model.recognize.side_effect = RuntimeError("boom")
        eng = _engine_with(model)
        self.assertIsNone(eng.keep_warm())
        self.assertTrue(eng._transcribe_lock.acquire(blocking=False))
        eng._transcribe_lock.release()

    def test_does_nothing_before_the_model_loads(self):
        self.assertIsNone(ParakeetTranscriber(vad_gate=False).keep_warm())

    def test_a_real_decode_counts_as_use(self):
        model = mock.Mock()
        model.recognize.return_value = "hello"
        eng = _engine_with(model)
        eng.transcribe(np.ones(16000, dtype=np.float32) * 0.1, 16000)
        self.assertGreater(eng.last_used, 0.0)


class ThreadBehaviour(unittest.TestCase):
    def test_a_press_wakes_the_loop_at_once(self):
        ran = threading.Event()

        class E(FakeEngine):
            def keep_warm(self):
                ran.set()
                return 200

        kw = ModelKeepWarm(E(), is_busy=lambda: False)
        kw.start()
        try:
            kw.note_press()
            self.assertTrue(ran.wait(5.0))
        finally:
            kw.stop()


class ProcessStats(unittest.TestCase):
    def test_own_figures_are_real_numbers(self):
        # Every memory_pressure report said 0 and 0 until 2026-11-05.
        self.assertGreater(memory_guard.own_private_mb(), 0)
        stats = memory_guard.own_process_stats()
        for key in ("ws_mb", "private_mb", "faults", "cpu_ms"):
            self.assertIn(key, stats)
        self.assertGreater(stats["ws_mb"], 0)
        self.assertGreater(stats["faults"], 0)
        self.assertGreaterEqual(memory_guard.own_gdi_count(), 0)


class Wiring(unittest.TestCase):
    src = (ROOT / "app.py").read_text(encoding="utf-8")

    def test_press_only_notes_the_press(self):
        self.assertIn("_warm.note_press()", self.src)
        self.assertNotIn(".keep_warm()", self.src)

    def test_guard_docs_stay_true(self):
        # Paging the model out is the very thing this prevents.
        for name in ("model_warmth.py", "memory_guard.py", "app.py"):
            code = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("EmptyWorkingSet(", code)
            self.assertNotIn("SetProcessWorkingSetSize", code)


if __name__ == "__main__":
    unittest.main()
