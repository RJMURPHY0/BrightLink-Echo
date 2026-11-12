"""The start/stop cues play through a warm WASAPI stream, never winsound first.

winsound.PlaySound (winmm) stalls Echo's own MME and DirectSound microphone
input for 300-520 ms and DROPS that audio, and the start cue plays at the
press, so it cost the first half second of speech (measured 12 Nov 2026: a
2.0 s window kept 1.54-1.73 s with the winsound cue, 1.98 s with the WASAPI
one). These tests pin the player with a fake sounddevice: no real audio device
is opened.
"""
import os
import sys
import threading
import types
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feedback  # noqa: E402
import pa_guard  # noqa: E402


class _FakeStream:
    instances: list = []
    fail_open = False

    def __init__(self, **kw):
        if _FakeStream.fail_open:
            raise RuntimeError("no device")
        self.kw = kw
        self.started = self.closed = False
        _FakeStream.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    def pull(self, frames):
        """What PortAudio would take from the callback for one block."""
        out = np.zeros((frames, 1), dtype=np.int16)
        self.kw["callback"](out, frames, None, None)
        return out[:, 0].copy()


def _fake_sd(wasapi=True):
    sd = types.SimpleNamespace()
    apis = [{"name": "MME", "default_output_device": 3}]
    if wasapi:
        apis.append({"name": "Windows WASAPI", "default_output_device": 8})
    sd.query_hostapis = lambda: apis
    sd.OutputStream = _FakeStream
    sd.WasapiSettings = lambda **kw: ("wasapi", kw)
    return sd


class CuePlayerTests(unittest.TestCase):
    def setUp(self):
        _FakeStream.instances = []
        _FakeStream.fail_open = False
        self.player = feedback._CuePlayer()
        self.hooks = mock.patch.object(pa_guard, "_before", [])
        self.hooks2 = mock.patch.object(pa_guard, "_after", [])
        self.hooks.start()
        self.hooks2.start()
        self.addCleanup(self.hooks.stop)
        self.addCleanup(self.hooks2.stop)
        # No real timers left running after a test.
        self.timer = mock.patch.object(feedback.threading, "Timer",
                                       lambda *a, **k: mock.Mock())
        self.timer.start()
        self.addCleanup(self.timer.stop)

    def _with_sd(self, sd):
        return mock.patch.dict(sys.modules, {"sounddevice": sd})

    def test_opens_the_wasapi_default_output_in_shared_auto_convert_mode(self):
        with self._with_sd(_fake_sd()):
            self.assertTrue(self.player.warm())
        s = _FakeStream.instances[0]
        self.assertEqual(8, s.kw["device"])
        self.assertEqual(feedback._SR, s.kw["samplerate"])
        self.assertEqual(("wasapi", {"auto_convert": True}), s.kw["extra_settings"])
        self.assertTrue(s.started)

    def test_a_cue_plays_its_exact_samples_then_silence(self):
        with self._with_sd(_fake_sd()):
            self.assertTrue(self.player.play("start"))
        s = _FakeStream.instances[0]
        pcm = feedback._get_pcm("start")
        got = np.concatenate([s.pull(441) for _ in range(len(pcm) // 441 + 3)])
        np.testing.assert_array_equal(pcm, got[:len(pcm)])
        self.assertFalse(got[len(pcm):].any(), "silence after the cue")

    def test_the_pcm_is_the_same_sound_winsound_played(self):
        # Same numbers as the WAV: the sound is not allowed to change.
        import io, wave
        with wave.open(io.BytesIO(feedback._get_sound("stop"))) as w:
            wav = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        np.testing.assert_array_equal(wav, feedback._get_pcm("stop"))

    def test_the_stream_is_reused_not_reopened_per_cue(self):
        with self._with_sd(_fake_sd()):
            for name in ("start", "stop", "start"):
                self.assertTrue(self.player.play(name))
        self.assertEqual(1, len(_FakeStream.instances))

    def test_no_wasapi_means_winsound(self):
        with self._with_sd(_fake_sd(wasapi=False)):
            self.assertFalse(self.player.play("start"))
            self.assertFalse(self.player.play("start"))
        self.assertEqual([], _FakeStream.instances)

    def test_open_failures_fall_back_and_stop_retrying(self):
        _FakeStream.fail_open = True
        with self._with_sd(_fake_sd()), mock.patch("builtins.print"):
            for _ in range(feedback._CUE_MAX_FAILS + 2):
                self.assertFalse(self.player.play("start"))
        self.assertEqual(feedback._CUE_MAX_FAILS, self.player._fails)

    def test_play_sound_uses_winsound_only_when_the_stream_cannot_play(self):
        calls = []
        fake_ws = types.SimpleNamespace(
            SND_MEMORY=4, PlaySound=lambda data, flags: calls.append(flags))
        with mock.patch.dict(sys.modules, {"winsound": fake_ws}), \
                mock.patch.object(feedback._CUE_PLAYER, "play", return_value=True):
            feedback._play_sound("start")
        self.assertEqual([], calls)
        with mock.patch.dict(sys.modules, {"winsound": fake_ws}), \
                mock.patch.object(feedback._CUE_PLAYER, "play", return_value=False):
            feedback._play_sound("start")
        self.assertEqual([4], calls)

    def test_a_portaudio_reinit_closes_the_stream_and_schedules_a_reopen(self):
        scheduled = []
        with self._with_sd(_fake_sd()):
            self.player.play("start")
            s = _FakeStream.instances[0]
            with mock.patch.object(
                    feedback.threading, "Timer",
                    lambda delay, fn: scheduled.append((delay, fn)) or mock.Mock()):
                with pa_guard.PORTAUDIO_LOCK:
                    pa_guard.notify_before_reinit()
                    self.assertTrue(s.closed)
                    self.assertFalse(self.player.is_open())
                    pa_guard.notify_after_reinit()
            self.assertEqual(feedback._CUE_REOPEN_DELAY, scheduled[-1][0])
            scheduled[-1][1]()          # the delayed reopen
        self.assertTrue(self.player.is_open())
        self.assertEqual(2, len(_FakeStream.instances))

    def test_no_reopen_after_a_reinit_once_the_warm_window_has_passed(self):
        scheduled = []
        with self._with_sd(_fake_sd()):
            self.player.play("start")
            self.player._last_use -= feedback._CUE_WARM_SECONDS + 5
            with mock.patch.object(
                    feedback.threading, "Timer",
                    lambda delay, fn: scheduled.append(fn) or mock.Mock()):
                with pa_guard.PORTAUDIO_LOCK:
                    pa_guard.notify_before_reinit()
                    pa_guard.notify_after_reinit()
        self.assertEqual([], scheduled)

    def test_idle_close_shuts_the_stream_after_the_warm_window(self):
        with self._with_sd(_fake_sd()):
            self.player.play("start")
            self.player._last_use -= feedback._CUE_WARM_SECONDS + 5
            self.player._idle_close()
        self.assertFalse(self.player.is_open())
        self.assertTrue(_FakeStream.instances[0].closed)


def _held_elsewhere() -> bool:
    """True when some other thread holds PORTAUDIO_LOCK (RLock has no
    locked() before Python 3.13)."""
    got = []

    def probe():
        ok = pa_guard.PORTAUDIO_LOCK.acquire(blocking=False)
        got.append(ok)
        if ok:
            pa_guard.PORTAUDIO_LOCK.release()   # same thread that took it

    t = threading.Thread(target=probe)
    t.start(); t.join()
    return not got[0]


def _held_by_me() -> bool:
    return pa_guard.PORTAUDIO_LOCK._is_owned()


class RecorderReinitTests(unittest.TestCase):
    def test_refresh_runs_the_hooks_under_the_portaudio_lock(self):
        import recorder
        seen = []

        def before():
            seen.append(("before", _held_by_me()))

        def after():
            seen.append(("after", _held_by_me()))

        rec = recorder.Recorder.__new__(recorder.Recorder)
        rec._monitor_active = rec._probe_active = False
        with mock.patch.object(pa_guard, "_before", [before]), \
                mock.patch.object(pa_guard, "_after", [after]), \
                mock.patch.object(recorder.sd, "_terminate",
                                  lambda: seen.append(("terminate", None))), \
                mock.patch.object(recorder.sd, "_initialize",
                                  lambda: seen.append(("initialize", None))), \
                mock.patch.object(recorder.time, "sleep", lambda s: None), \
                mock.patch("builtins.print"):
            rec._refresh_portaudio()
        self.assertEqual([("before", True), ("terminate", None),
                          ("initialize", None), ("after", True)], seen)
        self.assertFalse(_held_by_me())
        self.assertFalse(_held_elsewhere())

    def test_refresh_still_runs_when_a_cue_hangs_on_the_lock(self):
        import recorder
        rec = recorder.Recorder.__new__(recorder.Recorder)
        rec._monitor_active = rec._probe_active = False
        ran = []
        held = threading.Event()
        release = threading.Event()

        def hog():
            with pa_guard.PORTAUDIO_LOCK:
                held.set()
                release.wait(5)

        t = threading.Thread(target=hog, daemon=True)
        t.start()
        held.wait(2)
        try:
            with mock.patch.object(pa_guard, "REINIT_WAIT_SECONDS", 0.05), \
                    mock.patch.object(recorder.sd, "_terminate",
                                      lambda: ran.append("terminate")), \
                    mock.patch.object(recorder.sd, "_initialize",
                                      lambda: ran.append("initialize")), \
                    mock.patch("builtins.print"):
                rec._refresh_portaudio()
        finally:
            release.set()
            t.join(2)
        self.assertEqual(["terminate", "initialize"], ran)

    def test_the_warm_open_waits_for_a_cue_that_is_opening(self):
        import recorder
        rec = recorder.Recorder.__new__(recorder.Recorder)
        rec._stream_lifecycle_lock = threading.Lock()
        rec._lock = threading.Lock()
        rec._recording = False
        rec._stream = None
        rec._active_device_name = ""
        rec._active_sample_rate = 16000
        rec.sample_rate = 16000
        rec._preroll = []
        rec._preroll_samples = 0
        order = []
        cue_open = threading.Event()
        release = threading.Event()

        def cue():
            with pa_guard.PORTAUDIO_LOCK:
                cue_open.set()
                release.wait(2)
                order.append("cue opened")

        class _S:
            def start(self):
                pass

        def open_input():
            order.append("mic opened")
            return _S()

        rec._open_best_input_stream = open_input
        t = threading.Thread(target=cue, daemon=True)
        t.start()
        cue_open.wait(2)
        threading.Timer(0.1, release.set).start()
        with mock.patch("builtins.print"):
            self.assertTrue(rec._ensure_warm_stream())
        t.join(2)
        self.assertEqual(["cue opened", "mic opened"], order)


if __name__ == "__main__":
    unittest.main()
