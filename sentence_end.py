"""
Terminal punctuation — decide whether a finished dictation gets a full stop.

The old behaviour was a boolean: stamp a period on every utterance that did not
already end in one, or stamp none at all. Neither is right. Dictation is often a
FRAGMENT dropped into the middle of something the user is already typing ("and
then the invoice", "ryan.murphy@ftc-ss.com", "about half"), where a period has
to be deleted by hand; and it is just as often a finished sentence, where the
period is exactly what is wanted.

`smart` (the default) adds the stop only when the utterance reads as finished:

  * it is not already terminated, and does not end on a comma (a comma IS the
    user saying "I have not finished"),
  * the last word is not a hanging function word — "and", "to", "the", "with"
    are how a sentence-in-progress ends,
  * it is at least three words (one- and two-word dictations are overwhelmingly
    fragments: "yes", "one moment", "about half"),
  * the last token is not an address, URL or filename, where a trailing period
    reads as part of the address and gets copied with it,
  * it does not end on an opening bracket or quote.

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


def already_terminated(text: str) -> bool:
    """True when the text already ends a sentence (closing quotes allowed)."""
    t = (text or "").rstrip()
    while t and t[-1] in _CLOSERS:
        t = t[:-1]
    return bool(t) and t[-1] in _TERMINAL


def looks_finished(text: str) -> bool:
    """True when the utterance reads as a complete sentence — see module docs.

    Called only when the text is not already terminated."""
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
    """Strip a trailing pause artefact, then add a full stop if the mode says so.

    A trailing comma/semicolon/colon is always removed — it is a pause the
    engine stamped, never something the user asked for — and is NEVER stacked
    with a period ("then,." shipped once already).
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
    if mode == "never":
        return t
    if already_terminated(t):
        return t
    if mode == "always" or looks_finished(t):
        t += "."
    return t
