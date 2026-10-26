"""
AI model names and their version numbers, written the way people type them.

    "opus five point five"          -> "Opus 5.5"
    "claude sonnet four point five" -> "Claude Sonnet 4.5"
    "chat gpt"                      -> "ChatGPT"
    "gpt five"                      -> "GPT-5"
    "gpt four o"                    -> "GPT-4o"
    "gemini 2 point 5 pro"          -> "Gemini 2.5 Pro"
    "deep seek v three"             -> "DeepSeek V3"

Two rules keep it safe in ordinary prose:

* Names that are also English words ("opus", "sonnet", "haiku", "fable",
  "gemini", "llama", "mistral") are only touched when a version number follows
  them. "a haiku about spring" and "the llama farm" are left alone.
* A number is only turned into digits when it follows a model name. "at one
  point five people left" stays as spoken.

Runs inside apply_spoken_commands, so every path (inject, upgrade, history)
sees the same text. Add new model families to the tables below.
"""

import re

_S = r"[ \t]+"

_ONES = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_NUMW = "|".join(sorted(list(_ONES) + list(_TENS), key=len, reverse=True))
# One spoken number up to 99, or digits: "five", "twenty five", "twenty-five", "5".
_NUM = rf"(?:\d+|(?:{_NUMW})(?:[ \t-]+(?:{'|'.join(_ONES)}))?)"
# A version: "5", "five point five", "5 point 5", "2.5". A "5. 5" split is left
# alone: it is as likely a sentence end as a version.
_VER = rf"(?:{_NUM}(?:(?:[ \t]+point[ \t]+|\.(?=\d)){_NUM})?)"

# Names that are only ever the model ("gpt", "grok"): spelling fixed anywhere.
_ALWAYS = [
    (r"chat[ \t-]?gpt", "ChatGPT"),
    (r"open[ \t]?ai", "OpenAI"),
    (r"deep[ \t]?seek", "DeepSeek"),
    (r"l\.?m\.?[ \t]?arena", "LMArena"),
    (r"hugging[ \t]?face", "Hugging Face"),
    (r"mid[ \t]?journey", "Midjourney"),
    (r"eleven[ \t]?labs", "ElevenLabs"),
    (r"anthropic", "Anthropic"),
    (r"gpt", "GPT"),
    (r"grok", "Grok"),
    (r"qwen", "Qwen"),
    (r"kimi", "Kimi"),
    (r"llm", "LLM"),
    (r"llms", "LLMs"),
]

# Families that take a version. Cased (and digitised) only when one follows.
_FAMILIES = [
    ("claude", "Claude"), ("opus", "Opus"), ("sonnet", "Sonnet"),
    ("haiku", "Haiku"), ("fable", "Fable"), ("gemini", "Gemini"),
    ("gemma", "Gemma"), ("llama", "Llama"), ("mistral", "Mistral"),
    ("grok", "Grok"), ("qwen", "Qwen"), ("kimi", "Kimi"), ("phi", "Phi"),
    ("gpt", "GPT"), ("deepseek", "DeepSeek"), ("deepseek v", "DeepSeek V"),
    ("deep seek", "DeepSeek"), ("deep seek v", "DeepSeek V"),
    ("codex", "Codex"), ("veo", "Veo"), ("sora", "Sora"), ("kling", "Kling"),
]
_FAM_CANON = {k: v for k, v in _FAMILIES}
_FAM_ALT = "|".join(re.escape(k).replace(r"\ ", "[ \t]+")
                    for k in sorted(_FAM_CANON, key=len, reverse=True))

# Suffix words cased after a versioned model: "Gemini 2.5 Pro", "GPT-5 mini".
_TIERS = {"pro": "Pro", "flash": "Flash", "ultra": "Ultra", "max": "Max",
          "mini": "mini", "nano": "nano", "turbo": "Turbo", "lite": "Lite",
          "preview": "Preview", "instruct": "Instruct", "thinking": "Thinking"}
_TIER_ALT = "|".join(_TIERS)

_VERSIONED = re.compile(
    rf"\b(?P<fam>{_FAM_ALT})(?P<sep>[ \t-]*)(?P<ver>{_VER})"
    rf"(?P<o>[ \t]+o\b|o\b)?(?P<tier>{_S}(?:{_TIER_ALT})\b)?",
    re.IGNORECASE)
_ALWAYS_RE = [(re.compile(rf"\b(?:{p})\b", re.IGNORECASE), s) for p, s in _ALWAYS]


def _num(tok: str):
    tok = tok.strip().lower()
    if tok.isdigit():
        return tok
    parts = [p for p in re.split(r"[ \t-]+", tok) if p]
    total = 0
    for p in parts:
        if p in _TENS:
            total += _TENS[p]
        elif p in _ONES:
            total += _ONES[p]
        else:
            return None
    return str(total)


def _version(spoken: str):
    halves = re.split(r"[ \t]+point[ \t]+|\.", spoken.strip(), maxsplit=1,
                      flags=re.IGNORECASE)
    out = [_num(h) for h in halves]
    if any(o is None for o in out):
        return None
    return ".".join(out)


def _sub_versioned(m: "re.Match") -> str:
    ver = _version(m.group("ver"))
    if ver is None:
        return m.group(0)
    key = re.sub(r"[ \t]+", " ", m.group("fam").lower())
    fam = _FAM_CANON.get(key, m.group("fam"))
    # Claude is also a first name: "gave Claude four tasks" stays as spoken.
    # Only a decimal ("Claude three point five") marks the model.
    if fam == "Claude" and "." not in ver:
        return m.group(0)
    if fam == "DeepSeek V":
        out = f"DeepSeek V{ver}"
    elif fam == "GPT":
        out = f"GPT-{ver}"
    else:
        out = f"{fam} {ver}"
    if m.group("o"):
        out += "o"
    if m.group("tier"):
        out += " " + _TIERS[m.group("tier").strip().lower()]
    return out


def apply_tech_terms(text: str) -> str:
    """Write AI model names and versions the way they are spelt."""
    if not text:
        return text
    out = _VERSIONED.sub(_sub_versioned, text)
    for pat, canon in _ALWAYS_RE:
        out = pat.sub(lambda m, c=canon: c, out)
    # "Claude Opus 5.5": the leading family word is cased by its own match only
    # when a version follows it directly, so case it here before a family name.
    out = re.sub(rf"\bclaude(?=[ \t]+(?:Opus|Sonnet|Haiku|Fable)\b)", "Claude",
                 out, flags=re.IGNORECASE)
    return out
