"""Memory footprint: hold only the models the current engine needs.

Measured 2026-10-01: Parakeet plus both whisper models held ~1.9 GB working
set and ~5.7 GB commit, while whisper only ever served as Parakeet's fallback
(and History Retry). And one whole-clip Parakeet pass kept ~400 MB of ONNX
arena for the rest of the session. These pin the fixes without touching what
the user gets: whisper still serves a press made during Parakeet's load, a
dictation that began on whisper finishes on it, and streamed dictation never
pays for an arena shrink.
"""

import os
import sys
import threading
import types
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asr_engine
import transcriber


class _FakeWhisper:
    def __init__(self, busy_until=0):
        self.is_loaded = True
        self.unload_calls = 0
        self.load_calls = 0
        self._busy_until = busy_until

    def unload(self):
        self.unload_calls += 1
        if self.unload_calls <= self._busy_until:
            return False
        self.is_loaded = False
        return True

    def load_model(self):
        self.load_calls += 1
        self.is_loaded = True


def _app_double(parakeet_loaded=True, state="idle"):
    import app as app_mod
    a = app_mod.WhisperFlowApp.__new__(app_mod.WhisperFlowApp)
    a.config = types.SimpleNamespace(use_parakeet=True, language="en",
                                     parakeet_version="v2")
    a.parakeet = types.SimpleNamespace(is_loaded=parakeet_loaded)
    a.fast_transcriber = _FakeWhisper()
    a.transcriber = _FakeWhisper()
    states = {"idle": app_mod.AppState.IDLE,
              "recording": app_mod.AppState.RECORDING}
    a.hotkey_manager = types.SimpleNamespace(state=states[state])
    return a, app_mod


class TranscriberUnloadTests(unittest.TestCase):

    def _t(self):
        t = transcriber.Transcriber(model_size="base.en")
        t._model = object()
        return t

    def test_unload_frees_the_model(self):
        t = self._t()
        self.assertTrue(t.unload())
        self.assertFalse(t.is_loaded)

    def test_unload_refuses_while_a_transcription_holds_the_lock(self):
        t = self._t()
        with t._transcribe_lock:
            self.assertFalse(t.unload())
        self.assertTrue(t.is_loaded)

    def test_transcribe_after_unload_loads_the_model_again(self):
        t = self._t()
        t.unload()
        loaded = []

        def fake_load():
            loaded.append(1)
            t._model = object()

        with mock.patch.object(t, "load_model", fake_load), \
                mock.patch.object(t, "_run", lambda *a, **k: "hello"):
            out = t.transcribe(np.ones(1600, dtype=np.float32), 16000)
        self.assertEqual(out, "hello")
        self.assertTrue(loaded)


class WhisperFallbackTests(unittest.TestCase):

    def test_parakeet_ready_frees_both_whisper_models(self):
        a, _ = _app_double()
        a._release_whisper_fallback()
        self.assertFalse(a.fast_transcriber.is_loaded)
        self.assertFalse(a.transcriber.is_loaded)

    def test_waits_for_a_dictation_that_began_on_whisper(self):
        a, app_mod = _app_double(state="recording")
        sleeps = []

        def fake_sleep(s):
            sleeps.append(s)
            a.hotkey_manager.state = app_mod.AppState.IDLE

        with mock.patch.object(app_mod.time, "sleep", fake_sleep):
            a._release_whisper_fallback()
        self.assertEqual(len(sleeps), 1)
        self.assertFalse(a.fast_transcriber.is_loaded)

    def test_a_busy_model_is_retried_not_dropped_mid_decode(self):
        a, app_mod = _app_double()
        a.fast_transcriber = _FakeWhisper(busy_until=2)
        with mock.patch.object(app_mod.time, "sleep", lambda s: None):
            a._release_whisper_fallback()
        self.assertEqual(a.fast_transcriber.unload_calls, 3)
        self.assertFalse(a.fast_transcriber.is_loaded)

    def test_failed_parakeet_load_keeps_whisper_in_charge(self):
        a, _ = _app_double(parakeet_loaded=False)
        a.fast_transcriber.is_loaded = False
        a.transcriber.is_loaded = False
        with mock.patch.object(a, "_init_parakeet", lambda: None):
            a._preload_parakeet()
        self.assertTrue(a.fast_transcriber.is_loaded)
        self.assertTrue(a.transcriber.is_loaded)

    def test_accurate_model_preloads_unless_parakeet_files_are_present(self):
        a, _ = _app_double()
        with mock.patch.object(asr_engine, "model_files_present",
                               lambda **kw: True):
            self.assertTrue(a._parakeet_expected())
        with mock.patch.object(asr_engine, "model_files_present",
                               lambda **kw: False):
            self.assertFalse(a._parakeet_expected())
        a.config.language = "fr"
        with mock.patch.object(asr_engine, "model_files_present",
                               lambda **kw: True):
            self.assertFalse(a._parakeet_expected())


class ArenaShrinkTests(unittest.TestCase):

    def _wrap(self):
        seen = []
        inner = types.SimpleNamespace(
            run=lambda out, feed, ro=None: seen.append(ro) or ["ok"],
            get_inputs=lambda: "inputs")
        return asr_engine._ArenaShrinkingSession(inner, "SHRINK", 3000), seen

    def _feed(self, frames):
        return {"audio_signal": np.zeros((1, 128, frames), np.float32)}

    def test_streamed_chunk_runs_unchanged(self):
        s, seen = self._wrap()
        s.run(["outputs"], self._feed(1800))  # an 18 s committed chunk
        self.assertEqual(seen, [None])

    def test_whole_clip_run_shrinks_the_arena(self):
        s, seen = self._wrap()
        s.run(["outputs"], self._feed(22900))
        self.assertEqual(seen, ["SHRINK"])

    def test_other_attributes_pass_through(self):
        s, _ = self._wrap()
        self.assertEqual(s.get_inputs(), "inputs")


if __name__ == "__main__":
    unittest.main()
