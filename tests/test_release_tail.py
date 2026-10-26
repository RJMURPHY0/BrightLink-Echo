"""Last words kept at the key release.

People let go of the key on the last syllable, not after it. Cutting the
recording at the release lost the end of the last word: Ryan's stored clips
("Should be fine now.", "carry on with this.") ended with speech still at full
level in their final 50ms. Two fixes, both pinned here:

- Recorder.stop() after mark_release() keeps taking audio while a word is still
  being spoken, until the newest audio has been quiet for _TAIL_QUIET_SECONDS,
  never past _TAIL_MAX_SECONDS after the release. A release in silence (the
  common case) waits for nothing, so the stop stays instant.
- The final tail decode gets FINAL_PAD seconds of silence after it, because the
  transducer drops a last word whose audio ends abruptly. The pad never reaches
  the returned tail audio.

No real audio stream is opened: blocks are fed straight into _audio_callback.
"""
import os
import sys
import threading
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recorder
from recorder import Recorder
from stream_session import StreamingSession

RATE = 16000
BLOCK = 320  # 20 ms
_LOUD = (0.1 * np.sin(np.arange(BLOCK) / 3.0)).astype(np.float32).reshape(-1, 1)
_QUIET = np.full((BLOCK, 1), 0.0002, dtype=np.float32)
# A TV across the room: clears the absolute floor test, far below the voice.
_ROOM = (0.008 * np.sin(np.arange(BLOCK) / 2.0)).astype(np.float32).reshape(-1, 1)


def _recording(rate=RATE):
    rec = Recorder()
    rec._warm_enabled = False
    rec._active_sample_rate = rate
    rec._recording = True
    rec._recording_started_ts = time.monotonic()
    rec._last_callback_ts = time.monotonic()
    return rec


class _Feeder(threading.Thread):
    """Calls the real callback every 20 ms; voiced while speaking(t) says so,
    where t is seconds since the feeder started."""

    def __init__(self, rec, speaking, room=None):
        super().__init__(daemon=True)
        self.rec, self.speaking = rec, speaking
        self.room = room or (lambda t: False)
        self.halt = threading.Event()
        self.t0 = time.monotonic()

    def run(self):
        n = 0
        while not self.halt.is_set():
            t = time.monotonic() - self.t0
            block = (_LOUD if self.speaking(t)
                     else _ROOM if self.room(t) else _QUIET)
            self.rec._audio_callback(block.copy(), BLOCK, None, None)
            n += 1
            delay = self.t0 + n * BLOCK / RATE - time.monotonic()
            if delay > 0:
                time.sleep(delay)


def _voiced_seconds(audio):
    n = len(audio) // BLOCK
    rms = np.sqrt(np.mean(audio[: n * BLOCK].reshape(n, BLOCK) ** 2, axis=1))
    return float(np.sum(rms > 0.01)) * BLOCK / RATE


def _m(end, voiced, rms=None):
    return (end, 0.02, (0.07 if voiced else 0.0002) if rms is None else rms,
            voiced)


class TailSettledTests(unittest.TestCase):
    def test_nothing_delivered_near_the_release_waits(self):
        marks = [_m(9.7, False)] * 10
        self.assertFalse(Recorder._tail_settled(marks, 10.0, 0.07))

    def test_mid_word_waits_until_the_release_itself_has_arrived(self):
        marks = [_m(9.9 + 0.02 * i, True) for i in range(5)]
        self.assertFalse(Recorder._tail_settled(marks, 10.0, 0.07))

    def test_quiet_before_the_release_settles_at_once(self):
        marks = [_m(9.9 + 0.02 * i, False) for i in range(8)]
        self.assertTrue(Recorder._tail_settled(marks, 10.0, 0.07))

    def test_a_word_still_being_spoken_is_not_settled(self):
        marks = [_m(9.9 + 0.02 * i, True) for i in range(8)]
        marks.append(_m(10.08, True))
        self.assertFalse(Recorder._tail_settled(marks, 10.0, 0.07))

    def test_short_closure_inside_a_word_is_not_an_end(self):
        marks = [_m(9.96, True), _m(9.98, True), _m(10.0, True),
                 _m(10.02, False), _m(10.04, False)]
        self.assertFalse(Recorder._tail_settled(marks, 10.0, 0.07))

    def test_word_that_ended_after_the_release_settles(self):
        marks = [_m(9.96, True), _m(9.98, True), _m(10.0, True),
                 _m(10.02, True)] + [_m(10.04 + 0.02 * i, False) for i in range(6)]
        self.assertTrue(Recorder._tail_settled(marks, 10.0, 0.07))

    def test_noise_after_a_finished_sentence_never_waits(self):
        marks = [_m(9.84 + 0.02 * i, False) for i in range(9)]
        marks += [_m(10.02, True), _m(10.04, True)]
        self.assertTrue(Recorder._tail_settled(marks, 10.0, 0.07))

    def test_soft_room_sound_is_not_the_users_voice(self):
        marks = [_m(9.9 + 0.02 * i, True, rms=0.006) for i in range(8)]
        self.assertTrue(Recorder._tail_settled(marks, 10.0, 0.07))


class ReleaseTailTests(unittest.TestCase):
    def _stop_after(self, speaking, release_at=0.5, room=None):
        rec = _recording()
        feed = _Feeder(rec, speaking, room)
        feed.start()
        try:
            time.sleep(release_at)
            release = time.monotonic()
            rec.mark_release(release)
            audio = rec.stop()
            took = time.monotonic() - release
        finally:
            feed.halt.set()
            feed.join(1.0)
        return rec, audio, took

    def test_word_still_being_spoken_at_release_is_kept(self):
        # Speech runs 150 ms past the release: that audio must be captured.
        rec, audio, took = self._stop_after(lambda t: t < 0.65)
        self.assertGreaterEqual(_voiced_seconds(audio), 0.6)
        self.assertGreaterEqual(took, 0.15)
        self.assertLess(took, recorder._TAIL_MAX_SECONDS + 0.15)

    def test_release_in_silence_waits_for_nothing(self):
        rec, audio, took = self._stop_after(lambda t: t < 0.2)
        self.assertLess(took, 0.06, f"stop waited {took * 1000:.0f} ms")
        self.assertGreaterEqual(_voiced_seconds(audio), 0.18)

    def test_tv_in_the_room_does_not_delay_the_stop(self):
        # Voice ends 0.3s before the release; the room keeps making sound.
        rec, audio, took = self._stop_after(lambda t: t < 0.2,
                                            room=lambda t: t >= 0.2)
        self.assertLess(took, 0.06, f"stop waited {took * 1000:.0f} ms")

    def test_room_sound_under_a_word_still_ends_with_the_word(self):
        rec, audio, took = self._stop_after(lambda t: t < 0.6,
                                            room=lambda t: True)
        self.assertGreaterEqual(_voiced_seconds(audio), 0.55)
        self.assertLess(took, 0.3)

    def test_wait_is_capped_when_speech_never_stops(self):
        rec, audio, took = self._stop_after(lambda t: True)
        self.assertGreaterEqual(took, recorder._TAIL_MAX_SECONDS - 0.03)
        self.assertLess(took, recorder._TAIL_MAX_SECONDS + 0.15)

    def test_dead_stream_never_holds_the_stop(self):
        rec = _recording()
        rec._last_callback_ts = time.monotonic() - 2.0
        rec._chunks.append(_LOUD.copy())
        rec._chunks_samples = BLOCK
        rec.mark_release()
        t0 = time.monotonic()
        rec.stop()
        self.assertLess(time.monotonic() - t0, 0.05)

    def test_no_release_mark_means_no_wait(self):
        rec = _recording()
        rec._chunks.append(_LOUD.copy())
        rec._chunks_samples = BLOCK
        t0 = time.monotonic()
        rec.stop()
        self.assertLess(time.monotonic() - t0, 0.05)
        self.assertEqual(rec.last_tail_ms, 0)

    def test_mark_outside_a_recording_is_ignored(self):
        rec = Recorder()
        rec.mark_release()
        self.assertEqual(rec._release_ts, 0.0)


class _Rec:
    def __init__(self, secs):
        rng = np.random.default_rng(0)
        self.a = (rng.standard_normal(int(secs * RATE)) * 0.1).astype(np.float32)
        self.active_sample_rate = RATE
        self.dropped_samples = 0
        self.is_recording = True

    def get_audio_range(self, start):
        return None

    def drop_audio_before(self, abs_):
        self.dropped_samples = abs_

    def stop(self):
        self.is_recording = False
        return self.a


class _Eng:
    def __init__(self):
        self.lengths = []

    def transcribe(self, audio, rate, **kw):
        self.lengths.append(len(audio))
        self.last = audio
        return "Push it to main."


class FinalPadTests(unittest.TestCase):
    def test_final_decode_gets_trailing_silence_and_tail_is_untouched(self):
        rec, eng = _Rec(2.0), _Eng()
        s = StreamingSession(rec, eng, auto_paragraphs=False)
        text, tail, rate = s.finalize()
        pad = int(StreamingSession.FINAL_PAD * RATE)
        self.assertEqual(text, "Push it to main.")
        self.assertEqual(eng.lengths, [len(rec.a) + pad])
        self.assertFalse(np.any(eng.last[-pad:]))
        self.assertEqual(len(tail), len(rec.a))


if __name__ == "__main__":
    unittest.main()
