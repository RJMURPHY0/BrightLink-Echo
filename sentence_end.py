"""
Terminal punctuation: decide whether a finished dictation ends in a full stop.

The old behaviour was a boolean: stamp a period on every utterance that did not
already end in one, or stamp none at all. Neither is right. Dictation is often a
FRAGMENT dropped into the middle of something the user is already typing ("and
then the invoice", "ryan.murphy@ftc-ss.com", "about half"), where a period has
to be deleted by hand; and it is just as often a finished sentence, where the
period is exactly what is wanted.

`smart` (the default) ends the dictation with a stop only when the utterance
reads as finished:

  * it does not end on a comma (a comma IS the user saying "I have not
    finished"),
  * the last word is not a hanging function word — "and", "to", "the", "with"
    are how a sentence-in-progress ends,
  * it is at least three words (one- and two-word dictations are overwhelmingly
    fragments: "yes", "one moment", "about half"),
  * the last token is not an address, URL or filename, where a trailing period
    reads as part of the address and gets copied with it,
  * it does not end on an opening bracket or quote.

The decision covers the stop the speech engine wrote ITSELF, not just whether to
add one. Parakeet ends every utterance with a full stop, so a rule that only
chose whether to add a missing one never ran on its output: 172 of 200 real
dictations still ended in a stop under "smart" and under "never" alike (fixed in
v1.6.79). `smart` now judges an existing stop by the same test it uses to add
one, and `never` removes it. "?" and "!" are never touched: they are the
engine hearing a question or an exclamation, not a full stop. Neither is the
dot that belongs to an abbreviation ("7 p.m.", "etc.").

The bias is deliberately towards LEAVING IT OPEN. A missing full stop costs one
keystroke; an unwanted one has to be found and deleted mid-sentence, which is
the complaint this exists to fix.

Modes: "smart" (default) | "always" (the pre-1.6.75 behaviour) | "never".
"""

import re

MODES = ("smart", "always", "never")
DEFAULT_MODE = "smart"

_TERMINAL = ".!?…"
# A stop hiding behind a closing quote or bracket still terminates the sentence.
_CLOSERS = "\"'”’)]}»"

# Ending on one of these is the user mid-sentence. Kept tight and
# high-precision: every word here is one that rarely ends an English sentence.
# Words that routinely DO were measured against the 200 real transcripts in
# history.json and left out — the demonstrative pronouns ("I did that", "look at
# this"), the do-verbs ("all of the phases you need to do", "it's done"), "am"
# (which is a clock reading as often as a verb: "till 7 am") and "really" ("not
# really"). Blocking those cost a full stop on genuinely finished sentences.
_HANGING = frozenset("""
a an the and or nor but so because although though while whilst if unless until
whether since as than which who whom whose when where how
to of in on at by for with without from into onto upon over under between among
across during about against toward towards through per via plus versus
is are was were be been being have has had having
will would shall should can could may might must
my your our their his her its every each either neither both
some any another other such more most less least very rather
""".split())

# A token nobody wants a period welded onto: an email, a URL, a filename, a
# path, or a bare number ending in a decimal point.
_ADDRESSY = re.compile(
    r"(?:^|\S)@\S|^\w+://|^www\.|\.[A-Za-z]{2,6}$|[\\/]", re.IGNORECASE)

# A final "." that belongs to the WORD, not the sentence. Removing it leaves a
# broken abbreviation ("7 p.m", "the U.S"), so it is never treated as a stop.
_DOTTED_ABBREV = re.compile(r"^(?:[A-Za-z]\.){2,}$")
_ABBREV_WORDS = frozenset(
    "etc vs inc ltd co jr sr approx dept".split())


def already_terminated(text: str) -> bool:
    """True when the text already ends a sentence (closing quotes allowed)."""
    t = (text or "").rstrip()
    while t and t[-1] in _CLOSERS:
        t = t[:-1]
    return bool(t) and t[-1] in _TERMINAL


def _split_closers(t: str) -> tuple[str, str]:
    """(body, closers): trailing closing quotes/brackets peeled off the end."""
    i = len(t)
    while i > 0 and t[i - 1] in _CLOSERS:
        i -= 1
    return t[:i], t[i:]


def ends_with_full_stop(text: str) -> bool:
    """True when the text ends in a single sentence-final full stop. Not an
    ellipsis, not "?" or "!", and not the dot of an abbreviation."""
    body, _closers = _split_closers((text or "").rstrip())
    if not body.endswith(".") or body.endswith(".."):
        return False
    words = body.split()
    if not words:
        return False
    last = words[-1].lstrip("\"'“‘([{«")
    if _DOTTED_ABBREV.match(last) or last[:-1].lower() in _ABBREV_WORDS:
        return False
    return True


def strip_full_stop(text: str) -> str:
    """Remove the sentence-final full stop, keeping any closing quote or bracket
    after it ('He said "no."' -> 'He said "no"'). Anything that is not a plain
    full stop (see ends_with_full_stop) is returned unchanged, and so is a text
    that would be left empty."""
    t = (text or "").rstrip()
    if not ends_with_full_stop(t):
        return t
    body, closers = _split_closers(t)
    bare = body[:-1].rstrip()
    return (bare + closers) if bare else t


def looks_finished(text: str) -> bool:
    """True when the utterance reads as a complete sentence — see module docs.

    Judges the words, so pass the text WITHOUT its terminal full stop."""
    t = (text or "").strip()
    if not t:
        return False
    if t[-1] in ",;:-–—([{<":
        return False                    # explicitly still going
    if t[-1] in _CLOSERS:
        return True                     # "he said 'no'" — a closed quote ends it
    words = t.split()
    if len(words) < 3:
        return False
    last = words[-1]
    if _ADDRESSY.search(last):
        return False
    bare = last.strip("\"'”’)]}»").lower()
    if bare in _HANGING:
        return False
    return True


def apply(text: str, mode: str = DEFAULT_MODE) -> str:
    """Strip a trailing pause artefact, then settle the terminal full stop.

    A trailing comma/semicolon/colon is always removed — it is a pause the
    engine stamped, never something the user asked for — and is NEVER stacked
    with a period ("then,." shipped once already).

    "always" closes the sentence. "never" removes a full stop the engine wrote.
    "smart" keeps or adds a stop only when the words read as finished, and
    removes the engine's own stop when they do not.
    """
    t = (text or "").strip()
    if not t:
        return t
    if mode not in MODES:
        mode = DEFAULT_MODE
    if t[-1] in ",;:":
        t = t[:-1].rstrip()
        if not t:
            return t
        # A comma is the user mid-sentence: strip it, but do not then close the
        # sentence they were still building.
        if mode == "smart":
            return t
    if mode == "always":
        return t if already_terminated(t) else t + "."
    if mode == "never":
        return strip_full_stop(t)
    # smart
    if ends_with_full_stop(t):
        bare = strip_full_stop(t)
        return t if looks_finished(bare) else bare
    if already_terminated(t):
        return t                        # "?", "!", "…" or an abbreviation dot
    return t + "." if looks_finished(t) else t


def match_ending(candidate: str, reference: str) -> str:
    """Give *candidate* (a corrected copy of *reference*) the same full-stop
    ending as the text that was actually inserted.

    The AI correction pass likes to close sentences, so without this accepting
    its upgrade put back the stop the Sentence Endings setting had just removed.
    Only the full stop is reconciled: a "?" or "!" the correction chose is left
    alone, and so is a stop the user dictated deliberately (it is in the
    reference too)."""
    c = (candidate or "").rstrip()
    r = (reference or "").rstrip()
    if not c or not r:
        return candidate
    if ends_with_full_stop(c) and not already_terminated(r):
        return strip_full_stop(c)
    if ends_with_full_stop(r) and not already_terminated(c) \
            and c[-1] not in ",;:":
        return c + "."
    return candidate
