"""
Spoken lists — turn a clearly enumerated dictation into a real list.

    "Right, so here's a list of three things. first is the first thing,
     second is the second thing."

becomes

    Right, so here's a list of three things:

    1. First is the first thing
    2. Second is the second thing

Two shapes, and only two, because this changes the SHAPE of what the user said:

  * a **numbered list**, driven by ordinal markers at clause boundaries
    ("first … second … third", "firstly … secondly", "number one … number
    two", with "lastly"/"finally" allowed to close a run already under way);
  * a **bulleted list**, driven either by spoken bullet markers ("bullet
    point one … bullet point two", "next bullet point") or by an explicit
    announcement ("here are the three things", "we need the following")
    immediately followed by a short comma series ending in "and"/"or".

The guards exist because the markers are ordinary English. A run of two
ordinals needs an ANNOUNCEMENT in the lead-in ("a list of three things");
without one it takes three markers before anything happens, so a speaker who
merely says "first of all … second …" in passing is left alone. EXPLICIT
markers ("number one", "bullet point one") are the exception: nobody says
"number one … number two" at clause boundaries except to dictate a list, so
two of those are enough. Every item must be at least two words, and a comma
series must be at least three short items.

Content is never invented and the only thing deleted is the marker the number
(or bullet) now carries ("First, do X" -> "1. Do X", "number one, do X" ->
"1. Do X"), plus a joining word in front of it ("so, number one"). Where an
ORDINAL is part of the sentence ("first is the first thing") it stays, because
"1. Is the first thing" is worse than a little redundancy. "Number one" and
"bullet point one" are never part of the sentence, so they always go.

Applied once, on the whole utterance, at app.py's single post-processing point
— NEVER inside an engine's _post_process, which also runs on streamed chunks
and live captions, where a list spanning two commits would be split down the
middle and a newline typed into a chat box would send it.

Enabled via Config.auto_lists (default on), and skipped entirely while Live
Typing is on, where the words are already in the user's document.
"""

import re

# ── Markers ──────────────────────────────────────────────────────────────────

_ORDINALS = {
    "first": 1, "firstly": 1,
    "second": 2, "secondly": 2,
    "third": 3, "thirdly": 3,
    "fourth": 4, "fourthly": 4,
    "fifth": 5, "fifthly": 5,
    "sixth": 6, "sixthly": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
# Close a run that is already going. Never start one — "finally" opens far too
# many ordinary sentences.
_CLOSERS = ("lastly", "finally", "last of all", "last but not least")

_NUM_ALT = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r"|\d{1,2}"
# Spoken bullets: "bullet point one", "bullet 2", "bullet point number three",
# "next bullet point", or a bare "bullet point" that takes the next slot. The
# engines write numbers as words or digits, so both are accepted.
_BULLET_ALT = (
    r"(?:another|next|new)\s+bullet(?:\s+point)?"
    rf"|bullet(?:\s+point)?(?:\s+number)?\s+(?:{_NUM_ALT})"
    r"|bullet\s+point"
)
_MARKER_ALT = "|".join(
    [_BULLET_ALT, r"first of all", r"first off"]
    + sorted(_ORDINALS, key=len, reverse=True)
    + [rf"number\s+(?:{_NUM_ALT})"]
    + [re.escape(c) for c in _CLOSERS]
)
# group(1) separator · group(2) connective · group(3) marker · group(4) the
# punctuation that makes the marker a bare discourse word ("First, do X").
# A connective may carry its own comma ("so, number one"), which is how people
# lead into a list out loud.
_MARKER_RE = re.compile(
    r"(^|[.!?;:,]\s+|\n+)"
    r"((?:(?:and|then|also|but|so|now|next|okay|ok|right)\s*,?\s+)*)"
    rf"({_MARKER_ALT})\b(\s*[,:])?",
    re.IGNORECASE,
)

# A lead-in that says a list is coming. Only ever tested against the sentence
# immediately before the first marker.
_ANNOUNCE = re.compile(
    r"\b(?:here(?:'s|s| is| are)|there (?:is|are|were)|these are|those are"
    r"|the following|as follows|a list of|list of"
    r"|(?:start|make|do|write|begin|got|have)\s+a\s+(?:quick\s+|short\s+)?list"
    r"|list (?:for|of)"
    r"|(?:a )?(?:couple(?: of)?|few|number of|handful of|bunch of) "
    r"(?:things|reasons|steps|points|items|bits|tasks|ideas)"
    r"|(?:two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:things|reasons|steps|points|items|options|problems|issues|changes)"
    r"|(?:things|reasons|steps|points|items) (?:are|to do|i need|we need|i want)"
    r")\b",
    re.IGNORECASE,
)

_SENTENCE_END = re.compile(r"[.!?](?:[\"'”’)\]]+)?(?=\s|$)")
_MIN_ITEM_WORDS = 2


def _num(word: str):
    return int(word) if word.isdigit() else _NUMBER_WORDS.get(word)


def _marker_kind(word: str):
    """(index, kind) for a marker. kind is "ord" (first, second), "num"
    ("number one"), "bullet" or "close" ("finally"). index is a position,
    None for a run-closer, or "next" for a bullet that takes the next slot."""
    w = " ".join(word.lower().split())
    if "bullet" in w:
        n = _num(w.split()[-1])
        return (n if n else "next"), "bullet"
    if w.startswith("number "):
        return _num(w[7:]), "num"
    if w in ("first of all", "first off"):
        return 1, "ord"
    if w in _CLOSERS:
        return None, "close"
    return _ORDINALS.get(w), "ord"


def _last_sentence(text: str) -> str:
    parts = _SENTENCE_END.split(text.strip())
    return (parts[-1] if parts[-1].strip() else
            (parts[-2] if len(parts) > 1 else text))


def _cap(s: str) -> str:
    return s[0].upper() + s[1:] if s and s[0].islower() else s


def _markers(text: str):
    marks = []
    for m in _MARKER_RE.finditer(text):
        idx, kind = _marker_kind(m.group(3))
        # An ordinal that reads as part of the sentence stays in it; "number
        # one" and "bullet point one" never do.
        drop = bool(m.group(4)) or kind in ("num", "bullet")
        marks.append({
            "sep": m.start(1),
            "item": m.start(2),        # first character after the separator
            "body": (m.end(4) if m.group(4) else m.end(3)) if drop else m.start(3),
            "idx": idx,
            "kind": kind,
        })
    return marks


def _numbered(text: str):
    """A marker-driven numbered or bulleted list, or None when the text does
    not clearly hold one. Bullet markers and numbering markers never mix."""
    marks = _markers(text)
    if not marks:
        return None
    for bullets in (True, False):
        out = _build_run(text, marks, bullets)
        if out:
            return out
    return None


def _build_run(text: str, marks, bullets: bool):
    run, expect = [], 1
    for mk in marks:
        if mk["kind"] != "close" and (mk["kind"] == "bullet") != bullets:
            continue
        idx = mk["idx"]
        if idx is None:                # "finally" only ever closes a run
            if not run:
                continue
            idx = expect
        if idx == "next":              # "next bullet point" takes the next slot
            idx = expect
        if idx != expect:
            continue
        run.append(mk)
        expect += 1
    if len(run) < 2:
        return None

    lead = text[:run[0]["item"]].rstrip()
    announced = bool(_ANNOUNCE.search(_last_sentence(lead))) if lead else False
    explicit = all(mk["kind"] in ("num", "bullet", "close") for mk in run)
    # Two ordinals is only a list when the speaker said one was coming; without
    # that it takes three before this touches anything. "Number one … number
    # two" and "bullet point one … two" say so themselves.
    if len(run) < 3 and not announced and not explicit:
        return None

    bodies = []
    for i, mk in enumerate(run):
        end = run[i + 1]["sep"] if i + 1 < len(run) else len(text)
        bodies.append(text[mk["body"]:end].strip().strip(",;"))
    if any(len(b.split()) < _MIN_ITEM_WORDS for b in bodies):
        return None

    # When every item bar the last is a single sentence, the last one is too —
    # anything after its full stop is the user carrying on, and belongs in a
    # paragraph of its own rather than inside the final item.
    tail = ""
    if all(not _SENTENCE_END.search(b[:-1]) for b in bodies[:-1]):
        cut = _SENTENCE_END.search(bodies[-1])
        if cut and bodies[-1][cut.end():].strip():
            tail = bodies[-1][cut.end():].strip()
            bodies[-1] = bodies[-1][:cut.end()]

    items = [("• " if bullets else f"{i + 1}. ") + _cap(_trim_stop(b))
             for i, b in enumerate(bodies)]
    # An explicit run introduces itself, so its lead-in takes the colon too,
    # unless that lead-in is a finished sentence of its own.
    colon = announced or (explicit and lead[-1:] not in ".!?")
    return _assemble(lead, items, tail, colon)


# ── Bulleted list: an announcement plus a short comma series ─────────────────

_LEADING_CONJ = re.compile(r"^(?:and|or)\s+(?=\S)", re.IGNORECASE)
_INNER_CONJ = re.compile(r"\s+(?:and|or)\s+", re.IGNORECASE)
_MAX_BULLET_WORDS = 8


def _trim_stop(item: str) -> str:
    """Drop a terminal full stop from a list item. Only the LAST item still
    carries one (the others were consumed as the separator before the next
    marker), so this is what makes the list consistent rather than a change of
    content. "?" and "!" are kept — a number prefix does not replace those."""
    item = item.rstrip()
    return item[:-1].rstrip() if item.endswith(".") else item


def _split_final_conjunction(parts):
    """Turn "milk, bread and eggs" into three items. The last comma-part holds
    the conjunction standing in for the final comma — with an Oxford comma it
    leads that part ("bread, and eggs"), without one it sits inside it. No
    conjunction at all means this is not a spoken series, so return None."""
    last = parts[-1]
    stripped = _LEADING_CONJ.sub("", last)
    if stripped != last:
        parts[-1] = stripped
        return parts
    split_at = None
    for m in _INNER_CONJ.finditer(last):
        split_at = m                      # the LAST conjunction, not the first
    if split_at is None:
        return None
    parts[-1:] = [last[:split_at.start()].strip(),
                  last[split_at.end():].strip()]
    return parts if all(parts) else None


def _bulleted(text: str):
    """"…the three things we need: milk, bread and eggs" -> three bullets."""
    # The series is whatever follows the announcing clause, up to the end of
    # that sentence.
    for m in re.finditer(r"[:.]\s+|:\s*", text):
        lead = text[:m.start()].rstrip()
        if not lead or not _ANNOUNCE.search(_last_sentence(lead)):
            continue
        rest = text[m.end():]
        stop = _SENTENCE_END.search(rest)
        series = rest[:stop.end() - 1] if stop else rest
        after = rest[stop.end():].strip() if stop else ""
        parts = [p.strip() for p in series.split(",")]
        if not parts or any(not p for p in parts):
            continue
        parts = _split_final_conjunction(parts)
        if parts is None or len(parts) < 3:
            continue
        if any(len(p.split()) > _MAX_BULLET_WORDS for p in parts):
            continue
        items = [f"• {_cap(_trim_stop(p))}" for p in parts]
        return _assemble(lead, items, after, True)
    return None


def _assemble(lead: str, items, tail: str, announced: bool) -> str:
    lead = lead.rstrip()
    # An announced list gets the colon Ryan asked for: the lead-in's own stop
    # is replaced, never stacked, and a lead-in that ran straight into the
    # items ("…the three things I need" + ":") gains one. "?" and "!" are left
    # alone — they are the sentence, not a pause before a list.
    if lead and announced and not lead.endswith(":"):
        if lead[-1] in ".,;":
            lead = lead[:-1].rstrip()
        if lead and lead[-1] not in "?!":
            lead += ":"
    out = (lead + "\n\n" if lead else "") + "\n".join(items)
    if tail:
        out += "\n\n" + _cap(tail)
    return out


def format_lists(text: str) -> str:
    """Return `text` with a clearly-spoken list laid out, or unchanged."""
    if not text or len(text.split()) < 6:
        return text
    if "•" in text or re.search(r"^\s*\d+\.\s", text, re.MULTILINE):
        return text                      # already laid out — never re-format
    for build in (_numbered, _bulleted):
        try:
            out = build(text)
        except Exception:
            out = None
        if out and out != text:
            return out
    return text
