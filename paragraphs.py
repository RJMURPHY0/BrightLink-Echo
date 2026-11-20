"""
Local paragraph rules: instant, offline, used wherever the AI paragraph plan
did not reach (the last few sentences said before the release, or no AI).

Two rules, both only between finished sentences:

* A sentence that opens with a change-of-topic phrase ("Also,", "Another
  thing", "Secondly", "On another note", "Anyway", "Okay, so") starts a new
  paragraph, once the current one has at least two sentences and 40 words.
* A paragraph that has run past about 120 words breaks before the next
  sentence, so a long dictation is never one wall of text.

Pause breaks from the streaming session are kept as they are.
"""

import re

MIN_WORDS_BEFORE_SHIFT = 40
MIN_SENTENCES_BEFORE_SHIFT = 2
MAX_WORDS = 120

_OPENERS = re.compile(
    r"^(?:also|another thing|the other thing|one more thing|last thing|"
    r"secondly|thirdly|finally|lastly|next|separately|"
    r"on another note|on a different note|on a separate note|in other news|"
    r"moving on|besides that|apart from that|other than that|aside from that|"
    r"anyway|anyways|okay,? so|ok,? so|right,? so|so anyway|"
    r"as for|then there'?s|oh,? and|and another thing|"
    # The phrase as spoken; spaces escaped so the RegExp reads as a pattern.
    r"in\ terms\ of|with\ regards?\ to|regarding|when\ it\ comes\ to)\b",
    re.IGNORECASE)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=\S)")


def _words(s: str) -> int:
    return len(s.split())


def split_local(text: str, skip_keys=frozenset(), key=None) -> str:
    """Apply the local rules. `skip_keys`/`key`: sentences whose key is in
    skip_keys were already judged by the AI plan and are never split here."""
    if not text:
        return text
    if re.search(r"(?<!\n)\n(?!\n)", text):
        return text      # a list or email layout: not ours to touch
    out = []
    for para in text.split("\n\n"):
        sents = [s for s in _SENT_SPLIT.split(para.strip()) if s.strip()]
        if not sents:
            out.append(para)
            continue
        groups = [[sents[0]]]
        for s in sents[1:]:
            cur = groups[-1]
            n_words = sum(_words(x) for x in cur)
            judged = key is not None and key(s) in skip_keys
            if not judged and (
                    (_OPENERS.match(s) and len(cur) >= MIN_SENTENCES_BEFORE_SHIFT
                     and n_words >= MIN_WORDS_BEFORE_SHIFT)
                    or (n_words >= MAX_WORDS and len(cur) >= 2)):
                groups.append([s])
            else:
                cur.append(s)
        out.extend(" ".join(g) for g in groups)
    return "\n\n".join(out)
