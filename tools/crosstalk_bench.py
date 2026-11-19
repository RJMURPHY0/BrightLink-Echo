"""
Crosstalk bench: does voice isolation help with colleagues talking, and does
it ever hurt a clean dictation?

    venv\\Scripts\\python.exe tools\\crosstalk_bench.py --libri <LibriSpeech dir> [--clips 24]

Ryan's own stored dictations (the data folder's audio\\*.wav) are the user's
voice; LibriSpeech read speech (any folder of .flac, e.g. dev-clean-2 from
openslr.org/31) stands in for the colleagues. Each test clip is scored three
ways against Parakeet's OWN output on the clean clip with voice isolation off,
so the numbers measure what the interference and the filter change, not
Parakeet's absolute accuracy. Every clip runs through the real
StreamingSession exactly as the app runs it (commits mid-dictation, tail
decode at the stop); with the filter on, a VoiceTrack judges each window
after every tick, as its background thread does while the user talks:

  clean     the clip as recorded            -> filter must change nothing
  gaps      a colleague speaks before and after the user, at 0 and -6 dB
  overlap   a colleague talks over the whole clip at 10 and 5 dB below

The voiceprint is built from OTHER dictations than the ones tested
(leave-out), exactly as the app builds it. Re-run this before changing any
threshold in voice_filter.py. Writes a JSON report next to --out.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import wave

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import data_paths                                   # noqa: E402
import voice_filter as vfm                          # noqa: E402
from asr_engine import ParakeetTranscriber          # noqa: E402
from speaker_embed import SpeakerEmbedder           # noqa: E402
from stream_session import StreamingSession         # noqa: E402

SR = 16000


def read_wav(path: str) -> np.ndarray:
    with wave.open(path) as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768
    if ch > 1:
        a = a.reshape(-1, ch).mean(1)
    if sr != SR:
        raise ValueError(f"{path}: {sr} Hz")
    return a


def read_flac(path: str) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1",
         "-ar", str(SR), "-"], capture_output=True, check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def speech_rms(a: np.ndarray) -> float:
    blocks = a[: len(a) // 320 * 320].reshape(-1, 320)
    lv = np.sqrt(np.mean(blocks ** 2, axis=1))
    return float(np.percentile(lv, 90)) if len(lv) else 0.0


def words(t: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", t.lower())


def wer(ref: str, hyp: str) -> tuple[int, int, int]:
    """(errors, ref words, insertions)."""
    r, h = words(ref), words(hyp)
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=np.int32)
    d[:, 0] = np.arange(len(r) + 1)
    d[0, :] = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1,
                          d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    i, j, ins = len(r), len(h), 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i, j] == d[i - 1, j - 1] + (r[i - 1] != h[j - 1]):
            i, j = i - 1, j - 1
        elif j > 0 and d[i, j] == d[i, j - 1] + 1:
            ins += 1
            j -= 1
        else:
            i -= 1
    return int(d[len(r), len(h)]), len(r), ins


def scale_to(a: np.ndarray, target_rms: float) -> np.ndarray:
    return a * (target_rms / max(speech_rms(a), 1e-6))


class _Recorder:
    """Plays a clip into a StreamingSession tick by tick (no waiting)."""

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


def session_text(eng, vf, audio, on: bool):
    """(text, stop ms, speaker-model ms) for one dictation through the real
    streaming session, app defaults (auto paragraphs, trim silence)."""
    rec = _Recorder(audio)
    track = vfm.VoiceTrack(vf, threaded=False, log=lambda m: None) if on else None
    sess = StreamingSession(rec, eng, auto_paragraphs=True, trim_silence=True,
                            voice_track=track)
    step = int(StreamingSession.TICK_INTERVAL * SR)
    while rec.now < len(audio):
        rec.now = min(len(audio), rec.now + step)
        sess._tick()
        while track is not None and track.step():
            pass
    t = time.perf_counter()
    text, _tail, _rate = sess.finalize()
    return text, (time.perf_counter() - t) * 1000, (track.embed_ms if track else 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--libri", required=True)
    ap.add_argument("--clips", type=int, default=24)
    ap.add_argument("--audio", default=os.path.join(data_paths.roaming_dir(), "audio"))
    ap.add_argument("--model", default="")
    ap.add_argument("--out", default="crosstalk_report.json")
    ap.add_argument("--threshold", type=float, default=vfm.OTHER_BELOW)
    args = ap.parse_args()
    vfm.OTHER_BELOW = args.threshold

    rng = np.random.default_rng(7)
    paths = sorted(glob.glob(os.path.join(args.audio, "*.wav")))
    clips = []
    for p in paths:
        try:
            a = read_wav(p)
        except Exception:
            continue
        if 3.0 <= len(a) / SR <= 45.0 and speech_rms(a) > 0.003:
            clips.append((os.path.basename(p), a))
    if len(clips) < args.clips + vfm.MIN_ENROLL:
        print(f"only {len(clips)} usable dictations")
        return 2
    test_idx = set(np.linspace(0, len(clips) - 1, args.clips).astype(int).tolist())
    test = [c for i, c in enumerate(clips) if i in test_idx]
    enrol = [c for i, c in enumerate(clips) if i not in test_idx][-vfm.MAX_ENROLL:]

    model_dir = os.path.join(data_paths.local_dir(), "models")
    emb = SpeakerEmbedder(model_dir, args.model)
    if not emb.download():
        print("voice model:", emb.last_error)
        return 2
    prof = vfm.VoiceProfile(os.path.join(os.path.dirname(os.path.abspath(args.out)),
                                         "bench_voice_profile.json"))
    prof.delete()
    for _, a in enrol:
        speech = vfm.enrol_audio(a)
        if speech is not None:
            prof.add(emb.embed(speech), save=False)
    print(f"voiceprint from {prof.count} dictations; testing {len(test)}")
    vf = vfm.VoiceFilter(emb, prof)

    flacs = sorted(glob.glob(os.path.join(args.libri, "**", "*.flac"), recursive=True))
    by_spk: dict[str, list[str]] = {}
    for f in flacs:
        by_spk.setdefault(os.path.basename(f).split("-")[0], []).append(f)
    others = []
    for spk in sorted(by_spk):
        f = by_spk[spk][int(rng.integers(len(by_spk[spk])))]
        a = read_flac(f)
        if 2.0 <= len(a) / SR <= 16.0:
            others.append((spk, a))
    print(f"{len(others)} other speakers")

    # Calibration: window similarities for the user's own clean clips and for
    # other speakers, against the leave-out voiceprint.
    c = prof.centroid()

    def win_sims(a):
        win, hop = int(vfm.WIN_S * SR), int(vfm.HOP_S * SR)
        lv = vfm._block_levels(a)
        loud = lv >= max(vfm.SILENCE_RMS, 0.25 * float(np.percentile(lv, 90)))
        ws = [(s, s + win) for s in range(0, len(a) - win + 1, hop)
              if np.mean(loud[s // 320:(s + win) // 320]) >= vfm.VOICED_SHARE]
        if not ws:
            return []
        return (emb.embed_many([a[s:e] for s, e in ws]) @ c).tolist()

    own = [s for _, a in test for s in win_sims(a)]
    oth = [s for _, a in others for s in win_sims(scale_to(a, 0.03))]
    pct = lambda v, q: float(np.percentile(v, q)) if v else float("nan")
    calib = {"own_min": pct(own, 0), "own_p0_5": pct(own, 0.5), "own_p5": pct(own, 5),
             "own_median": pct(own, 50), "other_median": pct(oth, 50),
             "other_p95": pct(oth, 95), "other_max": pct(oth, 100),
             "own_below_other_threshold": float(np.mean(np.array(own) < vfm.OTHER_BELOW)),
             "own_above_user_threshold": float(np.mean(np.array(own) >= vfm.USER_ABOVE)),
             "other_below_other_threshold": float(np.mean(np.array(oth) < vfm.OTHER_BELOW)),
             "other_above_user_threshold": float(np.mean(np.array(oth) >= vfm.USER_ABOVE))}
    print("calibration", json.dumps({k: round(v, 3) for k, v in calib.items()}))

    eng = ParakeetTranscriber(vad_gate=True)
    if not eng.load_model():
        print("Parakeet model not available")
        return 2

    def run(a, on):
        return session_text(eng, vf, a, on)

    rows = []
    totals: dict = {}
    for k, (name, a) in enumerate(test):
        ref, _, _ = run(a, False)
        lvl = speech_rms(a)
        o1 = others[k % len(others)][1]
        o2 = others[(k + 7) % len(others)][1]
        gap = np.zeros(int(0.6 * SR), dtype=np.float32)
        cases = {"clean": a}
        for db in (0, -6):
            g = 10 ** (db / 20)
            cases[f"gaps_{db}dB"] = np.concatenate(
                [scale_to(o1, lvl * g), gap, a, gap, scale_to(o2, lvl * g)])
        # A colleague across the room: 12 dB down with room echo (exponential
        # decay, about 0.4 s), the way a far voice reaches a desk mic.
        ir_n = int(0.4 * SR)
        ir = rng.normal(0, 1, ir_n) * np.exp(-6.9 * np.arange(ir_n) / ir_n)
        ir[0] = 1.0
        far1 = np.convolve(o1, ir)[: len(o1)].astype(np.float32)
        far2 = np.convolve(o2, ir)[: len(o2)].astype(np.float32)
        cases["gaps_-12dB_room"] = np.concatenate(
            [scale_to(far1, lvl * 10 ** (-12 / 20)), gap, a, gap,
             scale_to(far2, lvl * 10 ** (-12 / 20))])
        for db in (10, 5):
            bg = np.tile(o1, int(np.ceil(len(a) / len(o1))) + 1)[: len(a)]
            cases[f"overlap_{db}dB"] = a + scale_to(bg, lvl * 10 ** (-db / 20))
        for case, audio in cases.items():
            for on in (False, True):
                hyp, ms, vms = run(np.clip(audio, -1, 1).astype(np.float32), on)
                err, n, ins = wer(ref, hyp)
                key = (case, "on" if on else "off")
                t = totals.setdefault(key, [0, 0, 0, 0.0, 0.0, 0.0])
                t[0] += err; t[1] += n; t[2] += ins; t[3] += ms; t[4] += vms
                t[5] += len(audio) / SR
                rows.append({"clip": name, "case": case, "on": on, "errors": err,
                             "words": n, "inserted": ins, "ms": round(ms),
                             "filter_ms": vms, "hyp": hyp, "ref": ref})
        print(f"{k + 1}/{len(test)} {name}")

    summary = {}
    for (case, mode), (err, n, ins, ms, vms, secs) in sorted(totals.items()):
        summary[f"{case}/{mode}"] = {
            "wer_pct": round(100 * err / max(n, 1), 2), "inserted_words": ins,
            "stop_ms_per_audio_s": round(ms / max(secs, 1e-9), 1),
            "speaker_model_ms_per_audio_s": round(vms / max(secs, 1e-9), 1)}
        print(f"{case:14s} {mode:3s} WER {summary[f'{case}/{mode}']['wer_pct']:6.2f}%"
              f"  inserted {ins:4d}  stop {ms / secs:6.1f} ms/s"
              f"  speaker model {vms / secs:6.1f} ms/s (while talking)")
    # Stop time (finalize only) with the filter on minus off, same clip. The
    # realtime check with the app's threads is tools/voice_stop_latency.py.
    extra: dict = {}
    by = {(x["clip"], x["case"], x["on"]): x["ms"] for x in rows}
    for (clip, case, on), ms in by.items():
        if on:
            extra.setdefault(case, []).append(ms - by[(clip, case, False)])
    for case, v in sorted(extra.items()):
        summary[f"{case}/extra_ms"] = {"median": float(np.median(v)),
                                       "p90": float(np.percentile(v, 90))}
        print(f"{case:14s} extra stop ms with filter: median {np.median(v):6.0f}"
              f"  p90 {np.percentile(v, 90):6.0f}")
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"threshold": vfm.OTHER_BELOW, "calibration": calib,
                   "summary": summary, "rows": rows}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
