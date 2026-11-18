"""Before/after table from run_eval.py result files.

    python tools/refine_eval/summarise.py results/baseline.json results/new.json
"""

import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checks  # noqa: E402

_CASES = {c["id"]: c for c in json.load(open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.json"), encoding="utf-8"))}


def _load(path):
    """Results with the checks re-run, so a checker fix needs no new model calls."""
    d = json.load(open(path, encoding="utf-8"))
    for r in d["results"]:
        r["checks"] = checks.score(_CASES[r["id"]], r["mode"], r["out"])
    return d

COLS = ("pass", "meaning_ok", "tone_ok", "uk_ok", "layout_ok", "length_ok", "voice_ok")


def table(path):
    d = _load(path)
    rows = {}
    for r in d["results"]:
        rows.setdefault(r["mode"], []).append(r)
    rows["ALL"] = d["results"]
    print(f"\n## {d['label']}  (model {d['model']})")
    print("| mode | n | pass | meaning | tone | UK | layout | length | voice>=min | voice avg "
          "| judge accept | judge M/V/Q | latency avg | p90 | cost/call $ |")
    print("|" + "---|" * 15)
    for mode, rs in rows.items():
        n = len(rs)
        pct = lambda k: f"{100 * sum(1 for r in rs if r['checks'][k]) / n:.0f}%"  # noqa: E731
        js = [r["judge"] for r in rs if "judge" in r]
        acc = f"{100 * sum(1 for j in js if j.get('accept')) / len(js):.0f}%" if js else "-"
        mvq = ("/".join(f"{statistics.mean(j.get(k, 0) for j in js):.2f}"
                        for k in ("meaning", "voice", "quality")) if js else "-")
        lat = sorted(r.get("latency", 0) for r in rs)
        p90 = lat[min(len(lat) - 1, int(0.9 * len(lat)))]
        cost = statistics.mean(r.get("cost", 0) for r in rs)
        voice = statistics.mean(r["checks"]["voice"] for r in rs)
        print(f"| {mode} | {n} | " + " | ".join(pct(k) for k in COLS)
              + f" | {voice:.2f} | {acc} | {mvq} | {statistics.mean(lat):.2f}s | {p90:.2f}s | {cost:.6f} |")
    models = {}
    for r in d["results"]:
        models[r.get("model")] = models.get(r.get("model"), 0) + 1
    print("answered by:", models)
    total = sum(r.get("cost", 0) for r in d["results"])
    jtotal = sum(r.get("judge_cost", 0) for r in d["results"])
    print(f"refine spend ${total:.4f}, judge spend ${jtotal:.4f}")


def failures(path, limit=200):
    d = _load(path)
    for r in d["results"]:
        c, j = r["checks"], r.get("judge", {})
        bad = {k: c[k] for k in ("missing", "added_numbers", "added_names", "fluff",
                                 "slop", "us_spelling", "dashes", "exclamations",
                                 "markdown", "layout") if c[k]}
        if not c["length_ok"]:
            bad["length"] = c["length_ratio"]
        if not c["voice_ok"]:
            bad["voice"] = c["voice"]
        if bad or (j and not j.get("accept")):
            print(f"- {r['mode']} {r['id']}: {bad} judge={j.get('issue', '')!r}")
            limit -= 1
            if not limit:
                return


if __name__ == "__main__":
    args = sys.argv[1:]
    show = "--failures" in args
    for p in [x for x in args if not x.startswith("--")]:
        table(p)
        if show:
            failures(p)
