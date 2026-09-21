"""
Email layout: when the dictation is going into an email, lay it out as one.

    "Hi John, thanks for your email. I'll look at the quote and come back to
     you tomorrow. Kind regards, Ryan."

becomes

    Hi John,

    Thanks for your email. I'll look at the quote and come back to you tomorrow.

    Kind regards,
    Ryan

Runs ONLY when the dictation started in an email client (`is_email_app`):
classic or new Outlook, Windows Mail, Thunderbird, or a browser tab or web-app
window whose title names Gmail or Outlook. Everywhere else the text is left
alone, so "Hi John, thanks" typed into Slack or Teams stays one line.

Three pieces, each optional, each recognised by shape:

  * a GREETING at the very start ("Hi John", "Dear Mr Smith", "Morning all",
    "Hello,"), which gets its own line ending in a comma;
  * a SIGN-OFF at the very end ("Kind regards", "Many thanks", "Cheers"),
    which becomes its own paragraph;
  * the NAME after the sign-off, which goes on the line below it.

Words are never added or removed. The only edits are line breaks, the
punctuation beside them and the capital that now starts the body. With no
greeting and no sign-off the text comes back byte-identical, which keeps the
body-only presses (most of an email) exactly as spoken.

"Thanks John" is the one real ambiguity: John may be the sender signing off or
the recipient being thanked. A bare "thanks"-type phrase only takes the name as
a signature when it matches the signed-in user's first name, or, with no name
known, when it is not the greeting's addressee. "Kind regards, John" is always
a signature: nobody thanks the recipient with "kind regards".

Applied once, on the whole utterance, at app.py's single post-processing point
(same place and same Live Typing exemption as list_format). Enabled via
Config.email_format, default on.
"""

import re

from app_icons import _BROWSERS, _stem_of

# ── Where it runs ────────────────────────────────────────────────────────────

# Desktop mail clients, by exe stem. Every window of these is email (compose,
# reply, reading pane), and a greeting-shaped dictation into the calendar or
# search box is rare enough not to design around.
_MAIL_APPS = {
    "outlook",      # classic Outlook
    "olk",          # new Outlook for Windows
    "hxoutlook",    # Windows Mail
    "thunderbird",
}

# A webmail tab is recognised by the title the service itself sets, which
# names it as a whole title SEGMENT near the end: "Inbox (3) - me@x.com -
# Gmail", "Mail - Ryan Murphy - Outlook". A page that merely mentions the
# service never has that shape, so all of these stay plain text:
#   "How to fix Outlook - Google Search"   (not a segment of its own)
#   "Create filters - Gmail Help"          (segment is not exactly the name)
#   "sign in - Gmail - Google Search"      (the query; a search page follows)
# Only an Edge profile name ("- Personal") may sit between the service and
# the browser's own name. Edge also appends "and 3 more pages" to the title.
_DASHES = "-" + "".join(chr(c) for c in range(0x2010, 0x2016))
_SEP_RE = re.compile(
    r"\s+[" + re.escape(_DASHES) + "|" + chr(0x2022) + chr(0x00b7) + r"]\s+")
_ZERO_WIDTH = re.compile("[" + chr(0x200b) + "-" + chr(0x200d)
                         + chr(0xfeff) + "]")
_WEBMAIL_SEGMENT = re.compile(
    r"(?:Gmail|Outlook)(?:\s+and\s+\d+\s+more\s+pages?)?")
_BROWSER_NAMES = {
    "google chrome", "google chrome for testing", "chrome", "microsoft edge",
    "mozilla firefox", "firefox", "brave", "opera", "opera gx", "vivaldi",
    "arc", "zen", "zen browser",
}
_SEARCH_WORDS = re.compile(
    r"(?i)\b(?:search|google|bing|duckduckgo|yahoo|ecosia)\b")


def _is_webmail_title(title: str) -> bool:
    segs = [s.strip() for s in _SEP_RE.split(_ZERO_WIDTH.sub("", title or ""))
            if s.strip()]
    while segs and segs[-1].casefold() in _BROWSER_NAMES:
        segs.pop()
    # Never the first segment: a real inbox title always has the folder or
    # message before the service name.
    for i in range(len(segs) - 1, 0, -1):
        if _WEBMAIL_SEGMENT.fullmatch(segs[i]):
            after = segs[i + 1:]
            return len(after) <= 1 and not any(
                _SEARCH_WORDS.search(a) for a in after)
    return False


def is_email_app(exe: str, title: str) -> bool:
    """True when the window the dictation started in is an email client."""
    stem = _stem_of(exe or "")
    if stem in _MAIL_APPS:
        return True
    return stem in _BROWSERS and _is_webmail_title(title)


# ── Shapes ───────────────────────────────────────────────────────────────────

_NAME = r"[A-Z][\w'\u2019\-]*"
_HONORIFIC = r"(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof)\.?"
_PERSON = rf"(?:{_HONORIFIC}\s+)?{_NAME}(?:\s+{_NAME}){{0,2}}"
_GROUP_WORDS = ("all", "everyone", "everybody", "team", "guys", "folks",
                "there", "both")
_GROUP = (r"(?i:you\s+all|all\s+of\s+you|"
          + "|".join(_GROUP_WORDS) + r")\b")
_ADDRESSEE = (rf"(?:{_GROUP}|(?i:sir\s+or\s+madam|sir/madam)|"
              rf"{_PERSON}(?:\s+(?:and|&)\s+{_PERSON})?)")
_GREETING_WORD = (r"(?i:good\s+(?:morning|afternoon|evening)|hiya|hi|hello|"
                  r"hey|dear|morning|afternoon|evening)")

_FIXED_ADDRESSEE = re.compile(rf"{_GROUP}|(?i:sir\s+or\s+madam|sir/madam)")

# The greeting word, then optionally an addressee (a comma may sit between:
# "Good morning, John"). Whether a greeting really ended is decided in code,
# because the capitalised run after it can hold a sentence starter ("Hi John
# I wanted…") that has to be trimmed off first.
_GREETING_RE = re.compile(
    rf"\s*(?P<greet>{_GREETING_WORD})\b"
    rf"(?:\s*,?\s+(?P<addr>{_ADDRESSEE}))?")

# Capitalised words that start a sentence rather than name a person. They cut
# an addressee short ("Hi John Thanks for…" -> "Hi John") and are never taken
# as a signature name.
_NOT_NAMES = {
    "i", "i'm", "im", "i've", "i'll", "i'd", "thanks", "thank", "just", "hope",
    "hoping", "please", "can", "could", "would", "will", "is", "are", "was",
    "do", "did", "does", "have", "has", "had", "so", "we", "we're", "we've",
    "we'll", "you", "your", "you're", "it", "it's", "its", "this", "that",
    "these", "those", "the", "a", "an", "sorry", "apologies", "great", "good",
    "quick", "following", "further", "as", "re", "regarding", "here", "there's",
    "yes", "no", "ok", "okay", "sure", "let", "let's", "my", "our", "what",
    "when", "where", "why", "how", "who", "any", "happy", "welcome",
    "congratulations", "congrats", "unfortunately", "hopefully", "also",
    "attached", "kind", "best", "many", "cheers", "regards", "not", "if",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december", "today",
    "tomorrow", "yesterday",
}
_JOINERS = {"and", "&"}

# Sign-offs that only ever close an email. Longest first: the regex takes the
# first alternative that fits.
_STRONG = (
    "many thanks and kind regards", "many thanks and best regards",
    "thanks and kind regards", "thanks and best regards", "thanks and regards",
    "with kind regards", "with best wishes", "with many thanks",
    "kindest regards", "warmest regards", "kind regards", "best regards",
    "warm regards", "many regards", "regards", "best wishes", "warm wishes",
    "all the best", "yours sincerely", "yours faithfully", "yours truly",
    "sincerely", "many thanks", "with thanks",
)
# Sign-offs that are also ordinary words at the end of a message ("let me
# know, thanks"), so they carry the tighter rules in _accept_signoff.
_WEAK = (
    "thank you very much", "thank you so much", "thanks very much",
    "thanks so much", "thanks in advance", "thanks again", "thanks a lot",
    "thank you", "thanks", "cheers", "speak soon", "talk soon", "take care",
    "best",
)
_STRONG_SET = set(_STRONG)
_NEEDS_NAME = {"best"}           # "Best." alone is not a sign-off


def _alt(phrases) -> str:
    return "|".join(p.replace(" ", r"\s+") for p in phrases)


_SIGNOFF_RE = re.compile(
    r"(?P<lead>^\s*|(?<=[.!?])\s+|,\s+|[ \t]*\n\s*)"
    rf"(?P<phrase>(?i:{_alt(_STRONG)}|{_alt(_WEAK)}))\b"
    r"(?P<p1>\s*[,.!]?)"
    rf"(?:\s+(?P<name>{_NAME}(?:\s+{_NAME}){{0,3}}))?"
    r"(?P<p2>\s*[.!]?)\s*$")


def _bare(word: str) -> str:
    return word.strip(".,!?;:").replace("\u2019", "'").lower()


def _cap_first(s: str) -> str:
    for i, ch in enumerate(s):
        if ch.isalpha():
            return s[:i] + ch.upper() + s[i + 1:] if ch.islower() else s
        if not ch.isspace() and ch not in "\"'(\u2018\u201c":
            return s
    return s


# ── Greeting ─────────────────────────────────────────────────────────────────

def _split_greeting(text: str):
    """Return (greeting_line, addressee, body_start) or None."""
    m = _GREETING_RE.match(text)
    if not m:
        return None
    greet = m.group("greet")
    end = m.end("greet")
    addr = ""
    if m.group("addr"):
        raw = m.group("addr")
        words = list(re.finditer(r"\S+", raw))
        kept = len(words)
        if not _FIXED_ADDRESSEE.fullmatch(raw):
            # A capitalised run can carry the body's first word with it.
            kept = 0
            for i, w in enumerate(words):
                if _bare(w.group()) in _NOT_NAMES:
                    break
                kept = i + 1
            while kept and _bare(words[kept - 1].group()) in _JOINERS:
                kept -= 1
        if kept:
            end = m.start("addr") + words[kept - 1].end()
            addr = raw[:words[kept - 1].end()]
    if greet.lower() == "dear" and not addr:
        return None
    pm = re.match(r"\s*([,.!:;])(?=\s|$)", text[end:])
    if pm:
        punct, body_start = pm.group(1), end + pm.end()
    elif not text[end:].strip():
        punct, body_start = "", len(text)
    elif addr:
        punct, body_start = "", end
    else:
        # "Morning meeting moved to three": a greeting word, but nothing
        # marks it as one.
        return None
    line = _cap_first(text[:end].strip()) + ("!" if punct == "!" else ",")
    return line, addr, body_start


# ── Sign-off ─────────────────────────────────────────────────────────────────

def _first_name(full: str) -> str:
    parts = (full or "").split()
    return _bare(parts[0]) if parts else ""


def _accept_signoff(m, addressee: str, sender_first: str) -> bool:
    phrase = " ".join(m.group("phrase").lower().split())
    lead = m.group("lead")
    at_start = m.start() == 0      # the sign-off is the whole body
    after_comma = lead.startswith(",")
    name = m.group("name") or ""
    strong = phrase in _STRONG_SET

    if name:
        first = _bare(name.split()[0])
        if first in _NOT_NAMES or first in _GROUP_WORDS:
            return False
        if strong:
            return True
        # "thanks"-type phrase + a name: signature or the recipient?
        if sender_first:
            return first == sender_first
        if at_start or after_comma:
            return False
        return first != _first_name(addressee)
    if phrase in _NEEDS_NAME:
        return False
    if after_comma and not strong:
        return False            # "let me know, thanks." is a sentence
    if at_start and not strong:
        return False            # a whole reply of "Thanks." stays as it is
    return True


# ── Public ───────────────────────────────────────────────────────────────────

def format_email(text: str, sender_name: str = "") -> str:
    """Lay out a dictated email. Unchanged when no greeting or sign-off."""
    if not text or not text.strip():
        return text
    greeting = _split_greeting(text)
    body_start = greeting[2] if greeting else 0
    addressee = greeting[1] if greeting else ""

    # Searched in the body alone, so a sign-off straight after the greeting
    # ("Hi John, kind regards, Ryan") still finds its start-of-body lead.
    rest = text[body_start:]
    signoff = None
    body_end = len(rest)
    m = _SIGNOFF_RE.search(rest)
    if m and _accept_signoff(m, addressee, _first_name(sender_name)):
        phrase = _cap_first(" ".join(m.group("phrase").split()))
        name = " ".join((m.group("name") or "").split())
        if name:
            signoff = phrase + ",\n" + name
        else:
            bang = "!" in (m.group("p1") + m.group("p2"))
            signoff = phrase + ("!" if bang else "")
        body_end = m.start()

    if greeting is None and signoff is None:
        return text

    body = rest[:body_end].strip()
    if signoff is not None and m.group("lead").startswith(",") \
            and body and body[-1].isalnum():
        body += "."     # "…tomorrow, kind regards": the comma was the break
    body = _cap_first(body)

    parts = [p for p in (greeting[0] if greeting else "", body,
                         signoff or "") if p]
    out = "\n\n".join(parts)
    if greeting and not body and signoff is None:
        out += "\n\n"   # just the greeting: leave the caret where the body goes
    return out
