"""Scores one refine result against its dictation, offline and with no model.

Each check answers one question a user would ask before accepting a refine:
is everything I said still there, did it invent anything, does it still sound
like me, is it British English, did it keep my layout, is the length sane.
A result passes when every hard check passes. Used by run_eval.py and pinned
by tests/test_refine_eval_checks.py.
"""

import re

MODES = ("punctuation", "formal", "casual", "concise", "email")
PROMPT_MODES = ("prompt_optimiser", "punctuation")

# Output length / input length, in words, that a user would still call the
# same message refined. Fix All only removes fillers; Short may cut a lot.
LENGTH_BANDS = {
    "punctuation": (0.70, 1.10),
    "formal": (0.70, 1.45),
    "casual": (0.70, 1.35),
    "concise": (0.35, 1.05),
    "email": (0.65, 1.45),
    "prompt_optimiser": (0.70, 3.50),
}

# Share of the speaker's own content words that must survive (their voice).
VOICE_MIN = {
    "punctuation": 0.90,
    "formal": 0.60,
    "casual": 0.60,
    "concise": 0.45,
    "email": 0.65,
    "prompt_optimiser": 0.0,
}

# Corporate padding a user did not say and would delete before sending.
FLUFF = (
    "hope this email finds you", "hope this message finds you",
    "hope this finds you", "hope you are doing well", "hope you're doing well",
    "do not hesitate", "don't hesitate", "please feel free",
    "at your earliest convenience", "i trust this", "i trust you",
    "thank you for your time", "thank you for your attention",
    "look forward to hearing from you", "looking forward to hearing from you",
    "i wanted to reach out", "reach out", "touch base", "circle back",
    "please be advised", "rest assured", "i would like to inform you",
    "kindly", "furthermore", "moreover", "additionally",
    "i am writing to", "i'm writing to", "please let me know if you have any further",
    "should you have any", "further questions", "warm regards", "dear ",
    "subject:", "here is the", "here's the", "sure,", "certainly",
)

SLOP = (
    "delve", "leverage", "robust", "seamless", "elevate", "unlock", "tapestry",
    "landscape", "navigate the complexities", "fast-paced", "simply",
    "essentially", "basically", "arguably", "notably", "utilise", "utilize",
    "streamline", "synergy", "game-changer", "cutting-edge",
)

_US = re.compile(
    r"\b(?:color\w*|colors?|favor\w*|honor\w*|behavior\w*|labor\w*|center\w*|"
    r"gray|traveled|traveling|canceled|canceling|fulfill|enrollment|catalog|"
    r"organiz\w*|realiz\w*|analyz\w*|apologiz\w*|recogniz\w*|prioritiz\w*|"
    r"finaliz\w*|minimiz\w*|maximiz\w*|summariz\w*|emphasiz\w*|optimiz\w*|"
    r"customiz\w*|categoriz\w*|authoriz\w*|utiliz\w*|specializ\w*)\b", re.I)

STOPWORDS = frozenset("""
a an the and or but so if to of in on at for by with from as is are was were be
been am i you we he she it they me us him her them my your our his its their this
that these those there here what which who whom do does did done have has had
will would can could should shall may might must not no yes just very really
also then than too up down out over about into off again any all some one
um uh er erm like you know yeah ok okay well sort kind basically honestly
""".split())

_WORD = re.compile(r"[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'’]*")
_NUM = re.compile(r"\d[\d,.:]*\d|\d")
_DASH = re.compile("[—–]")


def _norm(s: str) -> str:
    return (s or "").replace("’", "'").replace("\r\n", "\n")


def words(s: str):
    return [w.lower().strip("'") for w in _WORD.findall(_norm(s))]


def content_words(s: str):
    return [w for w in words(s) if w not in STOPWORDS and len(w) > 1]


def numbers(s: str):
    return {n.rstrip(".,:").replace(",", "") for n in _NUM.findall(_norm(s))}


def kept_items(keep, out: str):
    """Required items missing from the result. "3 year" and "3-year" are the
    same words; a hyphen added to a compound adjective is grammar, not a change."""
    o = _norm(out).lower().replace("-", " ")
    return [k for k in keep if _norm(k).lower().replace("-", " ") not in o]


def added_numbers(text: str, out: str):
    return sorted(numbers(out) - numbers(text))


def added_names(text: str, out: str):
    """Capitalised words mid-sentence in the result that the speaker never said."""
    said = {t.lower() for t in re.findall(r"[A-Za-z0-9À-ɏ']+", _norm(text))}
    found = []
    for line in _norm(out).split("\n"):
        tokens = re.findall(r"\S+", line)
        for i, tok in enumerate(tokens):
            w = tok.strip("\"'()[],.;:!?")
            if (not w or not w[0].isupper() or w.lower().strip("'") in said
                    or w.lower() in _norm(text).lower()):
                continue
            prev = tokens[i - 1] if i else ""
            if i == 0 or prev.endswith((".", "!", "?", ":")):
                continue
            if w in ("I", "I'm", "I'll", "I've", "I'd"):
                continue
            found.append(w)
    return found


def fluff(text: str, out: str):
    t, o = _norm(text).lower(), _norm(out).lower()
    return [p.strip() for p in FLUFF if p in o and p not in t]


def slop(text: str, out: str):
    t, o = set(words(text)), _norm(out).lower()
    hits = []
    for p in SLOP:
        if " " in p or "-" in p:
            if p in o and p not in _norm(text).lower():
                hits.append(p)
        elif re.search(r"\b" + re.escape(p) + r"\w*\b", o) and p not in t:
            hits.append(p)
    return hits


def us_spelling(text: str, out: str):
    said = {m.lower() for m in _US.findall(_norm(text))}
    return [m for m in _US.findall(_norm(out)) if m.lower() not in said]


def new_dashes(text: str, out: str) -> int:
    return 0 if _DASH.search(text or "") else len(_DASH.findall(out or ""))


def new_exclamations(text: str, out: str) -> int:
    return max(0, (out or "").count("!") - (text or "").count("!"))


def invented_markdown(text: str, out: str) -> bool:
    if re.search(r"(?m)^\s*(?:[-•*]|\d+[.)])\s+\S", text or ""):
        return False
    return bool(re.search(r"(?m)^\s*(?:[-•*#]|\d+[.)])\s+\S|\*\*", out or ""))


def _content_lines(s: str):
    return [l.strip() for l in _norm(s).split("\n") if l.strip()]


def layout_problems(case: dict, mode: str, out: str):
    probs = []
    lines = _content_lines(out)
    if not lines:
        return ["empty"]
    if case.get("greeting") and mode in ("punctuation", "email", "formal", "casual"):
        if lines[0].rstrip(",") .lower() != case["greeting"].rstrip(",").lower():
            probs.append(f"greeting line changed: {lines[0][:40]!r}")
    if case.get("signoff") and mode in ("punctuation", "email", "formal", "casual"):
        want = case["signoff"]
        got = lines[-len(want):]
        if [g.lower() for g in got] != [w.lower() for w in want]:
            probs.append(f"sign-off changed: {got!r}")
    for marker in case.get("list_lines", ()):
        if not any(l.startswith(marker) for l in lines):
            probs.append(f"list line {marker} lost")
    if mode == "punctuation" and "\n" in case["text"]:
        if len(lines) != len(_content_lines(case["text"])):
            probs.append("line count changed")
    return probs


def length_ratio(text: str, out: str) -> float:
    n = len(words(text)) or 1
    return len(words(out)) / n


def voice_retention(text: str, out: str) -> float:
    src = content_words(text)
    if not src:
        return 1.0
    have = set(content_words(out))
    return sum(1 for w in src if w in have) / len(src)


def score(case: dict, mode: str, out: str) -> dict:
    text = case["text"]
    lo, hi = LENGTH_BANDS[mode]
    ratio = length_ratio(text, out)
    voice = voice_retention(text, out)
    r = {
        "missing": kept_items(case.get("keep", ()), out),
        "added_numbers": added_numbers(text, out),
        "added_names": added_names(text, out) if mode != "prompt_optimiser" else [],
        "fluff": fluff(text, out),
        "slop": slop(text, out),
        "us_spelling": us_spelling(text, out),
        "dashes": new_dashes(text, out),
        "exclamations": new_exclamations(text, out) if mode != "prompt_optimiser" else 0,
        "markdown": invented_markdown(text, out) if mode != "prompt_optimiser" else False,
        "layout": layout_problems(case, mode, out),
        "length_ratio": round(ratio, 2),
        "length_ok": lo <= ratio <= hi,
        "voice": round(voice, 2),
        "voice_ok": voice >= VOICE_MIN[mode],
    }
    r["meaning_ok"] = not r["missing"] and not r["added_numbers"] and not r["added_names"]
    r["tone_ok"] = not (r["fluff"] or r["slop"] or r["dashes"] or r["exclamations"])
    r["uk_ok"] = not r["us_spelling"]
    r["layout_ok"] = not r["layout"] and not r["markdown"]
    r["pass"] = all(r[k] for k in ("meaning_ok", "tone_ok", "uk_ok", "layout_ok",
                                    "length_ok", "voice_ok"))
    return r
