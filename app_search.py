"""
Universal search: match a query against the app's pages and settings, and build
the Ask AI help prompt. Pure logic, no tkinter, so it is unit-testable and the
UI in app_window only has to render what these functions return.

An ENTRY is a plain dict the UI builds once from the pages and the settings
cards it lays out:

    {"kind": "page"|"setting", "title": str, "subtext": str,
     "keywords": str, "location": str, "target": <opaque, used by the UI>}

`match_entries` ranks entries whose text contains every word of the query;
`looks_like_question` decides whether Enter should run Ask AI rather than jump to
the first result; `help_prompt` turns the catalogue into the system prompt for
the app-scoped Ask AI answer.
"""

import re

import brand

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def normalise(s: str) -> str:
    return " ".join((s or "").lower().split())


def tokens(q: str):
    return [t for t in _WORD.findall((q or "").lower()) if t]


def _haystack(e: dict) -> str:
    return normalise(" ".join((
        e.get("title", ""), e.get("keywords", ""),
        e.get("subtext", ""), e.get("location", ""))))


def match_entries(query: str, entries, limit: int = 8):
    """Entries containing every query word, best first.

    Ranking, in order of weight: the whole query as a run inside the title, all
    words present in the title, the whole query as a run anywhere, then how
    early the first word falls (earlier = better). A page edges out a setting of
    equal score so "history" lands on the History page, not a setting that
    mentions it.
    """
    q = tokens(query)
    if not q:
        return []
    joined = " ".join(q)
    scored = []
    for e in entries:
        hay = _haystack(e)
        title = normalise(e.get("title", ""))
        if not all(t in hay for t in q):
            continue
        score = 0
        if joined in title:
            score += 100
        if all(t in title for t in q):
            score += 40
        if joined in hay:
            score += 10
        pos = hay.find(q[0])
        score -= pos if 0 <= pos < 80 else 80
        if e.get("kind") == "page":
            score += 5
        scored.append((score, e))
    scored.sort(key=lambda se: se[0], reverse=True)
    return [e for _s, e in scored[:limit]]


_QUESTION_STARTS = {
    "how", "what", "whats", "why", "when", "where", "who", "which", "can",
    "could", "would", "will", "does", "do", "did", "is", "are", "should",
    "explain", "tell", "help",
}


def looks_like_question(q: str) -> bool:
    """True when the query reads as a question for Ask AI rather than a term to
    jump to: it ends with '?', opens with a question word, or is a long phrase."""
    s = (q or "").strip()
    if not s:
        return False
    if s.endswith("?"):
        return True
    toks = tokens(s)
    if toks and toks[0] in _QUESTION_STARTS:
        return True
    return len(toks) >= 5


def help_prompt(catalogue) -> str:
    """The system prompt for the app-scoped Ask AI answer, listing every page
    and setting so the model answers from the real app, not from guesswork."""
    lines = []
    for e in catalogue:
        title = (e.get("title") or "").strip()
        sub = " ".join((e.get("subtext") or "").split())
        if not title:
            continue
        if e.get("kind") == "page":
            lines.append(f'- Page "{title}": {sub}')
        else:
            loc = (e.get("location") or "Settings").strip()
            lines.append(f'- Setting "{title}" (in {loc}): {sub}')
    body = "\n".join(lines)
    return (
        f"You are the built-in help assistant for {brand.PRODUCT_NAME}, a "
        "Windows push-to-talk dictation app: the user holds a hotkey, speaks, "
        "and the "
        "text is typed into whatever app is focused. Answer the user's question "
        "about how to use the app, briefly and in plain prose. No markdown, no "
        "bullet points, no numbered lists. Base the answer only on the settings "
        "and pages listed below. If it is not covered, say so plainly and point "
        "to the closest one. When a setting or page is relevant, name it exactly "
        "as written below so the app can offer a link to it. Two or three "
        "sentences is usually enough.\n\n"
        "Settings and pages:\n" + body
    )


def linked_entries(answer: str, catalogue, limit: int = 3):
    """Entries whose exact title appears in the AI answer, so the UI can offer a
    jump-straight-there chip. Longest titles first, so "Custom Vocabulary" wins
    over a stray "Custom"."""
    text = (answer or "").lower()
    hits = []
    for e in sorted(catalogue, key=lambda x: -len(x.get("title", ""))):
        title = (e.get("title") or "").strip()
        if len(title) >= 3 and title.lower() in text:
            if not any(title.lower() in h.get("title", "").lower()
                       and h is not e for h in hits):
                hits.append(e)
        if len(hits) >= limit:
            break
    return hits
