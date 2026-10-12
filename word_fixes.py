"""
"Fix words" in History: the user corrects a dictation, Echo learns the fix.

The user edits the text the way it should have read and presses Enter. This
module works out which words they actually changed and turns each change into
a vocabulary rule ("when I hear X, write Y"), so the same mishearing is put
right on every later dictation, on every PC the vocabulary syncs to.

Only a change that looks like a MISHEARING is learned. A correction is a
mishearing when the old words sound like the new ones (same Double Metaphone
code, or close letters); anything else is the user changing their mind
("Monday" -> "Tuesday"), which must fix this one dictation and teach nothing.
On top of that:

  * punctuation and spacing edits teach nothing;
  * a casing-only edit of a name ("brightlink" -> "BrightLink") becomes a term
    with no mishearings, which Echo's casing pass applies everywhere;
  * an edit that rewrites most of the text is a rewrite, not a fix;
  * a rule whose trigger is only everyday words ("the sale" -> "the sail") is
    refused: it would rewrite ordinary speech on every dictation;
  * a change of digits is data, never a sound, so it is never learned.

Learning merges into the user's existing entry for the same term, and every
change it makes can be undone exactly (undo_learned).
"""

import difflib
import re

import text_expansion
import vocab_store

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'&-]*")
_MAX_SPAN_WORDS = 5          # a mishearing is a few words, not a sentence
_MAX_CHANGED_SHARE = 0.5     # more of the text changed than this is a rewrite
_SOUND_JW = 0.75             # letter similarity that still counts as a sound-alike
_CODE_JW = 0.88              # sound-code similarity ("TKSPRKL" vs "TTKSPRKL")
_CODE_MIN = 4                # ...only for codes long enough to mean something
_DIGITS = re.compile(r"\d+")


def _words(text: str) -> list:
    return _WORD.findall(text or "")


def _sentence_starts(text: str) -> set:
    """Indexes of the words that open a sentence: their capital is grammar,
    not a name."""
    starts, prev_end = set(), 0
    for i, m in enumerate(_WORD.finditer(text or "")):
        gap = (text or "")[prev_end:m.start()]
        if i == 0 or re.search(r"[.!?:\n]", gap):
            starts.add(i)
        prev_end = m.end()
    return starts


def _everyday(word: str) -> bool:
    low = word.lower()
    return (low in text_expansion._COMMON_WORDS
            or low in text_expansion._FUNCTION_WORDS)


def _sounds_alike(heard: str, meant: str) -> bool:
    """The old words could be a mishearing of the new ones."""
    a = text_expansion._spoken_form(heard.lower())
    b = text_expansion._spoken_form(meant.lower())
    if a.replace(" ", "") == b.replace(" ", ""):
        return True
    dm = text_expansion._dm()
    if dm is not None:
        try:
            ca, cb = dm(a), dm(b)
            if ca[0] and (ca[0] == cb[0] or ca[0] == cb[1] or ca[1] == cb[0]):
                return True
            # A sound code one slip away: "tick sparkley" for "TEDx
            # Berkeley" (TKSPRKL / TTKSPRKL), where the letters look
            # nothing alike. "Monday"/"Tuesday" (MNT / TST) stays out.
            if (min(len(ca[0]), len(cb[0])) >= _CODE_MIN
                    and text_expansion._jaro_winkler(ca[0], cb[0]) >= _CODE_JW):
                return True
        except Exception:
            pass
    return text_expansion._jaro_winkler(a.replace(" ", ""),
                                        b.replace(" ", "")) >= _SOUND_JW


def learn(old: str, new: str) -> dict:
    """What a correction teaches.

    Returns {"learned": [{"heard": str | None, "term": str}],
             "skipped": [{"heard": str, "term": str, "why": str}]}.
    heard None means a casing-only fix: the term is learned with no
    mishearing, so Echo writes it with this casing wherever it is said."""
    out = {"learned": [], "skipped": []}
    a, b = _words(old), _words(new)
    if not a or not b:
        return out
    al, bl = [w.lower() for w in a], [w.lower() for w in b]
    sm = difflib.SequenceMatcher(a=al, b=bl, autojunk=False)
    ops = sm.get_opcodes()
    changed = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in ops
                  if tag != "equal")
    if changed > max(1, len(a)) * _MAX_CHANGED_SHARE and changed > 2:
        out["skipped"].append({"heard": old, "term": new,
                               "why": "rewrite"})
        return out
    seen = set()
    starts = _sentence_starts(new)

    def _add(kind, heard, term, why=""):
        key = ((heard or "").lower(), term.lower())
        if key in seen:
            return
        seen.add(key)
        if kind == "learned":
            out["learned"].append({"heard": heard, "term": term})
        else:
            out["skipped"].append({"heard": heard or "", "term": term, "why": why})

    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            # Same words, different capitals: a name the user wants cased.
            for k in range(i2 - i1):
                was, now = a[i1 + k], b[j1 + k]
                capital_is_grammar = (j1 + k in starts
                                      and now[1:] == now[1:].lower())
                if (was != now and now != now.lower() and len(now) >= 3
                        and not _everyday(now) and not capital_is_grammar):
                    _add("learned", None, now)
            continue
        if tag != "replace":
            continue        # a word added or removed is an edit, not a sound
        heard = " ".join(a[i1:i2])
        term = " ".join(b[j1:j2])
        if (i2 - i1) > _MAX_SPAN_WORDS or (j2 - j1) > _MAX_SPAN_WORDS:
            _add("skipped", heard, term, "too long")
        elif _DIGITS.findall(heard) != _DIGITS.findall(term):
            _add("skipped", heard, term, "numbers")
        elif all(_everyday(w) for w in a[i1:i2]):
            _add("skipped", heard, term, "everyday words")
        elif not _sounds_alike(heard, term):
            _add("skipped", heard, term, "not a mishearing")
        elif not text_expansion.validate_sounds_like(heard, term)[0]:
            _add("skipped", heard, term, "too short")
        else:
            _add("learned", heard, term)
    return out


def apply_learned(config, learned: list, email=None) -> list:
    """Write each lesson into the user's vocabulary. A term the user already
    has gains the new mishearing; a new term becomes a new entry. Returns an
    undo record for undo_learned()."""
    undo = []
    for lesson in learned:
        term = " ".join((lesson.get("term") or "").split())
        heard = " ".join((lesson.get("heard") or "").split())
        if not term:
            continue
        entries = vocab_store.load(config, "vocabulary", email)
        match = next((e for e in entries
                      if (e.get("term") or "").lower() == term.lower()), None)
        if match is None:
            entry = vocab_store.new_entry(term=term,
                                          sounds_like=[heard] if heard else [])
            vocab_store.upsert(config, "vocabulary", entry, email)
            undo.append({"id": entry["id"], "before": None})
            continue
        sounds = list(match.get("sounds_like") or [])
        if heard and heard.lower() not in (s.lower() for s in sounds):
            before = {**match, "sounds_like": list(sounds)}
            vocab_store.upsert(config, "vocabulary",
                               {**match, "sounds_like": sounds + [heard]}, email)
            undo.append({"id": match["id"], "before": before})
    return undo


def undo_learned(config, undo: list, email=None) -> None:
    """Put the vocabulary back exactly as it was before apply_learned()."""
    for rec in reversed(undo or []):
        if rec.get("before") is None:
            vocab_store.soft_delete(config, "vocabulary", rec["id"], email)
        else:
            vocab_store.upsert(config, "vocabulary", dict(rec["before"]), email)


def summary(learned: list) -> str:
    """One short line for the toast: what Echo will do from now on."""
    if not learned:
        return ""
    first = learned[0]
    head = (f"{first['heard']} → {first['term']}" if first.get("heard")
            else f"writes {first['term']}")
    more = len(learned) - 1
    return f"Learned: {head}" + (f" (+{more} more)" if more else "")
