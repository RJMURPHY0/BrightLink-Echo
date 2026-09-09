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
  * a **bulleted list**, driven by an explicit announcement ("here are the
    three things", "we need the following") immediately followed by a short
    comma series ending in "and"/"or".

The guards exist because the markers are ordinary English. A run of two needs
an ANNOUNCEMENT in the lead-in ("a list of three things"); without one it takes
three markers before anything happens, so a speaker who merely says "first of
all … second …" in passing is left alone. Every item must be at least two
words, and a bullet series must be at least three short items.

Content is never invented and only ever ONE thing is deleted: a bare discourse
marker that the number now carries ("First, do X" -> "1. Do X"). Where the
marker is part of the sentence ("first is the first thing") it stays, because
"1. Is the first thing" is worse than a little redundancy.

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

_MARKER_ALT = "|".join(
    [r"first of all", r"first off"]
    + sorted(_ORDINALS, key=len, reverse=True)
    + [rf"number\s+{w}" for w in sorted(_NUMBER_WORDS, key=len, reverse=True)]
    + [re.escape(c) for c in _CLOSERS]
)
# group(1) separator · group(2) connective · group(3) marker · group(4) the
# punctuation that makes the marker a bare discourse word ("First, do X").
_MARKER_RE = re.compile(
    rf"(^|[.!?;:,]\s+|\n+)((?:(?:and|then|also|but|so|now|next)\s+)*)"
    rf"({_MARKER_ALT})\b(\s*,)?",
    re.IGNORECASE,
)

# A lead-in that says a list is coming. Only ever tested against the sentence
# immediately before the first marker.
_ANNOUNCE = re.compile(
    r"\b(?:here(?:'s|s| is| are)|there (?:is|are|were)|these are|those are"
    r"|the following|as follows|a list of|list of"
    r"|(?:a )?(?:couple|few|number) of (?:things|reasons|steps|points|items)"
    r"|(?:two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:things|reasons|steps|points|items|options|problems|issues|changes)"
    r"|(?:things|reasons|steps|points|items) (?:are|to do|i need|we need|i want)"
    r")\b",
    re.IGNORECASE,
)

_SENTENCE_END = re.compile(r"[.!?](?:[\"'”’)\]]+)?(?=\s|$)")
_MIN_ITEM_WORDS = 2


def _marker_index(word: str):
    """1-10 for an explicit marker, None for a run-closer ("finally")."""
    w = " ".join(word.lower().split())
    if w.startswith("number "):
        return _NUMBER_WORDS.get(w[7:])
    if w in ("first of all", "first off"):
        return 1
    if w in _CLOSERS:
        return None
    return _ORDINALS.get(w)


def _last_sentence(text: str) -> str:
    parts = _SENTENCE_END.split(text.strip())
    return (parts[-1] if parts[-1].strip() else
            (parts[-2] if len(parts) > 1 else text))


def _cap(s: str) -> str:
    return s[0].upper() + s[1:] if s and s[0].islower() else s


def _numbered(text: str):
    """The ordinal-marker list, or None when the text does not clearly hold one."""
    marks = []
    for m in _MARKER_RE.finditer(text):
        marks.append({
            "sep": m.start(1),
            "item": m.start(2),        # first character after the separator
            "body": m.end(4) if m.group(4) else m.start(3),
            "word": m.group(3),
            "bare": bool(m.group(4)),  # "First," — a pure discourse marker
            "idx": _marker_index(m.group(3)),
        })
    if not marks:
        return None

    run, expect = [], 1
    for mk in marks:
        idx = mk["idx"]
        if idx is None:                # "finally" only ever closes a run
            if not run:
                continue
            idx = expect
        if idx != expect:
            continue
        run.append(mk)
        expect += 1
    if len(run) < 2:
        return None

    lead = text[:run[0]["item"]].rstrip()
    announced = bool(_ANNOUNCE.search(_last_sentence(lead))) if lead else False
    # Two markers is only a list when the speaker said one was coming; without
    # that it takes three before this touches anything.
    if len(run) < 3 and not announced:
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

    items = [f"{i + 1}. {_cap(_trim_stop(b))}" for i, b in enumerate(bodies)]
    return _assemble(lead, items, tail, announced)


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
