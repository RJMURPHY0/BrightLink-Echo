"""Run every refine button over the eval dictations against the real model.

    python tools/refine_eval/run_eval.py --module ai_refiner.py --label new
    python tools/refine_eval/run_eval.py --module <old ai_refiner.py> --label baseline --model meta-llama/llama-4-scout

Each result goes through the same AIRefiner.refine() the app runs (prompt
construction and every output guard), only the HTTP call is swapped for one
that records latency, the model that answered and OpenRouter's real cost.
A blind judge model then rates whether the user would accept it first time.
The key comes from the environment or ~/.claude/bin/keyvault.py, never a file.
Paid models only (never ":free"): dictation is personal data.
"""

import argparse
import concurrent.futures as cf
import importlib.util
import json
import os
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ.pop("SSLKEYLOGFILE", None)  # Avast's pipe breaks Python HTTPS here

import checks  # noqa: E402

URL = "https://openrouter.ai/api/v1/chat/completions"
JUDGE_MODEL = "anthropic/claude-sonnet-5.5"

INTENT = {
    "punctuation": "Fix All: correct grammar, spelling, punctuation and dictation slips "
                   "(stutters, false starts, um/er, padding 'like'/'you know') and "
                   "nothing else. Every other word stays the speaker's.",
    "formal": "Formal / Professional: like asking ChatGPT 'make this a bit more "
              "professional'. Polish and restructure lightly, keep the speaker's own "
              "voice and exactly what they said. No corporate padding.",
    "casual": "Casual: friendly and conversational, still the speaker's own voice "
              "and exactly what they said. No added enthusiasm or padding.",
    "concise": "Short: shorter, simpler sentences, cut repetition and filler, keep "
               "every point and fact.",
    "email": "Email: lay the dictation out as a ready-to-send email in the speaker's "
             "own voice: greeting only if they addressed someone, short paragraphs, "
             "their sign-off kept. Nothing added.",
    "prompt_optimiser": "Prompt Optimiser: turn the dictation into a clear prompt to "
                        "paste into an AI, keeping every requirement exactly.",
}

JUDGE_SYSTEM = (
    "You review AI edits of dictated text for a dictation app. You are strict: "
    "the user wants to accept the result first time and send it as their own. "
    "Answer with JSON only."
)


def _key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY", "")
    if not k:
        sys.path.insert(0, os.path.expanduser("~/.claude/bin"))
        import keyvault  # type: ignore
        k = keyvault.get("OPENROUTER_API_KEY") or ""
    if not k:
        sys.exit("No OPENROUTER_API_KEY")
    return k


def chat(key, model, system, user, max_tokens, temperature=0, fallbacks=None,
         reasoning=None):
    body = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [{"role": "user", "content": user}],
            "usage": {"include": True},
            "provider": {"data_collection": "deny"}}
    if fallbacks:
        body["models"] = fallbacks
    if reasoning is not None:
        body["reasoning"] = reasoning
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t = time.perf_counter()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:  # noqa: BLE001 - retried, then raised
            if attempt == 2:
                raise
            print(f"  retry after {type(e).__name__}: {e}")
            time.sleep(2)
    dt = time.perf_counter() - t
    u = data.get("usage") or {}
    return ((data["choices"][0]["message"].get("content") or "").strip(),
            {"latency": dt, "model": data.get("model"), "cost": u.get("cost") or 0,
             "tok_in": u.get("prompt_tokens"), "tok_out": u.get("completion_tokens")})


def load_module(path):
    spec = importlib.util.spec_from_file_location("ai_refiner_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_refiner(mod, key, model, fallbacks, reasoning):
    local = threading.local()

    class Timed(mod.AIRefiner):
        def _refine_via_openrouter(self, text, prompt, mode, system=""):
            out, meta = chat(key, model, system or self._system_prompt_for(mode),
                             mod._data_message(prompt, text),
                             self._max_tokens_for(text), 0, fallbacks, reasoning)
            local.meta = meta
            local.raw = out
            return out

    r = Timed(openrouter_api_key=key)
    return r, local


def judge(key, mode, text, out):
    user = (
        f"Button the user pressed: {INTENT[mode]}\n\n"
        f"ORIGINAL DICTATION:\n<<<\n{text}\n>>>\n\nRESULT:\n<<<\n{out}\n>>>\n\n"
        "Rate 1 to 5 each: meaning (every fact, name, number, request kept, nothing "
        "added or softened), voice (still sounds like this speaker, no corporate "
        "padding, no AI tells), quality (does what the button promises, reads well, "
        "British English, layout right). If the original already met what the "
        "button promises, a small change or none is correct and scores well; "
        "only mark it down for doing too little when there was clearly something "
        "the button should have fixed. Then accept: would the user send this "
        "without editing it? Reply exactly: "
        '{"meaning":n,"voice":n,"quality":n,"accept":true|false,"issue":"one short phrase or empty"}'
        " Output only that JSON object on one line, no reasoning before or after it."
    )
    raw, meta = chat(key, JUDGE_MODEL, JUDGE_SYSTEM, user, 700, 0)
    try:
        s = raw[raw.index("{"): raw.rindex("}") + 1]
        return json.loads(s), meta
    except ValueError:
        return {"meaning": 0, "voice": 0, "quality": 0, "accept": False,
                "issue": "judge unreadable: " + raw[:80]}, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default=os.path.join(ROOT, "ai_refiner.py"))
    ap.add_argument("--label", required=True)
    ap.add_argument("--model", default=None, help="defaults to the module's DEFAULT_OPENROUTER_MODEL")
    ap.add_argument("--no-fallbacks", action="store_true")
    ap.add_argument("--reasoning-off", action="store_true")
    ap.add_argument("--modes", default="")
    ap.add_argument("--cases", default="")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="")
    ap.add_argument("--rejudge", default="", help="re-run only the judge over a saved result file")
    a = ap.parse_args()
    if a.model and a.model.endswith(":free"):
        sys.exit("Never a :free model for dictation")

    key = _key()
    if a.rejudge:
        d = json.load(open(a.rejudge, encoding="utf-8"))
        cases = {c["id"]: c for c in json.load(open(os.path.join(HERE, "cases.json"), encoding="utf-8"))}

        def rj(r):
            r["judge"], jm = judge(key, r["mode"], cases[r["id"]]["text"], r["out"])
            r["judge_cost"] = jm["cost"]
            return r
        with cf.ThreadPoolExecutor(a.workers) as ex:
            d["results"] = list(ex.map(rj, d["results"]))
        d["label"] = a.label
        out_path = a.out or os.path.join(HERE, "results", f"{a.label}.json")
        json.dump(d, open(out_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("wrote", out_path)
        return
    mod = load_module(a.module)
    model = a.model or mod.AIRefiner.DEFAULT_OPENROUTER_MODEL
    fallbacks = None if a.no_fallbacks else mod.AIRefiner.OPENROUTER_FALLBACK_MODELS
    reasoning = {"enabled": False} if a.reasoning_off else None
    refiner, local = make_refiner(mod, key, model, fallbacks, reasoning)

    cases = json.load(open(os.path.join(HERE, "cases.json"), encoding="utf-8"))
    if a.cases:
        want = set(a.cases.split(","))
        cases = [c for c in cases if c["id"] in want]
    only = set(a.modes.split(",")) if a.modes else None
    jobs = [(c, m) for c in cases for m in c.get("modes", checks.MODES)
            if not only or m in only]

    def run(job):
        case, mode = job
        out = refiner.refine(case["text"], mode, sender_name="Ryan Murphy")
        meta = getattr(local, "meta", {})
        res = {"id": case["id"], "mode": mode, "out": out,
               "raw": getattr(local, "raw", ""), **meta,
               "checks": checks.score(case, mode, out)}
        if not a.no_judge:
            res["judge"], jm = judge(key, mode, case["text"], out)
            res["judge_cost"] = jm["cost"]
        return res

    results = []
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(run, jobs):
            results.append(r)
            flag = "PASS" if r["checks"]["pass"] else "fail"
            acc = r.get("judge", {}).get("accept")
            print(f"{flag} {('acc' if acc else 'rej') if acc is not None else ''} "
                  f"{r['mode']:16} {r['id']:26} {r.get('latency', 0):.2f}s {r.get('model')}")

    out_path = a.out or os.path.join(HERE, "results", f"{a.label}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump({"label": a.label, "model": model, "results": results},
              open(out_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
