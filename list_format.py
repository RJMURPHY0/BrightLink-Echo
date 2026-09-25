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
_POS_WORDS = (r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth"
              r"|tenth|next|last|final")
_BULLET_ALT = (
    r"(?:another|next|new)\s+bullet(?:\s+point)?"
    rf"|bullet(?:\s+point)?(?:\s+number)?\s+(?:{_NUM_ALT})"
    # "the first bullet point is CPU energy", "second bullet: GPU energy"
    rf"|(?:the\s+)?(?:{_POS_WORDS})\s+bullet(?:\s+point)?"
    r"(?:\s+(?:is|would\s+be|will\s+be))?"
    r"|bullet\s+point"
)
# "the first thing is …", "the second point is …", "the next one is …". The
# verb is REQUIRED: without it "the first thing I noticed was the colour" is
# ordinary speech, not a list item.
_ORD_NOUN_ALT = (
    rf"(?:the\s+)?(?:{_POS_WORDS})\s+(?:thing|point|item|one|step|reason)"
    r"\s+(?:is|would\s+be|will\s+be)"
)
_MARKER_ALT = "|".join(
    [_BULLET_ALT, _ORD_NOUN_ALT, r"first of all", r"first off"]
    + sorted(_ORDINALS, key=len, reverse=True)
    + [rf"number\s+(?:{_NUM_ALT})"]
    + [re.escape(c) for c in _CLOSERS]
)
# group(1) separator · group(2) connective · group(3) marker · group(4) the
# punctuation that makes the marker a bare discourse word ("First, do X").
# A connective may carry its own comma ("so, number one"), which is how people
# lead into a list out loud. The separator may be bare whitespace ("one thing
# and number two …" — people rarely pause audibly enough for a comma there),
# but only an EXPLICIT marker may use it, and only under an announcement
# (see _markers / _build_run).
_MARKER_RE = re.compile(
    r"(^|[.!?;:,]\s+|\n+|\s+)"
    r"((?:(?:and|then|also|but|so|now|next|okay|ok|right|for|like)\s*,?\s+)*)"
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
    r"|(?:to|me|i'll|i will|let's|let us|gonna|going to) list"
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

# An announcement only counts when the list follows it: at most this many words
# may sit between the announcing phrase and the items. "here are the three
# things I need" is 4; "none of the usage there is actually being used at all,
# and it would be really good if I could get the usage for" is 20, and reading
# that "there is" as an announcement is what laid a sentence out as bullets.
_ANNOUNCE_REACH = 8

# A lead-in that stops on one of these ("…get the usage for. The
# subscriptions…") did not finish: the full stop is a dictation pause, the
# sentence carries on, and nothing after it is a list.
_HANGING = frozenset((
    "a", "an", "the", "and", "or", "but", "for", "to", "of", "with", "about",
    "from", "in", "on", "at", "by", "into", "onto", "than", "that", "which",
    "who", "my", "your", "our", "their", "his", "her", "its", "this", "these",
    "those", "is", "are", "was", "were", "be", "get", "got", "have", "has",
))


def _announced(lead: str) -> bool:
    """True when the sentence right before the items says a list is coming,
    and says it close enough to the items to be introducing them."""
    if not lead:
        return False
    sentence = _last_sentence(lead)
    last = None
    for last in _ANNOUNCE.finditer(sentence):
        pass
    if last is None:
        return False
    return len(sentence[last.end():].split()) <= _ANNOUNCE_REACH


def _last_word(text: str) -> str:
    words = re.findall(r"[A-Za-z']+", text)
    return words[-1].lower() if words else ""


_EXAMPLE_TAIL = re.compile(
    r"(?:sort of thing|kind of thing|or something|or whatever|etc|"
    r"and so on|and stuff)", re.IGNORECASE)


def _num(word: str):
    return int(word) if word.isdigit() else _NUMBER_WORDS.get(word)


def _marker_kind(word: str):
    """(index, kind) for a marker. kind is "ord" (first, second), "num"
    ("number one"), "bullet" or "close" ("finally"). index is a position,
    None for a run-closer, or "next" for a bullet that takes the next slot."""
    w = " ".join(word.lower().split())
    words = w.split()
    if words[0] == "the":
        words = words[1:]
    head = words[0]

    def position():
        if head in _ORDINALS:
            return _ORDINALS[head]
        if head in ("last", "final"):
            return None
        return "next"

    if head == "number":
        return _num(words[1]), "num"
    if "bullet" in words:
        n = _num(words[-1])
        return (n if n else position()), "bullet"
    if len(words) > 2 and words[1] in (
            "thing", "point", "item", "one", "step", "reason"):
        return position(), "num"
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
        sep = m.group(1)
        bare = bool(sep) and not sep.strip()
        # A bare-space separator is only believable in front of an explicit
        # marker; "first" or "finally" mid-sentence is ordinary English.
        if bare and kind in ("ord", "close"):
            continue
        # An ordinal that reads as part of the sentence stays in it; "number
        # one" and "bullet point one" never do.
        drop = bool(m.group(4)) or kind in ("num", "bullet")
        marks.append({
            "sep": m.start(1),
            "item": m.start(2),        # first character after the separator
            "body": (m.end(4) if m.group(4) else m.end(3)) if drop else m.start(3),
            "idx": idx,
            "kind": kind,
            "bare": bare,
        })
    return marks


# Words that make a list item a sentence (so it takes a full stop) rather than
# a label ("CPU energy", "some milk and bread", "the login page").
_SUBJECT = re.compile(
    r"^(?:i|i'm|i've|i'll|i'd|we|we're|you|you're|they|they're|he|she|it|"
    r"it's|there|this|that|these|those|my|our)\b", re.IGNORECASE)
_VERB = re.compile(
    r"\b(?:is|are|was|were|am|be|been|want|wants|need|needs|have|has|had|"
    r"will|would|can|could|should|must|do|does|did|think|make|makes|get|"
    r"gets|go|goes|going)\b", re.IGNORECASE)


def _is_sentence(item: str) -> bool:
    return len(item.split()) >= 3 and bool(
        _SUBJECT.search(item) or _VERB.search(item))


def _fix_lone_i(item: str) -> str:
    """A lower-case "i" the engine left inside an item ("and number two i
    want…") — never the "i" in "i.e."."""
    return re.sub(r"(?<![\w.'])i(?=\s|'[a-z])", "I", item)


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
        # "first, so like number one, I want …": the same slot said twice in a
        # row. The later, more explicit marker wins, and the words between the
        # two are the speaker restarting, not part of the item.
        if run and idx == expect - 1 and mk["kind"] != "close":
            prev = run[-1]
            if len(text[prev["body"]:mk["sep"]].split()) <= 3:
                run[-1] = dict(prev, body=mk["body"])
                continue
        if idx != expect:
            continue
        run.append(mk)
        expect += 1
    if len(run) < 2:
        return None

    lead = text[:run[0]["item"]].rstrip()
    announced = _announced(lead)
    explicit = all(mk["kind"] in ("num", "bullet", "close") for mk in run)
    # Two ordinals is only a list when the speaker said one was coming; without
    # that it takes three before this touches anything. "Number one … number
    # two" and "bullet point one … two" say so themselves.
    if len(run) < 3 and not announced and not explicit:
        return None
    # "we scored number one in the league and number two in the cup" joins
    # its markers with bare spaces; only a spoken announcement makes that a
    # list.
    if any(mk["bare"] for mk in run) and not announced:
        return None

    bodies = []
    for i, mk in enumerate(run):
        end = run[i + 1]["sep"] if i + 1 < len(run) else len(text)
        bodies.append(text[mk["body"]:end].strip().strip(",;"))
    if any(len(b.split()) < _MIN_ITEM_WORDS for b in bodies):
        return None
    # "…like number one, number two, sort of thing": the markers were an
    # example the speaker gave, not a list they dictated.
    if any(_EXAMPLE_TAIL.match(b) for b in bodies):
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

    items = _finish_items(bodies, bullets)
    # An explicit run introduces itself, so its lead-in takes the colon too,
    # unless that lead-in is a finished sentence of its own.
    colon = announced or (explicit and lead[-1:] not in ".!?")
    return _assemble(lead, items, tail, colon)


# ── Bulleted list: an announcement plus a short comma series ─────────────────

# A comma series of real items. Spoken fillers and clause fragments are
# commas too ("the subscriptions I'm paying for, that are, you know, like AI
# related"), and none of them is ever a list item.
_FILLER_ITEMS = frozenset((
    "you know", "i mean", "like", "sort of", "kind of", "i guess", "i think",
    "and stuff", "or something", "or whatever", "basically", "actually",
    "so yeah", "yeah", "obviously", "honestly", "literally", "right", "okay",
    "ok", "well", "so", "um", "uh", "er", "also", "then", "too", "plus",
    "everything", "and everything", "etc", "and so on",
))
_FILLER_OPENERS = ("you know ", "i mean ", "like ", "sort of ", "kind of ")
# An item opening on one of these carries on the sentence before it ("but like
# still within the whole system", "that are").
_CLAUSE_OPENERS = frozenset(("that", "which", "who", "whose", "whom", "but",
                             "so", "because", "cause"))


def _is_series_item(item: str) -> bool:
    words = re.findall(r"[A-Za-z']+", item.lower())
    if not words:
        return False
    bare = " ".join(words)
    if bare in _FILLER_ITEMS or (bare + " ").startswith(_FILLER_OPENERS):
        return False
    # "that are": a relative clause hanging off the previous item, and any
    # item that stops on a function word, are one sentence split by commas.
    return words[0] not in _CLAUSE_OPENERS and words[-1] not in _HANGING


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
        if not _announced(lead):
            continue
        if text[m.start()] == "." and _last_word(lead) in _HANGING:
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
        if not all(_is_series_item(p) for p in parts):
            continue
        return _assemble(lead, _finish_items(parts, True), after, True)
    return None


def _finish_items(bodies, bullets: bool):
    """Marker, capital and ending for each item. Bullets are "- ": plain text
    everywhere, and a real bullet in every app that reads Markdown (ChatGPT,
    Claude, Teams, Slack). Items that are sentences end in a full stop, labels
    do not, and a list is consistent: the majority decides for every item."""
    texts = [_cap(_fix_lone_i(_trim_stop(b))) for b in bodies]
    stops = sum(_is_sentence(t) for t in texts) * 2 > len(texts)
    out = []
    for i, t in enumerate(texts):
        if stops and t[-1:] not in "?!.":
            t += "."
        out.append(("- " if bullets else f"{i + 1}. ") + t)
    return out


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
    if "•" in text or re.search(r"^\s*(?:\d+\.|-)\s", text, re.MULTILINE):
        return text                      # already laid out — never re-format
    for build in (_numbered, _bulleted):
        try:
            out = build(text)
        except Exception:
            out = None
        if out and out != text:
            return out
    return text
