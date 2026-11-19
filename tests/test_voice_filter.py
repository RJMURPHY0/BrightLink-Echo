"""Voice isolation must only ever remove audio it is sure is someone else,
and must never cost time at the stop.

Pinned here:
  * off is the speech gate and decode exactly as before: the engine without
    voice_spans runs the v1.8.39 gate byte for byte, and a session without a
    track calls the engine with exactly the arguments it always did;
  * the voice is judged WHILE the user talks (VoiceTrack): finalize never
    calls the speaker model, and a window still being judged at the stop
    protects the audio it covers;
  * no voiceprint yet, a missing or failing model, or doubt => nothing removed;
  * only the START or END of a clip is ever cut, never the middle, and only
    when a window confidently matches the user;
  * a cut that would leave no speech removes nothing; quiet audio is never
    judged, so it is never cut; the 3 s edge keep never reaches into a cut;
  * Live Typing is never filtered;
  * once enrolled, a dictation that sounds like someone else never joins the
    voiceprint; the voiceprint belongs to one signed-in account; switching the
    feature off deletes it.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from typing import Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice_filter as vf                       # noqa: E402
from asr_engine import ParakeetTranscriber      # noqa: E402
from stream_session import StreamingSession     # noqa: E402

SR = 16000
USER = np.eye(8, dtype=np.float32)[0]
OTHER = np.eye(8, dtype=np.float32)[1]
U_AMP, O_AMP = 0.1, 0.05


class _FakeEmbedder:
    """The voice is told by amplitude: U_AMP is the user, O_AMP someone else.
    A window over both sounds like a mix in proportion to its samples."""

    def __init__(self, fail=False, delay=0.0):
        self.fail = fail
        self.delay = delay
        self.calls = 0
        self.last_error = "fake model failed" if fail else ""

    def embed_many(self, clips):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            return None
        out = []
        for c in clips:
            a = np.abs(c)
            u = float(np.mean(np.isclose(a, U_AMP, atol=0.01)))
            o = float(np.mean(np.isclose(a, O_AMP, atol=0.01)))
            v = USER * u + OTHER * o if (u + o) else USER
            out.append(v / max(np.linalg.norm(v), 1e-9))
        return np.stack(out)

    def embed(self, a):
        res = self.embed_many([a])
        return None if res is None else res[0]


def _profile(tmp, ready=True):
    p = vf.VoiceProfile(os.path.join(tmp, "vp.json"))
    if ready:
        for _ in range(vf.MIN_ENROLL):
            p.add(USER.copy(), save=False)
    return p


def _voice(seconds, amp):
    t = np.arange(int(seconds * SR))
    return (amp * np.where(np.sin(2 * np.pi * 180 * t / SR) >= 0, 1.0, -1.0)).astype(np.float32)


def _office_clip():
    """Colleague 4 s, user 6 s, colleague 4 s."""
    return np.concatenate([_voice(4, O_AMP), _voice(6, U_AMP), _voice(4, O_AMP)])


def _track_spans(tmp, clip, emb=None, feed_step=None, judge=True):
    """Feed a clip to a VoiceTrack the way the session does and decide."""
    f = vf.VoiceFilter(emb or _FakeEmbedder(), _profile(tmp))
    t = vf.VoiceTrack(f, threaded=False, log=lambda m: None)
    step = feed_step or len(clip)
    for at in range(0, len(clip), step):
        t.feed(at, clip[at:at + step])
        while judge and t.step():
            pass
    return t, t.spans()


class FilterDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _filter(self, **kw):
        return vf.VoiceFilter(_FakeEmbedder(**kw), _profile(self.tmp))

    def test_colleague_before_and_after_is_cut(self):
        spans = self._filter().other_spans(_office_clip())
        self.assertEqual(len(spans), 2)
        (h0, h1), (t0, t1) = spans
        self.assertEqual(h0, 0)
        self.assertLessEqual(h1, 4 * SR, "the head cut reached the user")
        self.assertGreaterEqual(t0, 10 * SR, "the tail cut reached the user")
        self.assertEqual(t1, 14 * SR)

    def test_own_voice_is_never_cut(self):
        self.assertEqual(self._filter().other_spans(_voice(12, U_AMP)), [])

    def test_middle_is_never_cut(self):
        clip = np.concatenate([_voice(5, U_AMP), _voice(5, O_AMP), _voice(5, U_AMP)])
        self.assertEqual(self._filter().other_spans(clip), [])

    def test_someone_else_only_is_never_cut(self):
        self.assertEqual(self._filter().other_spans(_voice(12, O_AMP)), [])

    def test_no_voiceprint_means_no_filtering(self):
        emb = _FakeEmbedder()
        f = vf.VoiceFilter(emb, _profile(self.tmp, ready=False))
        self.assertEqual(f.other_spans(_office_clip()), [])
        self.assertEqual(emb.calls, 0)

    def test_model_failure_means_no_filtering(self):
        self.assertEqual(self._filter(fail=True).other_spans(_office_clip()), [])

    def test_quiet_colleague_is_never_judged(self):
        clip = np.concatenate([_voice(4, 0.001), _voice(6, U_AMP)])
        self.assertEqual(self._filter().other_spans(clip), [])

    def test_cut_keeps_a_margin_before_the_user(self):
        head_end = self._filter().other_spans(_office_clip())[0][1]
        self.assertLessEqual(head_end, 4 * SR - int(vf.KEEP_S * SR))


class TrackTests(unittest.TestCase):
    """The in-recording judge must reach the same decision as the batch one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_same_decision_as_batch_when_fed_in_ticks(self):
        clip = _office_clip()
        batch = vf.VoiceFilter(_FakeEmbedder(), _profile(self.tmp)).other_spans(clip)
        _t, spans = _track_spans(self.tmp, clip, feed_step=int(0.3 * SR))
        # The track judges on a grid from the start, the batch tail scan from
        # the end; both must cut both colleagues and never the user.
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0], batch[0])
        self.assertGreaterEqual(spans[1][0], 10 * SR)
        self.assertEqual(spans[1][1], len(clip))

    def test_own_voice_and_middle_never_cut(self):
        self.assertEqual(_track_spans(self.tmp, _voice(12, U_AMP))[1], [])
        mid = np.concatenate([_voice(5, U_AMP), _voice(5, O_AMP), _voice(5, U_AMP)])
        self.assertEqual(_track_spans(self.tmp, mid, feed_step=SR)[1], [])

    def test_unjudged_windows_protect(self):
        # Nothing judged yet (the model is behind): nothing is cut.
        _t, spans = _track_spans(self.tmp, _office_clip(), judge=False)
        self.assertEqual(spans, [])

    def test_lagging_tail_is_not_cut(self):
        clip = _office_clip()
        f = vf.VoiceFilter(_FakeEmbedder(), _profile(self.tmp))
        t = vf.VoiceTrack(f, threaded=False, log=lambda m: None)
        t.feed(0, clip[:11 * SR])
        while t.step():
            pass
        t.feed(0, clip)          # the last 3 s arrive at the stop, unjudged
        spans = t.spans()
        self.assertEqual(len(spans), 1, "a tail nobody judged was cut")
        self.assertEqual(spans[0][0], 0)

    def test_model_failure_and_no_voiceprint_cut_nothing(self):
        _t, spans = _track_spans(self.tmp, _office_clip(), emb=_FakeEmbedder(fail=True))
        self.assertEqual(spans, [])
        f = vf.VoiceFilter(_FakeEmbedder(), _profile(self.tmp, ready=False))
        t = vf.VoiceTrack(f, threaded=False, log=lambda m: None)
        t.feed(0, _office_clip())
        self.assertFalse(t.step())
        self.assertEqual(t.spans(), [])

    def test_gap_in_the_audio_stops_the_track(self):
        f = vf.VoiceFilter(_FakeEmbedder(), _profile(self.tmp))
        t = vf.VoiceTrack(f, threaded=False, log=lambda m: None)
        t.feed(0, _voice(2, U_AMP))
        t.feed(5 * SR, _voice(2, U_AMP))
        self.assertTrue(t.failed)
        self.assertEqual(t.spans(), [])

    def test_spans_never_call_the_model(self):
        emb = _FakeEmbedder()
        t, _ = _track_spans(self.tmp, _office_clip(), emb=emb, feed_step=SR)
        before = emb.calls
        t.spans()
        t.spans(head_only=True)
        self.assertEqual(emb.calls, before)

    def test_threaded_track_judges_in_the_background_and_close_never_waits(self):
        emb = _FakeEmbedder(delay=0.3)
        t = vf.VoiceTrack(vf.VoiceFilter(emb, _profile(self.tmp)), log=lambda m: None)
        t.feed(0, _voice(6, U_AMP))
        deadline = time.time() + 5
        while emb.calls == 0 and time.time() < deadline:
            time.sleep(0.02)
        self.assertGreater(emb.calls, 0, "nothing judged in the background")
        started = time.perf_counter()
        t.close()
        t.spans()
        self.assertLess(time.perf_counter() - started, 0.05, "the stop waited on the model")

    def test_tail_cut_never_runs_over_unjudged_speech(self):
        # User, colleague, then the user's last words arrive after the last
        # judged window: they must survive.
        clip = np.concatenate([_voice(6, U_AMP), _voice(4, O_AMP), _voice(0.9, U_AMP)])
        f = vf.VoiceFilter(_FakeEmbedder(), _profile(self.tmp))
        t = vf.VoiceTrack(f, threaded=False, log=lambda m: None)
        t.feed(0, clip[:10 * SR])
        while t.step():
            pass
        t.feed(0, clip)
        spans = t.spans()
        self.assertTrue(spans, "the colleague was not cut at all")
        self.assertLessEqual(spans[-1][1], 10 * SR, "unjudged last words were cut")
        # Silence after the last judged window may go with the cut.
        quiet = np.concatenate([_voice(6, U_AMP), _voice(4, O_AMP),
                                np.zeros(int(0.9 * SR), np.float32)])
        t2 = vf.VoiceTrack(f, threaded=False, log=lambda m: None)
        t2.feed(0, quiet[:10 * SR])
        while t2.step():
            pass
        t2.feed(0, quiet)
        self.assertEqual(t2.spans()[-1][1], len(quiet))

    def test_window_being_judged_is_not_settled(self):
        f = vf.VoiceFilter(_FakeEmbedder(), _profile(self.tmp))
        t = vf.VoiceTrack(f, threaded=False, log=lambda m: None)
        t.feed(0, _voice(4, O_AMP))
        t._inflight = 0
        t._next = SR          # window 0 handed out, result not back yet
        self.assertFalse(t.head_settled())
        t._inflight = -1
        t._sims[0] = 0.9
        self.assertTrue(t.head_settled())

    def test_relative_spans(self):
        self.assertEqual(vf.relative_spans([(0, 100), (500, 900)], 50, 600),
                         [(0, 50), (450, 550)])
        self.assertEqual(vf.relative_spans([(0, 10)], 20, 30), [])


class _Model:
    """Stands in for the Parakeet model so transcribe() can run."""


def _fake_vad(audio, opts):     # one region per non-silent run
    nz = np.abs(audio) > 0.001
    out, i = [], 0
    while i < len(audio):
        if nz[i]:
            j = i
            while j < len(audio) and nz[j]:
                j += 1
            out.append({"start": i, "end": j})
            i = j
        else:
            i += 1
    return out


def _v1839_vad_clip(engine, audio) -> Optional[np.ndarray]:
    """ParakeetTranscriber._vad_clip exactly as shipped in v1.8.39, before
    voice isolation. Off must stay byte for byte this."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    chunks = get_speech_timestamps(audio, VadOptions(**engine._VAD_OPTS))
    if not chunks:
        return None
    edge = int(engine._VAD_EDGE_KEEP * SR)
    spans: list[dict] = []
    for i, c in enumerate(chunks):
        start = int(c["start"]) - (edge if i == 0 else 0)
        end = int(c["end"]) + (edge if i == len(chunks) - 1 else 0)
        start = max(0, start)
        end = min(len(audio), end)
        if spans and start <= spans[-1]["end"]:
            spans[-1]["end"] = max(spans[-1]["end"], end)
        else:
            spans.append({"start": start, "end": end})
    kept = sum(c["end"] - c["start"] for c in spans)
    if kept >= 0.9 * len(audio):
        return audio
    gap = np.zeros(int(engine._VAD_JOIN_GAP * SR), dtype=np.float32)
    parts: list = []
    for c in spans:
        if parts:
            parts.append(gap)
        parts.append(audio[c["start"]:c["end"]])
    return np.concatenate(parts)


class EngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = ParakeetTranscriber(vad_gate=True)
        self.engine._model = _Model()
        self.decoded: list = []

        def rec(audio, conf):
            self.decoded.append(np.array(audio, copy=True))
            return f"words {len(audio)}"
        self.engine._recognize_long = rec
        self.engine._post_process = lambda text, hot="": text
        self.engine.polish = lambda text: text
        import faster_whisper.vad as fwv
        self._orig = fwv.get_speech_timestamps
        fwv.get_speech_timestamps = _fake_vad

    def tearDown(self):
        import faster_whisper.vad as fwv
        fwv.get_speech_timestamps = self._orig

    def test_off_is_the_v1839_gate_byte_for_byte(self):
        rng = np.random.default_rng(3)
        clips = [_office_clip(), _voice(12, U_AMP),
                 np.concatenate([np.zeros(9 * SR, np.float32), _voice(2, U_AMP),
                                 np.zeros(9 * SR, np.float32), _voice(3, O_AMP)])]
        for _ in range(4):
            parts = [(_voice(rng.uniform(0.3, 4), U_AMP) if rng.random() < 0.6
                      else np.zeros(int(rng.uniform(0.3, 7) * SR), np.float32))
                     for _ in range(6)]
            clips.append(np.concatenate(parts))
        for clip in clips:
            for spans in (None, []):
                self.decoded.clear()
                self.engine.transcribe(clip, voice_spans=spans)
                want = _v1839_vad_clip(self.engine, clip)
                if want is None:
                    self.assertEqual(self.decoded, [])
                    continue
                self.assertEqual(len(self.decoded), 1)
                self.assertTrue(np.array_equal(self.decoded[0], want),
                                "off changed the audio the model hears")

    def test_spans_cut_the_colleague_in_one_decode_keeping_every_user_sample(self):
        clip = _office_clip()
        spans = vf.VoiceFilter(_FakeEmbedder(), _profile(tempfile.mkdtemp())).other_spans(clip)
        self.engine.transcribe(clip, voice_spans=spans)
        self.assertEqual(len(self.decoded), 1, "a cut must cost no second decode")
        cut = self.decoded[0]
        self.assertLess(len(cut), len(clip))
        self.assertEqual(int(np.sum(np.isclose(np.abs(cut), U_AMP))),
                         int(np.sum(np.isclose(np.abs(clip), U_AMP))),
                         "a sample of the user's speech was lost")
        self.assertGreater(self.engine.last_voice_cut_s, 0)

    def test_cut_that_leaves_nothing_keeps_everything(self):
        clip = _office_clip()
        self.assertIs(self.engine._vad_clip(clip, [(0, len(clip))]), clip)
        self.assertFalse(self.engine._voice_cut_applied)

    def test_edge_keep_never_reaches_into_a_cut(self):
        clip = _office_clip()
        cut = self.engine._vad_clip(clip, [(0, 3 * SR)])
        self.assertEqual(int(np.sum(np.isclose(np.abs(cut), O_AMP))),
                         int(np.sum(np.isclose(np.abs(clip[3 * SR:]), O_AMP))))

    def test_gate_off_ignores_spans(self):
        eng = ParakeetTranscriber(vad_gate=False)
        eng._model = _Model()
        got = []
        eng._recognize_long = lambda a, c: got.append(len(a)) or "x"
        eng._post_process = lambda text, hot="": text
        eng.polish = lambda text: text
        clip = _office_clip()
        eng.transcribe(clip, voice_spans=[(0, 3 * SR)])
        self.assertEqual(got, [len(clip)])


class _Recorder:
    def __init__(self, audio):
        self.a = audio
        self.active_sample_rate = SR
        self.now = 0
        self.dropped_samples = 0
        self.is_recording = True

    def get_audio_range(self, start):
        seg = self.a[start:self.now]
        return seg if len(seg) else None

    def drop_audio_before(self, abs_):
        self.dropped_samples = abs_

    def stop(self):
        self.is_recording = False
        return self.a[self.dropped_samples:]


class _Engine:
    def __init__(self):
        self.calls = []
        self.last_voice_cut_s = 0.0

    def transcribe(self, audio, rate, **kw):
        self.calls.append((len(audio), dict((k, v) for k, v in kw.items()
                                            if k != "conf_out")))
        if kw.get("voice_spans"):
            self.last_voice_cut_s = sum(e - s for s, e in kw["voice_spans"]) / SR
        return "" if kw.get("blocking") is False else "words"


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _run(self, clip, track=None, live=False, paragraphs=False, emb=None):
        rec, eng = _Recorder(clip), _Engine()
        s = StreamingSession(rec, eng, live_inject=live,
                             on_inject=(lambda t: True) if live else None,
                             auto_paragraphs=paragraphs, voice_track=track)
        step = int(StreamingSession.TICK_INTERVAL * SR)
        while rec.now < len(clip):
            rec.now = min(len(clip), rec.now + step)
            s._tick()
            if track is not None:
                while track.step():
                    pass
        before = emb.calls if emb else 0
        stop_calls = len(eng.calls)
        s.finalize()
        return eng.calls, stop_calls, s, (emb.calls - before) if emb else 0

    def _track(self, emb):
        return vf.VoiceTrack(vf.VoiceFilter(emb, _profile(self.tmp)),
                             threaded=False, log=lambda m: None)

    def _office_long(self):
        """Colleague 5 s, user 9 s with a pause, colleague 5 s: long enough to
        commit a chunk mid-dictation."""
        pause = np.zeros(int(0.5 * SR), np.float32)
        return np.concatenate([_voice(5, O_AMP), _voice(4, U_AMP), pause,
                               _voice(4.5, U_AMP), _voice(5, O_AMP)])

    def test_off_calls_the_engine_exactly_as_before(self):
        for paragraphs in (False, True):
            calls, _, _, _ = self._run(self._office_long(), paragraphs=paragraphs)
            for _n, kw in calls:
                self.assertNotIn("voice_spans", kw)

    def test_on_with_a_clean_dictation_calls_exactly_as_off(self):
        clip = _voice(14, U_AMP)
        off, _, _, _ = self._run(clip)
        on, _, _, _ = self._run(clip, track=self._track(_FakeEmbedder()))
        self.assertEqual(off, on)

    def test_on_cuts_both_colleagues_and_stop_never_calls_the_model(self):
        emb = _FakeEmbedder()
        calls, stop_at, s, stop_model_calls = self._run(
            self._office_long(), track=self._track(emb), emb=emb)
        self.assertEqual(stop_model_calls, 0, "finalize called the speaker model")
        kept = [kw for _n, kw in calls if kw.get("blocking") is not False
                and "context_words" in kw]
        cuts = [kw.get("voice_spans") for kw in kept]
        self.assertTrue(cuts[0], "the colleague before the user was not cut at commit")
        self.assertEqual(cuts[0][0][0], 0)
        self.assertTrue(cuts[-1], "the colleague after the user was not cut at the stop")
        self.assertGreater(s.voice_cut_s, 0)

    def test_colleague_committed_before_the_user_is_put_right_while_talking(self):
        # The colleague talks long enough for a chunk to commit before the
        # user's first window is judged: that chunk must lose the colleague's
        # words on the worker, never at the stop.
        pause = np.zeros(int(0.5 * SR), np.float32)
        clip = np.concatenate([_voice(5.5, O_AMP), pause, _voice(5.5, O_AMP), pause,
                               _voice(4, U_AMP), pause, _voice(4, U_AMP)])
        emb = _FakeEmbedder()
        track = self._track(emb)
        rec, eng = _Recorder(clip), _Engine()
        s = StreamingSession(rec, eng, voice_track=track)
        step = int(StreamingSession.TICK_INTERVAL * SR)
        committed_early = None
        while rec.now < len(clip):
            rec.now = min(len(clip), rec.now + step)
            s._tick()
            while track.step():
                pass
            if committed_early is None and s._committed_texts:
                committed_early = len(eng.calls)
                self.assertTrue(s._head_pending, "the early chunk was not kept")
        self.assertIsNotNone(committed_early, "nothing committed before the user spoke")
        self.assertEqual(s._head_pending, [], "the start was never settled while talking")
        before = len(eng.calls)
        s.finalize()
        self.assertEqual(len(eng.calls) - before, 1, "the stop paid for more than the tail")
        self.assertGreater(s.voice_cut_s, 0)
        self.assertEqual(s._committed_texts[0], "", "the colleague's words were kept")
        self.assertEqual(len(s._conf), 0)

    def test_microphone_not_at_16k_is_never_filtered(self):
        clip = self._office_long()
        rec, eng = _Recorder(clip), _Engine()
        rec.active_sample_rate = 48000
        track = self._track(_FakeEmbedder())
        s = StreamingSession(rec, eng, voice_track=track)
        step = int(StreamingSession.TICK_INTERVAL * SR)
        while rec.now < len(clip):
            rec.now = min(len(clip), rec.now + step)
            s._tick()
        s.finalize()
        for _n, kw in eng.calls:
            self.assertNotIn("voice_spans", kw)
        self.assertTrue(track._stop.is_set())

    def test_no_re_decode_once_the_key_is_up(self):
        pause = np.zeros(int(0.5 * SR), np.float32)
        # Colleague then user inside the first chunk: a partial cut, which
        # needs a decode. Settling it after the key-up must not decode.
        clip = np.concatenate([_voice(3, O_AMP), _voice(5, U_AMP), pause,
                               _voice(4, U_AMP)])
        track = self._track(_FakeEmbedder())
        rec, eng = _Recorder(clip), _Engine()
        s = StreamingSession(rec, eng, voice_track=track)
        s._head_pending = [{"at": 0, "audio": clip[:8 * SR], "first": 0, "n": 1,
                            "conf": (0, 0)}]
        s._committed_texts = ["words"]
        s._para_flags = [False]
        track.feed(0, clip)
        while track.step():
            pass
        s._stop_event.set()
        before = len(eng.calls)
        s._settle_head(SR)
        self.assertEqual(len(eng.calls), before, "a re-decode ran after the key-up")

    def test_clean_dictation_keeps_no_early_audio(self):
        clip = _voice(14, U_AMP)
        _calls, _, s, _ = self._run(clip, track=self._track(_FakeEmbedder()))
        self.assertEqual(s._head_pending, [])

    def test_live_typing_is_never_filtered(self):
        emb = _FakeEmbedder()
        track = self._track(emb)
        calls, _, _, _ = self._run(self._office_long(), track=track, live=True)
        for _n, kw in calls:
            self.assertNotIn("voice_spans", kw)
        self.assertTrue(track._stop.is_set(), "the unused track was left running")

    def test_paragraph_parts_get_their_own_spans(self):
        calls, _, _, _ = self._run(self._office_long(),
                                   track=self._track(_FakeEmbedder()), paragraphs=True)
        for n, kw in calls:
            for s, e in kw.get("voice_spans") or []:
                self.assertTrue(0 <= s < e <= n, "a span fell outside its part")


class ProfileTests(unittest.TestCase):
    def test_other_voice_never_joins_once_enrolled(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _profile(tmp)
            self.assertFalse(p.add(OTHER.copy(), save=False))
            self.assertTrue(p.add(USER.copy(), save=False))

    def test_saved_and_reloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _profile(tmp)
            p.mark_seen("a.wav")
            q = vf.VoiceProfile(os.path.join(tmp, "vp.json"))
            self.assertTrue(q.ready)
            self.assertIn("a.wav", q.seen)

    def test_voiceprint_from_another_model_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "vp.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"model": "something-else", "vectors": [[1,0,0]]}')
            self.assertFalse(vf.VoiceProfile(path).ready)

    def test_saved_voiceprint_holds_numbers_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _profile(tmp)
            p.mark_seen("a.wav")
            import json
            with open(os.path.join(tmp, "vp.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(set(data), {"model", "updated", "owner", "since",
                                         "seen", "vectors"})

    def test_enrol_audio_needs_enough_speech(self):
        self.assertIsNone(vf.enrol_audio(_voice(1, U_AMP)))
        long = vf.enrol_audio(_voice(80, U_AMP))
        self.assertEqual(len(long), int(vf.ENROLL_MAX_S * SR))


class IsolationLifecycleTests(unittest.TestCase):
    def _wav(self, folder, name, audio):
        import wave
        with wave.open(os.path.join(folder, name), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((audio * 32767).astype(np.int16).tobytes())

    def _vi(self, tmp, **kw):
        kw.setdefault("embedder", _FakeEmbedder())
        return vf.VoiceIsolation(tmp, os.path.join(tmp, "vp.json"), tmp, **kw)

    def test_learns_from_saved_dictations_then_goes_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(vf.MIN_ENROLL):
                self._wav(tmp, f"{i:04d}.wav", _voice(5, U_AMP))
            vi = self._vi(tmp)
            self.assertIsNone(vi.new_track(), "a track before anything was learned")
            self.assertEqual(vi.learn_once(), vf.MIN_ENROLL)
            self.assertTrue(vi.active)
            track = vi.new_track()
            self.assertIsInstance(track, vf.VoiceTrack)
            track.close()
            self.assertEqual(vi.learn_once(), 0, "a dictation was learned twice")

    def test_waits_while_dictating(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._wav(tmp, "a.wav", _voice(5, U_AMP))
            busy = threading.Event(); busy.set()
            emb = _FakeEmbedder()
            vi = self._vi(tmp, is_busy=busy.is_set, embedder=emb)
            t = threading.Thread(target=vi.learn_once, daemon=True)
            t.start()
            time.sleep(0.3)
            self.assertEqual(emb.calls, 0, "learned during a dictation")
            busy.clear()
            t.join(5)
            self.assertEqual(emb.calls, 1)

    def test_failures_are_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._wav(tmp, "a.wav", _voice(5, U_AMP))
            got = []
            vi = self._vi(tmp, embedder=_FakeEmbedder(fail=True), log=lambda m: None,
                          report=lambda ev, d: got.append(ev))
            vi.learn_once()
            self.assertEqual(got, ["voice_isolation_failed"])
            self.assertNotIn("a.wav", vi.profile.seen, "a failed file must be retried")

    def test_stop_with_forget_deletes_the_voiceprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(vf.MIN_ENROLL):
                self._wav(tmp, f"{i:04d}.wav", _voice(5, U_AMP))
            vi = self._vi(tmp)
            vi.learn_once()
            self.assertTrue(os.path.exists(os.path.join(tmp, "vp.json")))
            vi.stop(forget=True)
            self.assertFalse(vi.active)
            self.assertIsNone(vi.new_track())
            self.assertFalse(os.path.exists(os.path.join(tmp, "vp.json")))

    def test_switching_off_mid_learning_never_writes_the_voiceprint_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                self._wav(tmp, f"{i:04d}.wav", _voice(5, U_AMP))
            vi = self._vi(tmp)
            path = os.path.join(tmp, "vp.json")

            class SlowThenOff(_FakeEmbedder):
                def embed_many(inner, clips):
                    vi.stop(forget=True)        # switched off mid-embed
                    return super().embed_many(clips)
            vi.embedder = SlowThenOff()
            vi.filter.embedder = vi.embedder
            vi.learn_once()
            self.assertFalse(os.path.exists(path), "a deleted voiceprint came back")
            self.assertEqual(vi.profile.count, 0)
            vi.profile.add(USER.copy())
            vi.profile.mark_seen("x.wav")
            self.assertFalse(os.path.exists(path), "a closed voiceprint was saved")

    def test_delete_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = []
            vi = self._vi(tmp, log=lambda m: None, report=lambda ev, d: got.append(d))
            vi.profile.delete = lambda close=False: False
            vi.profile.last_error = "voice profile not deleted: locked"
            vi.stop(forget=True)
            self.assertEqual(got, [{"reason": "voice profile not deleted: locked"}])

    def test_account_switch_mid_learning_never_mixes_voices(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(vf.MIN_ENROLL + 2):
                self._wav(tmp, f"{i:04d}.wav", _voice(5, U_AMP))
            who = {"id": "user-a"}
            seen = {"n": 0}
            vi = self._vi(tmp, owner=lambda: who["id"], log=lambda m: None)

            class SwitchAfterTwo(_FakeEmbedder):
                def embed_many(inner, clips):
                    seen["n"] += 1
                    if seen["n"] == 2:
                        who["id"] = "user-b"     # B signs in while A is learned
                    return super().embed_many(clips)
            vi.embedder = SwitchAfterTwo()
            vi.learn_once()
            self.assertEqual(vi.profile.count, 0, "A's voice joined B's voiceprint")
            self.assertFalse(vi.profile.seen)

    def test_voiceprint_belongs_to_one_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(vf.MIN_ENROLL):
                self._wav(tmp, f"{i:04d}.wav", _voice(5, U_AMP))
            who = {"id": "user-a"}
            vi = self._vi(tmp, owner=lambda: who["id"], log=lambda m: None)
            self.assertEqual(vi.learn_once(), vf.MIN_ENROLL)
            self.assertIsNotNone(vi.new_track())
            with open(os.path.join(tmp, "vp.json"), encoding="utf-8") as fh:
                self.assertNotIn("user-a", fh.read(),
                                 "the account id is stored in plain text")
            # Signed out: no filtering with somebody's voiceprint.
            who["id"] = None
            self.assertIsNone(vi.new_track())
            # Another account: A's voiceprint is gone, and A's old dictations
            # are never learned as B's voice.
            who["id"] = "user-b"
            self.assertIsNone(vi.new_track())
            self.assertFalse(vi.profile.ready)
            self.assertEqual(vi.learn_once(), 0)
            self._wav(tmp, "9999.wav", _voice(5, U_AMP))
            os.utime(os.path.join(tmp, "9999.wav"), (time.time() + 5, time.time() + 5))
            self.assertEqual(vi.learn_once(), 1)


if __name__ == "__main__":
    unittest.main()
