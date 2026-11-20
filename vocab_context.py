"""
The names block the AI accuracy check gets with each piece of dictation.

It lists the speaker's own vocabulary, the CRM names, their job words and the
everyday tool names, but only the ones that could bear on THIS text, so the
block stays short: the BrightLink relay caps the system prompt at 4,000
characters, and a short list is also what keeps the model from "fixing" a word
into a name nobody said.

A term is relevant when one of its words starts with the same three letters as
a word in the text ("clawed" -> Claude, "riddor" -> RIDDOR), or when a known
sound-alike of it appears (common_terms.CONTEXT_NAMES: "homies" -> Hermes).
The user's own vocabulary is always included first; it is short and hand-made.
"""

import re

import common_terms

MAX_CHARS = 2200
# The line holding the names list; speculative_fix reads the names back from
# it, and only from it.
LIST_MARK = ("Names and work words this speaker uses. Spell them exactly as "
             "written here: ")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'&.-]*")


def _prefixes(text: str) -> set:
    return {w.lower()[:3] for w in _WORD.findall(text or "") if len(w) >= 3}


def _relevant(term: str, prefixes: set) -> bool:
    for w in _WORD.findall(term):
        if len(w) >= 3 and w.lower()[:3] in prefixes:
            return True
        if len(w) < 3 and w.lower() in prefixes:
            return True
    return False


def _sound_alike_hits(text: str) -> list:
    low = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    out = []
    for name, alikes in common_terms.CONTEXT_NAMES.items():
        if any(f" {a.lower()} " in low or f" {a.lower()}," in low
               or f" {a.lower()}." in low for a in alikes):
            out.append(name)
    return out


def block(text: str, user_terms=(), crm_names=(), job_terms=(),
          job_line: str = "") -> str:
    """The names block for `text`, or "" when there is nothing to say."""
    prefixes = _prefixes(text)
    picked, seen = [], set()

    def add(term):
        t = (term or "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            picked.append(t)

    for t in user_terms:
        add(t)
    for t in _sound_alike_hits(text):
        add(t)
    for t in common_terms.CONTEXT_NAMES:
        if _relevant(t, prefixes):
            add(t)
    for t in crm_names:
        if _relevant(t, prefixes):
            add(t)
    for t in job_terms:
        if _relevant(t, prefixes):
            add(t)
    for t in common_terms.names_for_prompt():
        if _relevant(t, prefixes):
            add(t)
    if not picked and not job_line:
        return ""
    head = LIST_MARK
    body, used = [], len(head) + len(job_line) + 2
    for t in picked:
        if used + len(t) + 2 > MAX_CHARS:
            break
        # "; " separates the names, so one may hold a comma ("Smith, Jones
        # & Co") without splitting into names nobody listed.
        body.append(t.replace(";", ","))
        used += len(t) + 2
    lines = []
    if job_line:
        lines.append(job_line)
    if body:
        lines.append(head + "; ".join(body) + ".")
    # The known mishearings of the names in play, said plainly: with only the
    # list, the model left "short-term memory and clawed" alone (real-model
    # check, 2026-11-20). Only names whose sound-alike is in this text.
    hints = []
    for name in _sound_alike_hits(text):
        if name in body:
            alikes = ", ".join(f'"{a}"' for a in common_terms.CONTEXT_NAMES[name])
            hints.append(f"{name} (speech-to-text often writes it as {alikes})")
    if hints:
        lines.append("Often misheard here: " + "; ".join(hints) + ". Use the name "
                     "only where the sentence means it.")
    return "\n".join(lines)

def listed_names(block: str) -> list:
    """The names in a block made by block(), and nothing else from it."""
    for line in (block or "").splitlines():
        if line.startswith(LIST_MARK):
            body = line[len(LIST_MARK):].rstrip(".")
            return [n.strip() for n in body.split("; ") if n.strip()]
    return []
