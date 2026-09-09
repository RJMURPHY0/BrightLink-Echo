"""
Spoken symbol commands — convert dictated character names into the characters.

    "slash settings"                    -> "/settings"
    "ryan underscore murphy"            -> "ryan_murphy"
    "hashtag safety first"              -> "#safety first"
    "open bracket see attached close bracket" -> "(see attached)"
    "ryan dot murphy at ftc dash ss dot com"  -> "ryan.murphy@ftc-ss.com"
    "fifty four percent"                -> "54%"

Deliberately conservative: a symbol NAME is only swapped for its symbol when
that name is almost never dictated as literal prose. Plain punctuation words
("comma", "full stop", "period", "question mark", "new line") are NOT converted
— Parakeet already punctuates from prosody, and those words appear in ordinary
English far too often to rewrite safely ("over a period of time", "a question
mark over the plan", "a new line of products").

"dot", "dash" and "at" are the same kind of everyday word, so they are only
converted inside a run that has the SHAPE of an address (see _rewrite_address):
resolved right-to-left from a known TLD or file extension. "look at the report"
has no such shape and is left exactly as spoken.

Enabled via Config.spoken_punctuation (default on).
"""

import re

_S = r"[ \t]*"  # horizontal space only — never swallow newlines

# ── Spoken addresses: emails, domains, filenames ─────────────────────────────
#
# The separators are ordinary English words, so the rewrite is driven entirely
# by SHAPE. A run of alternating word/separator tokens is scanned RIGHT to LEFT
# starting from a known top-level domain or file extension; the chain extends
# left over "." "-" "_" and, at most once, over "@". Anything to the left of
# that chain is prose and is left untouched.

# Everyday English words are deliberately absent ("it", "in", "us", "be", "at",
# "no", "so") even where they are real top-level domains: "put a dot in the box"
# must never become "a.in". The single-character-label rule below is the second
# guard on the same class of mistake.
_TLDS = frozenset("""
com co uk org net io ai dev app gov edu info biz me tv eu ie de fr es nl ch se
dk fi pl pt cz ca au nz jp cn br za shop site online store tech cloud email
live news blog xyz agency group ltd plc solutions systems
""".split())

_EXTS = frozenset("""
pdf doc docx xls xlsx ppt pptx csv txt md rtf png jpg jpeg gif svg webp zip rar
py js ts jsx tsx html htm css json yaml yml xml sql sh bat exe msi dll log
mp3 mp4 wav mov avi psd ai eps
""".split())

# Separators, as spoken. Longest first so "at sign" wins over "at".
_SEP_ALT = r"(?:at\s+sign|at\s+symbol|underscore|hyphen|dash|dot|at)"
_SEP_SYM = {
    "dot": ".",
    "dash": "-",
    "hyphen": "-",
    "underscore": "_",
    "at": "@",
    "atsign": "@",
    "atsymbol": "@",
}
# Separators an address label may be built from (everything except "@").
_LABEL_SEPS = frozenset(".-_")

# A token may already carry punctuation ("ftc-ss") because an earlier rule, or
# the engine itself, produced it.
_ADDR_TOKEN = r"[A-Za-z0-9]+(?:[-._][A-Za-z0-9]+)*"
_ADDR_RUN = re.compile(
    rf"(?<![\w@-])({_ADDR_TOKEN}(?:\s+{_SEP_ALT}\s+{_ADDR_TOKEN})+)(?![\w@-])",
    re.IGNORECASE,
)
_SPLIT_SEP = re.compile(rf"\s+({_SEP_ALT})\s+", re.IGNORECASE)

# Words that routinely sit in front of a prose "at" ("email me at …", "look at
# …"). When the whole local part of a would-be email is a single one of these,
# the "at" is prose and the address starts after it.
_PROSE_BEFORE_AT = frozenset("""
a an and are as at back be been being but by call called can check contact did
do does done email emailed find for found get go going got had has have he her
here him his how i in is it its just look looked looking made make me meet met
my no not now of off on one or order our out over post posted put see seen send
sent she so staying start stay stop that the their them then there these they
this those to try trying up us use used very was we went were what when where
which who why will with work working would you your
""".split())


def _rewrite_address(m: "re.Match") -> str:
    """Collapse the address-shaped tail of a spoken run; leave the rest alone."""
    raw = m.group(1)
    parts = _SPLIT_SEP.split(raw)
    words = parts[0::2]
    seps = [_SEP_SYM.get(p.lower().replace(" ", ""), "") for p in parts[1::2]]
    if not seps or "" in seps:
        return raw

    # Walk left from the end. The chain must terminate in "<label>.<tld|ext>".
    n = len(words)
    if seps[-1] != "." or words[-1].lower() not in (_TLDS | _EXTS):
        return raw

    i = n - 1                       # index of the leftmost word in the chain
    while i > 0 and seps[i - 1] in _LABEL_SEPS:
        i -= 1
    # Optionally one "@", and the local part left of it (labels only).
    if i > 0 and seps[i - 1] == "@":
        at_i = i - 1
        j = at_i
        while j > 0 and seps[j - 1] in _LABEL_SEPS:
            j -= 1
        # A single-word local part that is an everyday English word means the
        # "at" was prose ("looked at report dot pdf"), not an address.
        if not (j == at_i and words[j].lower() in _PROSE_BEFORE_AT):
            i = j

    if i == n - 1:
        return raw                  # nothing but the TLD — not an address
    # A one-character leading label is prose, not a domain ("put a dot in the
    # box"). An email is exempt: its local part is free-form.
    if "@" not in seps[i:n - 1] and len(words[i]) < 2:
        return raw

    head = ""
    if i > 0:
        # Prose in front of the address, rebuilt exactly as spoken.
        head = words[0]
        for k in range(1, i):
            head += f" {parts[2 * k - 1]} {words[k]}"
        head += f" {parts[2 * i - 1]} "

    addr = words[i]
    for k in range(i + 1, n):
        addr += seps[k - 1] + words[k]
    return head + addr.lower()


# ── Spoken numbers, but only where a symbol depends on them ──────────────────

_NUM_SMALL = {
    "zero": 0, "oh": 0, "nought": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUM_SCALE = {"hundred": 100, "thousand": 1000, "million": 1000000}
_NUM_WORD = "|".join(sorted(list(_NUM_SMALL) + list(_NUM_SCALE), key=len,
                            reverse=True))
_NUM_RUN = rf"(?:{_NUM_WORD})(?:[\s-]+(?:and[\s-]+)?(?:{_NUM_WORD}))*"


def _words_to_number(phrase: str):
    """'fifty four' -> 54, 'one hundred and five' -> 105. None if unparseable."""
    total = 0
    current = 0
    seen = False
    for tok in re.split(r"[\s-]+", phrase.strip().lower()):
        if not tok or tok == "and":
            continue
        if tok in _NUM_SMALL:
            current += _NUM_SMALL[tok]
            seen = True
        elif tok in _NUM_SCALE:
            scale = _NUM_SCALE[tok]
            if scale == 100:
                current = (current or 1) * 100
            else:
                total += (current or 1) * scale
                current = 0
            seen = True
        else:
            return None
    return (total + current) if seen else None


_PERCENT_WORDS = re.compile(rf"\b({_NUM_RUN})[\s-]+per\s?cent\b", re.IGNORECASE)
_PERCENT_DIGITS = re.compile(r"(\d)[\s-]*per\s?cent\b", re.IGNORECASE)
_CURRENCY_WORDS = re.compile(rf"([$£€])\s*({_NUM_RUN})\b", re.IGNORECASE)


def _sub_percent_words(m: "re.Match") -> str:
    phrase = m.group(1).strip().lower()
    # "a hundred percent" is prose — digitising the bare scale word gives the
    # nonsense "a 100%". A scale only counts with a multiplier in front of it.
    if phrase in _NUM_SCALE:
        return m.group(0)
    n = _words_to_number(phrase)
    return f"{n}%" if n is not None else m.group(0)


def _sub_currency_words(m: "re.Match") -> str:
    n = _words_to_number(m.group(2))
    return f"{m.group(1)}{n}" if n is not None else m.group(0)


# ── Symbol names ─────────────────────────────────────────────────────────────
# Each entry: (spoken-name regex, symbol). Grouped by how the symbol binds to
# its neighbours. Order inside a group matters where names overlap
# ("forward slash" before "slash").
_JOIN_BOTH = [   # swallow space on both sides: "foo slash bar" -> "foo/bar"
    ("forward slash", "/"),
    ("back ?slash", "\\"),
    ("slash", "/"),
    ("underscore", "_"),
    ("hyphen", "-"),
    ("at symbol", "@"),
    ("apostrophe", "'"),
]
_JOIN_RIGHT = [  # swallow the following space: "hashtag safety" -> "#safety"
    ("hash ?tag", "#"),
    ("dollar sign", "$"),
    ("pound sign", "£"),
    ("euro sign", "€"),
    ("tilde", "~"),
    ("open square bracket", "["),
    ("open curly bracket", "{"),
    ("open brace", "{"),
    ("open bracket", "("),
    ("open paren(?:thesis)?", "("),
    ("open(?:ing)? (?:double )?quotes?", '"'),
    ("begin quotes?", '"'),
    ("open(?:ing)? single quote", "'"),
]
_JOIN_LEFT = [   # swallow the preceding space: "50 percent sign" -> "50%"
    ("percent sign", "%"),
    ("semicolon", ";"),
    ("close square bracket", "]"),
    ("close curly bracket", "}"),
    ("close brace", "}"),
    ("close bracket", ")"),
    ("close paren(?:thesis)?", ")"),
    ("clos(?:e|ing) (?:double )?quotes?", '"'),
    ("end quotes?", '"'),
    ("un ?quote", '"'),
    ("clos(?:e|ing) single quote", "'"),
    ("exclamation (?:mark|point)", "!"),
]
_SPACED = [      # plain word swap, spacing untouched: "A ampersand B" -> "A & B"
    ("ampersand", "&"),
    ("asterisk", "*"),
    ("plus sign", "+"),
    ("equals? sign", "="),
    ("pipe symbol", "|"),
    ("vertical bar", "|"),
    ("caret", "^"),
    ("less ?than sign", "<"),
    ("greater ?than sign", ">"),
    ("back ?tick", "`"),
    # NB "quotation mark(s)" is deliberately absent. It reads as prose far more
    # often than as a command — it turned a real stored dictation ("research of
    # the other things like quotation marks, dollar signs") into a stray quote.
    # The unambiguous open/close forms above cover the actual instruction.
]

_RULES: list[tuple[re.Pattern, str]] = (
    [(re.compile(rf"{_S}\b(?:{p})\b{_S}", re.IGNORECASE), s) for p, s in _JOIN_BOTH]
    + [(re.compile(rf"\b(?:{p})\b{_S}", re.IGNORECASE), s) for p, s in _JOIN_RIGHT]
    + [(re.compile(rf"{_S}\b(?:{p})\b", re.IGNORECASE), s) for p, s in _JOIN_LEFT]
    + [(re.compile(rf"\b(?:{p})\b", re.IGNORECASE), s) for p, s in _SPACED]
)


def apply_spoken_commands(text: str) -> str:
    """Replace spoken symbol names with the symbols themselves."""
    if not text:
        return text
    out = text
    # Addresses first: they own "dot"/"dash"/"at", and their tokens may already
    # contain the punctuation a later rule would otherwise have to re-parse.
    out = _ADDR_RUN.sub(_rewrite_address, out)
    for pat, sym in _RULES:
        # Function replacement — literal symbol, immune to "\\"/"$" escaping.
        out = pat.sub(lambda m, s=sym: s, out)
    # Numbers last: "dollar sign fifty" has to become "$fifty" first.
    out = _PERCENT_WORDS.sub(_sub_percent_words, out)
    out = _PERCENT_DIGITS.sub(r"\1%", out)
    out = _CURRENCY_WORDS.sub(_sub_currency_words, out)
    if out != text:
        out = re.sub(r" {2,}", " ", out)
        out = re.sub(r" +([.,!?;:])", r"\1", out)
        out = out.strip()
    return out
