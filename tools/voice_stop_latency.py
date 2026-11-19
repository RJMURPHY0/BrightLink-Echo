"""
Stop latency with voice isolation on vs off, in real time.

    venv\\Scripts\\python.exe tools\\voice_stop_latency.py [--clips 12] [--reps 2]
        [--model <titanet onnx>] [--libri <dir>] [--out report.json]

Each dictation is played into the real StreamingSession at wall-clock speed
(its worker thread ticking, the VoiceTrack judging on its own thread, exactly
as in the app), then the time finalize() takes is measured: that is the wait
between letting go of the key and the text. Off and on are interleaved per
clip and the order flips each rep, so a busy laptop hurts both equally.

The user's own saved dictations are the clips; the voiceprint is built from
other dictations (leave-out). With --libri, each clip is also run with a
LibriSpeech speaker before and after it, so the cut path is timed too.
Off is byte for byte the v1.8.39 path (pinned in tests/test_voice_filter.py).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import crosstalk_bench as cb                        # noqa: E402
import data_paths                                   # noqa: E402
import voice_filter as vfm                          # noqa: E402
from asr_engine import ParakeetTranscriber          # noqa: E402
from speaker_embed import SpeakerEmbedder           # noqa: E402
from stream_session import StreamingSession         # noqa: E402

SR = 16000


class RealtimeRecorder:
    """Delivers a clip at wall-clock speed in 20 ms blocks."""

    def __init__(self, audio):
        self.a = audio
        self.active_sample_rate = SR
        self.now = 0
        self.dropped_samples = 0
        self.is_recording = True
        self._t0 = time.perf_counter()
        self._lock = threading.Lock()

    def advance(self) -> bool:
        with self._lock:
            self.now = min(len(self.a), int((time.perf_counter() - self._t0) * SR) // 320 * 320)
            return self.now < len(self.a)

    def get_audio_range(self, start):
        self.advance()
        seg = self.a[start:self.now]
        return seg.copy() if len(seg) else None

    def drop_audio_before(self, abs_):
        self.dropped_samples = abs_

    def stop(self):
        self.is_recording = False
        return self.a[self.dropped_samples:self.now].copy()


def one(eng, vi_filter, audio, on: bool) -> tuple[float, str, int]:
    track = vfm.VoiceTrack(vi_filter, log=lambda m: None) if on else None
    rec = RealtimeRecorder(audio)
    sess = StreamingSession(rec, eng, auto_paragraphs=True, trim_silence=True,
                            voice_track=track)
    sess.start()
    while rec.advance():
        time.sleep(0.005)
    t = time.perf_counter()
    text, _tail, _r = sess.finalize()
    return (time.perf_counter() - t) * 1000, text, (track.windows if track else 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", type=int, default=12)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--model", default="")
    ap.add_argument("--libri", default="")
    ap.add_argument("--audio", default=os.path.join(data_paths.roaming_dir(), "audio"))
    ap.add_argument("--out", default="voice_stop_latency.json")
    args = ap.parse_args()

    clips = []
    for p in sorted(glob.glob(os.path.join(args.audio, "*.wav"))):
        try:
            a = cb.read_wav(p)
        except Exception:
            continue
        if 4 * SR <= len(a) <= 20 * SR and cb.speech_rms(a) > 0.003:
            clips.append(a)
    test, enrol = clips[-args.clips:], clips[:-args.clips][-vfm.MAX_ENROLL:]
    emb = SpeakerEmbedder(os.path.join(data_paths.local_dir(), "models"), args.model,
                          threads=1)
    if not emb.download():
        print("voice model:", emb.last_error)
        return 2
    prof = vfm.VoiceProfile(os.path.join(os.path.dirname(os.path.abspath(args.out)),
                                         "latency_voice_profile.json"))
    prof.delete()
    for a in enrol:
        s = vfm.enrol_audio(a)
        if s is not None:
            prof.add(emb.embed(s), save=False)
    filt = vfm.VoiceFilter(emb, prof)

    cases = [("clean", a) for a in test]
    if args.libri:
        flacs = sorted(glob.glob(os.path.join(args.libri, "**", "*.flac"), recursive=True))
        others = [cb.read_flac(f) for f in flacs[::max(1, len(flacs) // 40)][:40]]
        others = [o for o in others if 2 * SR <= len(o) <= 8 * SR]
        gap = np.zeros(int(0.6 * SR), np.float32)
        for k, a in enumerate(test):
            lvl = cb.speech_rms(a)
            o1, o2 = others[k % len(others)], others[(k + 7) % len(others)]
            cases.append(("gaps_0dB", np.clip(np.concatenate(
                [cb.scale_to(o1, lvl), gap, a, gap, cb.scale_to(o2, lvl)]), -1, 1)
                .astype(np.float32)))

    eng = ParakeetTranscriber(vad_gate=True)
    if not eng.load_model():
        print("Parakeet model not available")
        return 2
    eng.transcribe(test[0])            # warm
    emb.embed(test[0][: 3 * SR])

    rows = []
    for rep in range(args.reps):
        for i, (case, a) in enumerate(cases):
            order = (False, True) if (rep + i) % 2 == 0 else (True, False)
            res = {}
            for on in order:
                res[on] = one(eng, filt, a, on)
            rows.append({"case": case, "secs": round(len(a) / SR, 1),
                         "off_ms": round(res[False][0], 1), "on_ms": round(res[True][0], 1),
                         "windows": res[True][2],
                         "same_text": res[False][1] == res[True][1]})
            print(f"rep {rep + 1} {i + 1}/{len(cases)} {case} {len(a) / SR:4.1f}s "
                  f"off {res[False][0]:6.0f} ms  on {res[True][0]:6.0f} ms")

    summary = {}
    for case in sorted({r["case"] for r in rows}):
        rs = [r for r in rows if r["case"] == case]
        off = np.array([r["off_ms"] for r in rs])
        on = np.array([r["on_ms"] for r in rs])
        d = on - off
        summary[case] = {
            "runs": len(rs),
            "off_median_ms": float(np.median(off)), "off_p90_ms": float(np.percentile(off, 90)),
            "on_median_ms": float(np.median(on)), "on_p90_ms": float(np.percentile(on, 90)),
            "extra_median_ms": float(np.median(d)), "extra_p90_ms": float(np.percentile(d, 90)),
            "same_text": int(sum(r["same_text"] for r in rs))}
        s = summary[case]
        print(f"{case:9s} off median {s['off_median_ms']:5.0f} p90 {s['off_p90_ms']:5.0f} | "
              f"on median {s['on_median_ms']:5.0f} p90 {s['on_p90_ms']:5.0f} | "
              f"extra median {s['extra_median_ms']:4.0f} p90 {s['extra_p90_ms']:4.0f} ms | "
              f"same text {s['same_text']}/{s['runs']}")
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "rows": rows}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
