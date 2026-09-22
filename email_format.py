"""
Email layout: when the dictation is going into an email, lay it out as one.

    "Hi John, thanks for your email. I'll look at the quote and come back to
     you tomorrow. Kind regards, Ryan."

becomes

    Hi John,

    Thanks for your email. I'll look at the quote and come back to you tomorrow.

    Kind regards,
    Ryan

Runs when the dictation started in an email client (`is_email_app`):
classic or new Outlook, Windows Mail, Thunderbird, a browser tab or web-app
window whose title names Gmail or Outlook, or BrightLink's own inbox and
send-email modal. Everywhere else only `format_signoff` runs, which moves an
unmistakable close with a name after it ("Kind regards, Ryan") onto its own
lines and touches nothing else, so "Hi John, thanks" typed into Slack or
Teams stays one line.

Three pieces, each optional, each recognised by shape:

  * a GREETING at the very start ("Hi John", "Dear Mr Smith", "Morning all",
    "Hello,"), which gets its own line ending in a comma;
  * a SIGN-OFF at the very end ("Kind regards", "Many thanks", "Cheers"),
    which becomes its own paragraph, even run straight on from the body with
    no punctuation ("…say thank you kind regards Ryan") when the phrase is
    one nobody ends a sentence with;
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


# BrightLink's own mail. The CRM titles its tab "<page> | <brand>", and the
# brand half is the customer's profile name ("Inbox | BrightLink", "Inbox |
# FTC Safety"), so only the page half can be matched. The CRM writes these two
# page names while its mail panel or its send-email modal (Email tab) is open:
# Brightlink src/lib/pageTitle.ts, INBOX_TITLE and NEW_EMAIL_TITLE, pinned on
# that side by tests/page-title.test.tsx. Renaming either breaks this match.
_CRM_MAIL_TITLE = re.compile(r"(?:Inbox|New email) \| (?P<rest>.+)")


def _is_crm_mail_title(title: str) -> bool:
    m = _CRM_MAIL_TITLE.fullmatch(_ZERO_WIDTH.sub("", title or "").strip())
    if not m:
        return False
    segs = [s.strip() for s in _SEP_RE.split(m.group("rest")) if s.strip()]
    while segs and segs[-1].casefold() in _BROWSER_NAMES:
        segs.pop()
    # The brand, and at most an Edge profile name after it. Anything longer,
    # or a search engine, is a page ABOUT the inbox rather than the inbox.
    return (1 <= len(segs) <= 2 and "|" not in m.group("rest")
            and not any(_SEARCH_WORDS.search(s) for s in segs))


def is_email_app(exe: str, title: str) -> bool:
    """True when the window the dictation started in is an email client."""
    stem = _stem_of(exe or "")
    if stem in _MAIL_APPS:
        return True
    return stem in _BROWSERS and (_is_webmail_title(title)
                                  or _is_crm_mail_title(title))


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
    "thank you and kind regards", "thank you and best regards",
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

# Sign-offs that close the message even when spoken straight on from the body
# with no pause for the engine to punctuate: "…I just wanted to say thank you
# kind regards Ryan". Only phrases nobody uses inside a sentence. "Best
# wishes", "all the best", "sincerely" and bare "regards" are left out on
# purpose: "I wish you all the best", "I mean it sincerely" and "as regards
# John" are sentences that happen to end on them, and so is "end the email
# with kind regards Ryan", which is why "with kind regards" needs a pause.
_RUN_ON = {
    "many thanks and kind regards", "many thanks and best regards",
    "thank you and kind regards", "thank you and best regards",
    "thanks and kind regards", "thanks and best regards", "thanks and regards",
    "kindest regards", "warmest regards", "kind regards", "best regards",
    "warm regards", "yours sincerely", "yours faithfully",
}
# A word that makes a run-on sign-off the OBJECT of the sentence rather than
# its close: "give him my kind regards", "wanted to say thanks Ryan", and the
# instructions dictated to an assistant ("sign it off kind regards Ryan").
# The adjectives stop "sent with kind regards" splitting inside the phrase.
_GOVERNS = {
    "my", "your", "our", "his", "her", "their", "its", "it", "the", "a", "an",
    "and", "or", "of", "to", "for", "with", "by", "as", "in", "like", "is",
    "was", "be", "just", "off", "send", "sends", "sent", "sending", "give",
    "gives", "gave", "giving", "pass", "passes", "passed", "passing", "extend",
    "extends", "convey", "conveys", "offer", "offers", "say", "says", "said",
    "saying", "sign", "signs", "signed", "signing", "end", "ends", "ended",
    "ending", "close", "closes", "closed", "closing", "write", "writes",
    "wrote", "writing", "put", "use", "uses", "used", "using", "no", "some",
    "any", "these", "those", "very", "many", "all", "kind", "kindest", "best",
    "warm", "warmest",
}
# Outside an email only these, and only with a name after them, take their
# own lines: a "regards" close or a formal one with a signature is a letter
# ending wherever it is typed, while "thanks, John" in a chat is a sentence.
_ANYWHERE = {p for p in _STRONG if "regards" in p} | {
    "yours sincerely", "yours faithfully", "sincerely", "best wishes",
    "warm wishes", "with best wishes",
}


def _alt(phrases) -> str:
    return "|".join(p.replace(" ", r"\s+") for p in phrases)


# The lead is what separates the sign-off from the body: the start of the text,
# a sentence end, a comma, a line break, or (checked in _accept_signoff) plain
# whitespace after a word.
_SIGNOFF_RE = re.compile(
    r"(?P<lead>^\s*|(?<=[.!?])\s+|,\s+|[ \t]*\n\s*|(?<=\w)\s+)"
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


def _lead_kind(m, text: str) -> str:
    lead = m.group("lead")
    if "\n" in lead:
        return "newline"
    if lead.startswith(","):
        return "comma"
    if m.start() == 0:
        return "start"
    if text[m.start() - 1] in ".!?":
        return "sentence"
    return "bare"


def _prev_word(text: str, end: int) -> str:
    words = text[:end].split()
    return _bare(words[-1]) if words else ""


def _accept_signoff(m, text: str, addressee: str, sender_first: str,
                    anywhere: bool = False) -> bool:
    phrase = " ".join(m.group("phrase").lower().split())
    kind = _lead_kind(m, text)
    at_start = kind == "start"      # the sign-off is the whole body
    after_comma = kind == "comma"
    name = m.group("name") or ""
    first = _bare(name.split()[0]) if name else ""
    strong = phrase in _STRONG_SET

    if anywhere and not (name and phrase in _ANYWHERE):
        return False
    if kind == "bare":
        # Run straight on from the body: only an unmistakable close, or a
        # casual one followed by the sender's own name ("…see you then cheers
        # Ryan": nobody thanks themselves). The other formal closes ("all the
        # best", "with kind regards") need a pause even then: "I wish you all
        # the best Ryan" is a sentence.
        if _prev_word(text, m.start()) in _GOVERNS:
            return False
        if phrase not in _RUN_ON and not (
                not strong and first and first == sender_first):
            return False

    if name:
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


def _find_signoff(text: str, addressee: str, sender_first: str,
                  anywhere: bool = False):
    """The accepted sign-off match, trying each place one could start."""
    pos = 0
    while True:
        m = _SIGNOFF_RE.search(text, pos)
        if m is None:
            return None
        if _accept_signoff(m, text, addressee, sender_first, anywhere):
            return m
        pos = m.start() + 1


def _signoff_block(m) -> str:
    phrase = _cap_first(" ".join(m.group("phrase").split()))
    name = " ".join((m.group("name") or "").split())
    if name:
        return phrase + ",\n" + name
    bang = "!" in (m.group("p1") + m.group("p2"))
    return phrase + ("!" if bang else "")


def _close_body(body: str, m, text: str) -> str:
    # "…tomorrow, kind regards" / "…thank you kind regards": the comma or the
    # run-on was the break, so the body's last sentence gets its stop.
    if _lead_kind(m, text) in ("comma", "bare") and body and body[-1].isalnum():
        return body + "."
    return body


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
    m = _find_signoff(rest, addressee, _first_name(sender_name))
    signoff = _signoff_block(m) if m else None
    body_end = m.start() if m else len(rest)

    if greeting is None and signoff is None:
        return text

    body = rest[:body_end].strip()
    if m is not None:
        body = _close_body(body, m, rest)
    body = _cap_first(body)

    parts = [p for p in (greeting[0] if greeting else "", body,
                         signoff or "") if p]
    out = "\n\n".join(parts)
    if greeting and not body and signoff is None:
        out += "\n\n"   # just the greeting: leave the caret where the body goes
    return out


def format_signoff(text: str, sender_name: str = "") -> str:
    """Outside an email client: put an unmistakable letter close and the name
    after it on their own lines ("…thanks for this kind regards Ryan"). Only
    the _ANYWHERE phrases, and only with a name. The rest of the text,
    greeting included, is left exactly as spoken."""
    if not text or not text.strip():
        return text
    m = _find_signoff(text, "", _first_name(sender_name), anywhere=True)
    if m is None:
        return text
    body = _close_body(text[:m.start()].rstrip(), m, text)
    block = _signoff_block(m)
    return body + "\n\n" + block if body.strip() else block
