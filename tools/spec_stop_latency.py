"""
Stop latency with the live AI check (speculative_fix.py) on vs off, in real
time.

    venv\\Scripts\\python.exe tools\\spec_stop_latency.py [--clips 8] [--reps 1]

Each saved dictation is played into the real StreamingSession at wall-clock
speed. "On" adds the extra hypothesis decodes the live check asks for
(StreamingSession.on_hypothesis) and a SpeculativeFixer whose AI is a stand-in
that waits a second and changes nothing, so no text leaves the PC and the
cost measured is the engine's: finalize() waiting behind a hypothesis decode.
Off and on are interleaved per clip and the order flips, so a busy laptop
hurts both equally. Clips 6 to 40 seconds.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import crosstalk_bench as cb                        # noqa: E402
import data_paths                                   # noqa: E402
import speculative_fix                              # noqa: E402
from asr_engine import ParakeetTranscriber          # noqa: E402
from stream_session import StreamingSession         # noqa: E402
from voice_stop_latency import RealtimeRecorder, SR  # noqa: E402


class _StandInAI:
    last_relay_error = ""
    is_available = True

    def context_fix(self, text, names=""):
        time.sleep(1.0)
        return text

    def plan_paragraphs(self, sents):
        time.sleep(1.0)
        return []


def one(eng, audio, on: bool) -> tuple[float, str, int]:
    rec = RealtimeRecorder(audio)
    fixer = speculative_fix.SpeculativeFixer(_StandInAI(), lambda t: "") if on else None
    sess = StreamingSession(rec, eng, auto_paragraphs=True, trim_silence=True,
                            on_hypothesis=fixer.feed if fixer else None)
    sess.start()
    while rec.advance():
        time.sleep(0.005)
    if fixer:
        fixer.stop()
    t = time.perf_counter()
    text, _tail, _r = sess.finalize()
    calls = fixer.stats["fix_calls"] + fixer.stats["plan_calls"] if fixer else 0
    return (time.perf_counter() - t) * 1000, text, calls


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", type=int, default=8)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--audio", default=os.path.join(data_paths.roaming_dir(), "audio"))
    ap.add_argument("--out", default="spec_stop_latency.json")
    args = ap.parse_args()

    clips = []
    for p in sorted(glob.glob(os.path.join(args.audio, "*.wav"))):
        try:
            a = cb.read_wav(p)
        except Exception:
            continue
        if 6 * SR <= len(a) <= 40 * SR and cb.speech_rms(a) > 0.003:
            clips.append(a)
    test = clips[-args.clips:]
    if not test:
        print("no clips")
        return 2
    eng = ParakeetTranscriber(vad_gate=True)
    if not eng.load_model():
        print("Parakeet model not available")
        return 2
    eng.transcribe(test[0])            # warm

    rows = []
    for rep in range(args.reps):
        for i, a in enumerate(test):
            order = (False, True) if (rep + i) % 2 == 0 else (True, False)
            res = {on: one(eng, a, on) for on in order}
            rows.append({"secs": round(len(a) / SR, 1),
                         "off_ms": round(res[False][0], 1), "on_ms": round(res[True][0], 1),
                         "calls": res[True][2], "same_text": res[False][1] == res[True][1]})
            print(f"rep {rep + 1} {i + 1}/{len(test)} {len(a) / SR:4.1f}s "
                  f"off {res[False][0]:6.0f} ms  on {res[True][0]:6.0f} ms  "
                  f"AI calls {res[True][2]}")
    off = np.array([r["off_ms"] for r in rows])
    on = np.array([r["on_ms"] for r in rows])
    s = {"runs": len(rows),
         "off_median_ms": float(np.median(off)), "off_p90_ms": float(np.percentile(off, 90)),
         "on_median_ms": float(np.median(on)), "on_p90_ms": float(np.percentile(on, 90)),
         "extra_median_ms": float(np.median(on - off)),
         "extra_p90_ms": float(np.percentile(on - off, 90)),
         "same_text": int(sum(r["same_text"] for r in rows))}
    print(f"off median {s['off_median_ms']:.0f} p90 {s['off_p90_ms']:.0f} | on median "
          f"{s['on_median_ms']:.0f} p90 {s['on_p90_ms']:.0f} | extra median "
          f"{s['extra_median_ms']:.0f} p90 {s['extra_p90_ms']:.0f} ms | same text "
          f"{s['same_text']}/{s['runs']}")
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"summary": s, "rows": rows}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
