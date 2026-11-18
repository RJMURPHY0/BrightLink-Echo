"""
How sure the recogniser was about each word of the finished dictation.

Parakeet's decoder already scores every token it emits (see
`asr_engine._recognize` and `phrase_learning.words_from_tokens`): the engine
fills a `(word, confidence)` record in spoken order at no extra stop latency.
This module turns that record into something the post-passes can ask about a
word of the FINISHED text, which is close to but never exactly the record
(destutter removes words, vocabulary rewrites some).

One rule runs through every caller: **a word the engine was sure about is never
changed, and a word whose confidence cannot be established counts as sure.**
Unknown fails closed, so a bad alignment costs a correction, never a word the
user said.

Callers:
  * `homophones.fix(word_conf=...)`: rules marked `unsure` fire only on a word
    the engine hesitated over.
  * `text_expansion.apply_vocabulary_fuzzy(word_conf=...)`: company and CRM
    names (the managed tier) may only rewrite a span the engine was unsure of.
  * `restrict_to_unsure()`: the background LLM context fix may only change
    words the engine was unsure of; everything else keeps the injected text.

Pure Python over lists of a few hundred items: microseconds, and all of it runs
after the text is chosen, never on the decode.
"""

import difflib
import re
from typing import List, Optional

# A word under this is one the engine hesitated over. Measured on Ryan's own
# dictations (2026-11-18): the misheard words sat at 0.51-0.75 ("to" for
# "too" 0.51, "two" for "too" 0.62, "versus" for "fixes" 0.75) while most words
# he said clearly score 0.9-1.0. Plenty of correct words also score in the
# 0.6-0.8 band, so confidence alone never decides a correction; it only
# decides which words a context rule or the LLM is allowed to touch at all.
UNSURE = 0.80

# What the managed tier (company profile and CRM names) needs before it may
# rewrite a span: at least one word of the span under this. Lives in
# text_expansion, which applies it.
from text_expansion import MANAGED_SURE, _WORD_RE  # noqa: E402,F401
_TOKEN_RE = re.compile(r"\S+")


def aligned(text: str, recorded) -> List[Optional[float]]:
    """Confidence per `_WORD_RE` word of `text` (None where unknown).

    Delegates to phrase_learning.align, the one aligner the app uses, so every
    pass agrees on which recorded word a text word came from."""
    if not text:
        return []
    try:
        import phrase_learning
        return list(phrase_learning.align(text, recorded or []))
    except Exception:
        return [None] * len(_WORD_RE.findall(text))


def by_offset(text: str, recorded) -> dict:
    """{start offset of each word in `text`: confidence or None}."""
    confs = aligned(text, recorded)
    out = {}
    for i, m in enumerate(_WORD_RE.finditer(text or "")):
        out[m.start()] = confs[i] if i < len(confs) else None
    return out


def is_unsure(conf: Optional[float], limit: float = UNSURE) -> bool:
    """True only for a KNOWN confidence under `limit`."""
    return conf is not None and conf < limit


def _bare(tok: str) -> str:
    return "".join(_WORD_RE.findall(tok)).lower()


def restrict_to_unsure(original: str, proposed: str, recorded,
                       limit: float = UNSURE) -> str:
    """`proposed` with every change to a word the engine was SURE about undone.

    Word-level diff of original against proposed. A replaced run is accepted
    only when every original word in it was unsure, and it may not grow by more
    than one word (a contraction or a split compound) nor shrink to nothing.
    A pure insertion or deletion is refused: the fix may correct how a word was
    heard, never add or drop one. Unchanged words keep the ORIGINAL token, so
    spacing, line breaks and punctuation the app laid out survive exactly.

    With no confidence record at all (whisper fallback, a failed timestamp
    pass) the proposal is returned as it was: that is today's behaviour, and
    the user still has to accept it in the popup."""
    if not original or not proposed or proposed == original:
        return proposed
    if not recorded:
        return proposed
    word_confs = aligned(original, recorded)
    words = list(_WORD_RE.finditer(original))
    otoks = list(_TOKEN_RE.finditer(original))
    ptoks = [m.group(0) for m in _TOKEN_RE.finditer(proposed)]
    if not otoks or not ptoks:
        return original

    def _tok_conf(m) -> Optional[float]:
        # A token's confidence is its least sure word; unknown if any is.
        vals = []
        for i, w in enumerate(words):
            if m.start() <= w.start() < m.end():
                c = word_confs[i] if i < len(word_confs) else None
                if c is None:
                    return None
                vals.append(c)
        return min(vals) if vals else None

    sm = difflib.SequenceMatcher(
        a=[_bare(m.group(0)) for m in otoks], b=[_bare(t) for t in ptoks],
        autojunk=False)
    edits = []          # (start, end, replacement) into original
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "replace":
            continue    # equal keeps the original; insert/delete refused
        if (j2 - j1) > (i2 - i1) + 1 or (i2 - i1) > 3:
            continue
        if not all(is_unsure(_tok_conf(otoks[k]), limit) for k in range(i1, i2)):
            continue
        edits.append((otoks[i1].start(), otoks[i2 - 1].end(),
                      " ".join(ptoks[j1:j2])))
    if not edits:
        return original
    out, pos = [], 0
    for s, e, rep in edits:
        out.append(original[pos:s])
        out.append(rep)
        pos = e
    out.append(original[pos:])
    return "".join(out)
