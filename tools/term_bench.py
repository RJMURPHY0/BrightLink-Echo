"""Term accuracy benchmark: does Echo write the names that matter correctly?

tools/wer_bench.py replays real dictations against Echo's own past output, so
it measures consistency, not truth, and says nothing about names. This one
has ground truth: sentences built around the user's real terms (the CRM names
and companies in estate-vocab.json, plus their own vocabulary), spoken by the
offline Windows voices, then run through the same offline pipeline the app
uses after a dictation. It reports, per pipeline:

  term_exact   the term appears exactly as written (casing included)
  term_ci      the term appears, ignoring case
  wer          word error rate over the whole sentence
  false_fix    control sentences (no names) that gained a CRM term

Pipelines compared:
  raw          the engine alone, no hotwords, no corrections
  app          what Echo does today: casing hotwords, destutter, homophones,
               spoken commands, lists, exact and fuzzy vocabulary (user first,
               then managed CRM entries, strict tier)

Synthetic voices are not the user's voice: this catches name and term
handling, not accent problems. Everything stays on this PC under
%LOCALAPPDATA%\\BrightLink Echo\\bench (the names are business data).

Usage (venv python, from the project root, outside 08:00-16:30 weekdays):
  venv\\Scripts\\python.exe tools\\term_bench.py            # build, speak, score
  venv\\Scripts\\python.exe tools\\term_bench.py --limit 40 # quick run
"""

import argparse
import datetime
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import data_paths  # noqa: E402
from wer_bench import norm_words, wer  # noqa: E402

TEMPLATES = (
    "Can you send the fire risk assessment to {t} by Friday?",
    "I spoke to {t} this morning about the renewal.",
    "Please add {t} to the meeting on Thursday afternoon.",
    "{t} asked for a quote for the extinguisher service.",
    "Let's follow up with {t} next week about the training.",
    "I've just had a call from {t} about the last invoice.",
    "Remind me to email {t} after lunch.",
    "We need to book the site visit with {t} for next month.",
)
CONTROLS = (
    "Can you send the report to the team by Friday?",
    "I spoke to the client this morning about the renewal.",
    "Please add the new starter to the meeting on Thursday.",
    "We need to book the site visit for next month.",
    "Remind me to call the office after lunch.",
    "The engineer said the alarm panel needs a new battery.",
    "Let's follow up next week about the training dates.",
    "I've just checked the extinguisher service schedule.",
)
VOICES = (("Hazel", 0), ("Zira", 0), ("Hazel", 1), ("Zira", -1))


def bench_dir() -> str:
    return os.path.join(data_paths.local_dir(), "bench")


def read_term_list(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [t for t in json.load(f) if isinstance(t, str) and t.strip()]


def load_terms(limit: int, path: str = "") -> tuple[list[str], list[dict]]:
    """CRM terms (estate-vocab.json, or `path`) and the user's own vocabulary
    entries from the installed config (every account key, deleted dropped)."""
    estate = []
    path = path or os.path.join(data_paths.roaming_dir(), "estate-vocab.json")
    try:
        estate = read_term_list(path)
    except Exception as e:
        print(f"[bench] No term list at {path} ({e}): user vocabulary only.")
    vocab = []
    try:
        with open(os.path.join(data_paths.local_dir(), "config.json"),
                  encoding="utf-8") as f:
            cfg = json.load(f)
        for entries in (cfg.get("vocabulary") or {}).values():
            vocab += [e for e in entries or [] if isinstance(e, dict)
                      and e.get("term") and not e.get("deleted")]
    except Exception as e:
        print(f"[bench] No installed config vocabulary ({e}).")
    return estate[:limit] if limit else estate, vocab


def spoken_form(raw: str) -> str:
    """What a person actually says for a CRM row: the trading name, without
    the legal suffix, tagline or address ("Fitzgerald Equipment", not
    "Fitzgerald Equipment Company, Inc."). The corrector aims at the same
    variants, so this is also the right answer to expect."""
    from text_expansion import managed_variants
    forms = managed_variants(raw)
    return forms[-1] if forms else raw


def _clip_id(prefix: str, i: int, text: str, voice: str, rate: int) -> str:
    # The file name carries the content, so an edited sentence is re-spoken
    # instead of scored against a stale recording.
    h = hashlib.sha1(f"{text}|{voice}|{rate}".encode("utf-8")).hexdigest()[:8]
    return f"{prefix}{i:04d}-{h}"


def build_corpus(estate: list[str], vocab: list[dict], seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    terms = ([(spoken_form(t), "crm") for t in estate]
             + [(e["term"], "own") for e in vocab])
    items = []
    for i, (term, source) in enumerate(terms):
        voice, rate = VOICES[i % len(VOICES)]
        text = rng.choice(TEMPLATES).format(t=term)
        items.append({"id": _clip_id("t", i, text, voice, rate), "text": text,
                      "term": term, "source": source, "voice": voice, "rate": rate})
    for i, text in enumerate(CONTROLS * 2):
        voice, rate = VOICES[i % len(VOICES)]
        items.append({"id": _clip_id("c", i, text, voice, rate), "text": text,
                      "term": "", "source": "control", "voice": voice, "rate": rate})
    return items


def insertion_probes(managed: list[dict], vocab: list[dict]) -> list[dict]:
    """Text only, no audio: for every ordinary word inside a CRM name, a plain
    sentence using that word must come through the corrector unchanged. This
    is the class of bug where a name's own word ("forklift") was rewritten
    into the whole name ("H & W Forklift")."""
    from text_expansion import _FUNCTION_WORDS, apply_vocabulary, apply_vocabulary_fuzzy
    words = {}
    for m in managed:
        for w in re.findall(r"[A-Za-z']+", m["term"]):
            low = w.lower()
            if len(low) >= 4 and low not in _FUNCTION_WORDS:
                words.setdefault(low, m["term"])
    out = []
    for low in sorted(words):
        text = f"Can you check the {low} again today?"
        fixed = apply_vocabulary_fuzzy(apply_vocabulary(text, vocab), vocab + managed)
        if fixed != text:
            out.append({"word": low, "from_term": words[low], "text": text,
                        "became": fixed})
    return out


def synthesize(items: list[dict], out_dir: str) -> None:
    """Speak every item with cscript + SAPI (no PowerShell: script execution
    is disabled by policy on managed PCs, and bypassing it is not an option)."""
    with open(os.path.join(out_dir, "corpus.json"), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    tsv = os.path.join(out_dir, "corpus.tsv")
    with open(tsv, "w", encoding="utf-16") as f:
        for it in items:
            text = " ".join(it["text"].split())
            f.write("\t".join((it["id"], it["voice"], str(it["rate"]), text)) + "\n")
    script = os.path.join(ROOT, "tools", "tts_sapi.vbs")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(["cscript.exe", "//nologo", script, tsv,
                        os.path.join(out_dir, "wav")],
                       capture_output=True, text=True, creationflags=flags)
    if r.returncode != 0:
        raise RuntimeError(f"speech synthesis failed: {(r.stderr or r.stdout).strip()[:500]}")
    print(f"[bench] {r.stdout.strip()}")


def managed_entries(estate: list[str]) -> list[dict]:
    """As app._managed_entries: legal suffixes stripped, case-insensitive dedupe."""
    from text_expansion import managed_variants
    seen, out = set(), []
    for raw in estate:
        for t in managed_variants(raw):
            if t.lower() not in seen:
                seen.add(t.lower())
                out.append({"term": t, "sounds_like": [], "managed": True})
    return out


def load_engine():
    from asr_engine import ParakeetTranscriber, download_model, model_files_present
    if not model_files_present(version="v2"):
        download_model(version="v2")
    eng = ParakeetTranscriber(auto_punctuate=True, end_punctuation="smart",
                              vad_gate=True, model_version="v2")
    eng.load_model()
    return eng


def app_pipeline(text: str, vocab: list[dict], managed: list[dict]) -> str:
    """The offline steps Echo runs after recognition (app._on_stop_recording,
    default settings, Live Typing off, not an email window)."""
    import homophones
    from disfluency import destutter
    from list_format import format_lists
    from spoken_commands import apply_spoken_commands
    from text_expansion import apply_vocabulary, apply_vocabulary_fuzzy
    text = destutter(text, source="assembled")
    text = homophones.fix(text, source="assembled")
    text = apply_spoken_commands(text)
    text = format_lists(text)
    text = apply_vocabulary(text, vocab)
    return apply_vocabulary_fuzzy(text, vocab + managed)


def _tokens(text: str) -> list[str]:
    """Words with punctuation dropped and "&" read as "and", so "Taste and Art"
    matches "Taste & Art" and "Inc" matches "Inc.": a written variant of the
    right name is not an error."""
    return re.findall(r"[A-Za-z0-9']+", (text or "").replace("&", " and "))


def has_term(text: str, term: str, exact: bool) -> bool:
    """`exact` keeps casing; both ignore punctuation (see _tokens)."""
    want, got = _tokens(term), _tokens(text)
    if not exact:
        want, got = [w.lower() for w in want], [w.lower() for w in got]
    n = len(want)
    return bool(n) and any(got[i:i + n] == want for i in range(len(got) - n + 1))


def has_term_strict(text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text or "") is not None


def score(items, out_dir, estate, vocab, known=None) -> dict:
    """`known` is the CRM vocabulary Echo has (default: the dictated terms)."""
    import audio_store
    from text_expansion import vocabulary_hotwords
    managed = managed_entries(estate if known is None else known)
    # As app._get_hotwords: own terms, then the managed/CRM variants.
    hotwords = ", ".join(p for p in (vocabulary_hotwords(vocab),
                                     ", ".join(m["term"] for m in managed)) if p)
    eng = load_engine()
    rows = []
    t0 = time.time()
    for it in items:
        audio, rate = audio_store.read(os.path.join(out_dir, "wav", it["id"] + ".wav"))
        raw = eng.transcribe(audio, rate, conf_out=[]).strip()
        cased = eng.transcribe(audio, rate, hotwords_str=hotwords, conf_out=[]).strip()
        app = app_pipeline(cased, vocab, managed)
        rows.append(dict(it, raw=raw, app=app))
    secs = time.time() - t0

    def summary(key):
        named = [r for r in rows if r["term"]]
        ctrl = [r for r in rows if not r["term"]]
        crm_terms = [m["term"] for m in managed]
        return {
            "term_strict": round(sum(has_term_strict(r[key], r["term"]) for r in named)
                                 / max(1, len(named)), 3),
            "term_exact": round(sum(has_term(r[key], r["term"], True) for r in named)
                                / max(1, len(named)), 3),
            "term_ci": round(sum(has_term(r[key], r["term"], False) for r in named)
                             / max(1, len(named)), 3),
            "wer": round(sum(wer(norm_words(r["text"]), norm_words(r[key]))
                             for r in rows) / max(1, len(rows)), 3),
            "false_fix": sum(any(has_term(r[key], t, False) and not has_term(r["text"], t, False)
                                 for t in crm_terms) for r in ctrl),
        }
    return {"when": datetime.datetime.now().isoformat(timespec="seconds"),
            "clips": len(rows), "named": sum(1 for r in rows if r["term"]),
            "seconds": round(secs, 1),
            "raw": summary("raw"), "app": summary("app"),
            "insertions": insertion_probes(managed, vocab), "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max CRM terms (0 = all)")
    ap.add_argument("--fresh", action="store_true", help="re-speak every clip")
    ap.add_argument("--terms", default="", help="JSON list of names to dictate "
                    "(default: estate-vocab.json)")
    ap.add_argument("--known", default="", help="JSON list of names Echo knows "
                    "(default: the same as --terms); compare vocabularies with it")
    args = ap.parse_args()
    out_dir = bench_dir()
    os.makedirs(out_dir, exist_ok=True)
    estate, vocab = load_terms(args.limit, args.terms)
    known = read_term_list(args.known) if args.known else None
    items = build_corpus(estate, vocab)
    if args.fresh:
        for it in items:
            p = os.path.join(out_dir, "wav", it["id"] + ".wav")
            if os.path.exists(p):
                os.remove(p)
    print(f"[bench] {len(items)} sentences ({len(estate)} CRM terms, "
          f"{len(vocab)} own terms, controls included)")
    synthesize(items, out_dir)
    report = score(items, out_dir, estate, vocab, known)
    report["terms_file"], report["known_file"] = args.terms, args.known
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(out_dir, f"report-{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    for key in ("raw", "app"):
        print(f"[bench] {key:4s} {report[key]}")
    print(f"[bench] insertion probes failed: {len(report['insertions'])}")
    print(f"[bench] {report['clips']} clips in {report['seconds']}s -> {path}")


if __name__ == "__main__":
    main()
