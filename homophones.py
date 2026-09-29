"""
Sound-alike words picked from the rest of the sentence ("Revenue one this
quarter" -> "Revenue won this quarter").

An ASR engine hears the SOUND of a word correctly and then has to pick a
spelling. For a true homophone the audio carries no information about which
one was meant, so the engine falls back on its language-model prior, and that
prior is often wrong for dictation: "one" is far commoner than "won" in general
text. Measured on the real clip that was reported (2026-09-29): Parakeet wrote
"Revenue One this quarter" and whisper small.en "Revenue one this quarter".
The surrounding words settle it, which is what a person reading the sentence
does: a sales noun before it and a time phrase after it make it the verb.

Runs once over the assembled dictation at app.py's single post-processing
point, right after the whole-text destutter and before spoken commands, so the
injected text, the popup, history and every later pass all see the same words.
Local, pure regex, well under a millisecond: nothing here waits on a network or
a model, because stop-to-text latency is not traded for accuracy in this app.

This REWRITES words the user said, so it is deliberately timid:

  * Every rule is one confusable pair in one narrow shape, and it needs
    evidence on BOTH sides of the word: a left context that makes one spelling
    grammatical and a right context that rules the other out. One-sided
    evidence is never enough ("I have one" is a count).
  * The contexts are written against the ways each shape is legitimately used
    ("had one the other day", "phase one this quarter", "see you later then",
    "the plan is to close", "all right the report is done"), and those are
    pinned as must-not-fire cases in tests/test_homophones.py.
  * Only spaces may sit between the words of a shape. A comma, a full stop or
    a line break is the speaker's own boundary and ends the match.
  * A rule that could be reading an enumeration ("two deals one this week and
    one next") stands down when a number comes before it or another
    "one"/"another"/"other" follows in the same sentence.

The safe direction is to UNDER-correct: a missed homophone is one wrong
spelling that ✨ Fix All and the LLM context fix can still repair; a wrong
correction changes what the user said.
"""

import re
from typing import Callable, List, NamedTuple, Optional, Pattern

# Word edges. A word may not continue into letters, digits, apostrophes or a
# hyphen ("won't", "one-off"), and may not follow a path, handle or file-name
# character ("/one", "#one", "file.one"), which is never speech.
_B = r"(?<![\w'’/@#.\\-])"
_E = r"(?![\w'’-])"
# Only spaces or tabs between the words of a shape.
_S = r"[ \t]+"
# End of the clause: closing punctuation or the end of the text.
_END = r"[ \t]*(?:[.!?,;:]|$)"


def _alt(words: str) -> str:
    """Whitespace-separated words -> a non-capturing alternation, longest
    first. A word written with an underscore matches a multi-word phrase
    ("so_far" -> "so far")."""
    items = sorted(set(words.split()), key=len, reverse=True)
    return "(?:" + "|".join(re.escape(w).replace("_", _S) for w in items) + ")"


def _rx(pattern: str) -> Pattern:
    return re.compile(pattern, re.IGNORECASE)


class _Rule(NamedTuple):
    name: str
    # Group "w" is the word that changes. Left context is matched, right
    # context lives in a lookahead so a rule never swallows the word the next
    # rule needs.
    pattern: Pattern
    replacement: str
    guard: Optional[Callable[[str, "re.Match"], bool]] = None
    # Keep a capital the word already had mid-sentence ("Closed One" ->
    # "Closed Won"). Off by default: Parakeet capitalises a mis-picked "One"
    # as if it were a name ("Revenue One"), and that capital is the mistake.
    keep_title: bool = False


# ── Shared context ───────────────────────────────────────────────────────────

# Plural things you win. Plural on purpose: after the numeral "one" only a
# SINGULAR noun is grammatical ("one deal"), so "have one deals" can only be
# the verb, while "have one deal" is a count and stays.
_WON_PLURALS = """
awards prizes deals contracts games matches tenders bids cases elections
titles trophies medals races points seats votes customers clients accounts
pitches battles arguments rounds goals
"""

# "the" after "one" is the verb's object ("won the deal") EXCEPT in these time
# and size phrases, where "one" is a count or a pronoun ("had one the other
# day", "one the size of a phone", "have one the whole time").
_THE_NOT_OBJECT = _alt("""
other next last same whole day week month year morning afternoon evening
night weekend size one first second previous following
""")
_NUMBER = (r"(?:\d[\d,.]*|a_couple_of|a_few|two|three|four|five|six|seven|"
           r"eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|hundred|"
           r"several|some|both)").replace("_", _S)

# What "won" takes as its object: "the deal", "it", "them", "(three) awards".
_OBJECT = (r"(?:the" + _S + r"(?!" + _THE_NOT_OBJECT + _E + r")"
           r"|it(?![\w'’])|them" + _E +
           r"|(?:" + _NUMBER + _S + r")?" + _alt(_WON_PLURALS) + _E + r")")

# Words that make "one" a count or a pronoun when they follow it.
_ONE_AS_COUNT = _alt("""
day time of more another or and thing point way last less too either each
at by in on for to with from that which who is was
""")


def _sentence_tail(text: str, pos: int) -> str:
    m = re.search(r"[.!?\n]", text[pos:])
    return text[pos:pos + m.start()] if m else text[pos:]


def _sentence_head(text: str, pos: int) -> str:
    cut = max(text.rfind(c, 0, pos) for c in ".!?\n")
    return text[cut + 1:pos]


def _not_enumeration(text: str, m) -> bool:
    """A later "one"/"another"/"other" in the same sentence means the first
    "one" was a count in a list ("two deals one this week and one next")."""
    return not re.search(r"(?<![\w'’])(?:one|another|other)(?![\w'’])",
                         _sentence_tail(text, m.end("w")), re.IGNORECASE)


def _no_count_before(text: str, m) -> bool:
    """ "we lost two customers one this week": a number before the noun makes
    the "one" a share of it, not the verb."""
    head = _sentence_head(text, m.start())
    return not re.search(r"(?<![\w'’])" + _NUMBER + r"[ \t]+(?:\w+[ \t]+)?$",
                         head, re.IGNORECASE)


def _not_question(text: str, m) -> bool:
    """ "Did we one?" reads as a pronoun more often than the verb."""
    tail = _sentence_tail(text, m.end("w"))
    return text[m.end("w") + len(tail):m.end("w") + len(tail) + 1] != "?"


def _all(*guards):
    return lambda t, m: all(g(t, m) for g in guards)


# ── The rules ────────────────────────────────────────────────────────────────

_RULES: List[_Rule] = [

    # ── one -> won ───────────────────────────────────────────────────────────

    # Subject pronoun + "one": "we one the deal", "they one it", "We one."
    # Object pronouns are left out ("give you one", "owe you one"), and so is
    # a pronoun after a copula ("is she one", "am I one", "are we one team").
    _Rule("won_after_subject", _rx(
        r"(?<![\w'’])(?<!is )(?<!am )(?<!are )(?<!was )(?<!were )(?<!be )"
        r"(?:I|we|they|he|she)" + _S +
        r"(?P<w>one)" + _E +
        r"(?!" + _S + _ONE_AS_COUNT + _E + r")"
        r"(?![ \t]*[?,;:])"
    ), "won", guard=_all(_not_question, _not_enumeration)),

    # Perfect "have" + "one" + an object: "we have one the contract", "she's
    # had one it", "they've one three awards". "have one", "have one back",
    # "had one again" and "have one every day" are all counts and stay.
    _Rule("won_after_have", _rx(
        _B + r"(?:have|has|had|having|haven't|hasn't|hadn't|[a-z]+'ve|[a-z]+’ve)" +
        _S + r"(?P<w>one)" + _E + r"(?=" + _S + _OBJECT + r")"
    ), "won", guard=_not_enumeration),

    # Adverb + "one" + an object: "we finally one the tender".
    _Rule("won_after_adverb", _rx(
        _B + r"(?:just|never|finally|already|recently|narrowly|eventually|"
        r"nearly|almost|actually|comfortably|easily)" + _S +
        r"(?P<w>one)" + _E + r"(?=" + _S + _OBJECT + r")"
    ), "won", guard=_not_enumeration),

    # The reported case. Something you win + "one" + a time or rivalry
    # phrase: "Revenue one this quarter", "deals one so far", "clients one
    # since March". Singular countable nouns are left out because "phase one
    # this quarter" and "deal one this week" are enumerations.
    _Rule("won_after_sales_noun", _rx(
        _B + _alt("revenue business sales orders opportunities jobs projects "
                  + _WON_PLURALS) + _S +
        r"(?P<w>one)" + _E +
        r"(?=" + _S + _alt("this last so_far since today yesterday recently "
                           "to_date year_to_date ytd against over_the "
                           "over_last in_q1 in_q2 in_q3 in_q4") + _E + r")"
    ), "won", guard=_all(_not_enumeration, _no_count_before)),

    # A winning margin: "one by a mile", "one by a landslide".
    _Rule("won_by_margin", _rx(
        _B + r"(?P<w>one)" + _S +
        r"(?=by" + _S + r"(?:a|an)" + _S +
        _alt("mile country_mile landslide whisker nose length head "
             "narrow_margin clear_margin wide_margin big_margin huge_margin "
             "small_margin") + _E + r")"
    ), "won"),

    # "one or lost", "deals one and lost", "lost or one".
    _Rule("won_or_lost", _rx(
        _B + r"(?P<w>one)" + _S + r"(?=(?:or|and|vs|versus)" + _S +
        r"(?:lost|drawn)" + _E + r")"
    ), "won"),
    _Rule("lost_or_won", _rx(
        _B + r"lost" + _S + r"(?:or|and|vs|versus)" + _S + r"(?P<w>one)" + _E
    ), "won"),

    # The CRM deal stage: "marked as closed one" -> "closed won". "I closed
    # one yesterday" (a deal) has no stage word before it and stays.
    _Rule("closed_won_stage", _rx(
        _B + r"(?:as|to|into|in|at|stage|status|marked|mark|set|move|moved)" +
        _S + r"closed(?:" + _S + r"|-)(?P<w>one)" + _E
    ), "won", keep_title=True),
    _Rule("closed_won_pair", _rx(
        _B + r"closed(?:" + _S + r"|-)(?P<w>one)" + _E +
        r"(?=" + _S + r"(?:or|and|vs|versus)" + _S +
        r"closed(?:" + _S + r"|-)lost" + _E + r")"
    ), "won", keep_title=True),

    # ── won -> one ───────────────────────────────────────────────────────────

    _Rule("one_of", _rx(
        _B + r"(?P<w>won)" + _S + r"(?=of" + _S +
        _alt("the my our your their his her its those these them us you "
             "which what many several") + _E + r")"
    ), "one"),
    _Rule("no_one", _rx(
        _B + r"no" + _S + r"(?P<w>won)" + _E +
        r"(?=" + _END + r"|'s|’s|" + _S + _alt(
            "is was will would can could should has had knows knew else wants "
            "cares seems really actually ever here there") + _E + r")"
    ), "one"),
    _Rule("the_one", _rx(
        _B + r"(?:the|this)" + _S + r"(?P<w>won)" + _E +
        r"(?=" + _S + _alt("that who which is was looks seems works here") +
        _E + r")"
    ), "one"),

    # ── then -> than ─────────────────────────────────────────────────────────

    # A comparative + "then" + what it is compared with. The right context is
    # what keeps "add a bit more then save" as the time word, and "later
    # then" is not listed at all ("see you later then").
    _Rule("than", _rx(
        _B + _alt("more less fewer better worse bigger smaller higher lower "
                  "faster slower greater larger longer shorter cheaper easier "
                  "harder quicker stronger weaker heavier lighter older "
                  "younger busier safer simpler clearer") + _S +
        r"(?P<w>then)" + _E +
        r"(?=" + _S + r"(?:\d|" + _alt(
            "a an one two three four five six seven eight nine ten twenty "
            "fifty hundred thousand million ever usual expected before "
            "anything anyone anybody everyone everything average normal "
            "necessary needed planned twice half") + _E + r"))"
    ), "than"),
    _Rule("other_than", _rx(
        _B + r"(?<!each )(?<!one )(?<!the )(?:other|rather)" + _S +
        r"(?P<w>then)" + _E +
        r"(?=" + _S + _alt("that this the a an me you him her us them") +
        _E + r")"
    ), "than"),

    # ── of -> have ───────────────────────────────────────────────────────────

    _Rule("modal_have", _rx(
        _B + r"(?:could|should|would|must|might)(?:n't|n’t)?" + _S +
        r"(?P<w>of)" + _S + r"(?=" + _alt(
            "been had done gone got gotten seen known made said taken thought "
            "liked loved wanted told given come become heard sent asked tried "
            "used called checked missed forgotten left put let") + _E + r")"
    ), "have"),

    # ── whether ──────────────────────────────────────────────────────────────

    _Rule("whether_or_not", _rx(
        _B + r"(?<!the )(?P<w>weather)" + _S + r"(?=or" + _S + r"not" + _E + r")"
    ), "whether"),
    _Rule("whether_clause", _rx(
        r"(?:(?:^|(?<=[.!?\n]))[ \t]*|" + _B + _alt(
            "know knows knew see check decide decided ask asked wondering "
            "wonder unsure sure matter matters doubt confirm tell clear") +
        _S + r")(?P<w>weather)" + _S +
        r"(?=(?:we|you|they|I|he|she|it's)" + _S + _alt(
            "should can could will would want need go are were do did "
            "decide is was") + _E + r")"
    ), "whether"),

    # ── you're / your, it's / its, there / their ────────────────────────────

    _Rule("youre", _rx(
        _B + r"(?P<w>your)" + _S +
        r"(?=going" + _S + r"to" + _E + r"|(?:gonna|able|already|absolutely|"
        r"probably|definitely)" + _E + r"|not(?![\w'’-])|welcome" + _END + r")"
    ), "you're"),
    _Rule("your_things", _rx(
        _B + r"(?P<w>you're|you’re)" + _S + r"(?=" + _alt(
            "own thoughts feedback details calendar inbox laptop computer "
            "behalf name") + _E + r")"
    ), "your"),
    _Rule("its_is", _rx(
        _B + r"(?P<w>its)" + _S +
        r"(?=going" + _S + r"to" + _E + r"|not(?![\w'’-])|" +
        _alt("a an the been gonna okay ok") + _E + r")"
    ), "it's"),
    _Rule("its_own", _rx(
        _B + r"(?P<w>it's|it’s)" + _S + r"(?=own" + _E + r")"
    ), "its"),
    _Rule("there_is", _rx(
        _B + r"(?P<w>their)" + _S + r"(?=(?:is|are|was|were|isn't|aren't|"
        r"wasn't|weren't|seems|seem|(?:will|would|must|might|could|should)" +
        _S + r"be|(?:has|have)" + _S + r"been|used" + _S + r"to" + _S +
        r"be)" + _E + r")"
    ), "there"),
    _Rule("their_own", _rx(
        _B + r"(?P<w>there|they're|they’re)" + _S + r"(?=own" + _E + r")"
    ), "their"),

    # ── too ──────────────────────────────────────────────────────────────────

    # "is to late" -> "too late". The adjective list leaves out every word
    # that is also a verb after "to" ("the plan is to close / slow / short").
    _Rule("too", _rx(
        _B + _alt("is was are were be it's that's not bit way far slightly") +
        _S + r"(?P<w>to)" + _S + r"(?=" + _alt(
            "much many long late early big small soon expensive hard easy "
            "often high busy complicated complex risky dark bright loud "
            "tight hot cold heavy bad") + _E + r")"
    ), "too"),

    # ── write / right ────────────────────────────────────────────────────────

    # "Right an email to John" -> "Write". Never after a word that makes it
    # the interjection or the direction ("all right a note for you", "that's
    # right an email", "turn right a…").
    _Rule("write_a", _rx(
        _B + r"(?<!all )(?<!that's )(?<!that’s )(?<!yeah )(?<!yes )"
        r"(?<!okay )(?<!ok )(?<!right )(?<!turn )(?<!left )(?<!is )"
        r"(?<!was )(?<!exactly )(?<!quite )"
        r"(?P<w>right)" + _S +
        r"(?=(?:a|an|me" + _S + r"(?:a|an)|up" + _S + r"(?:a|an|the))" + _S +
        _alt("email emails letter report note message blog post review script "
             "proposal summary function story cheque list brief article essay "
             "update invoice reply response description prompt query comment "
             "draft spec") + _E + r")"
    ), "write"),
    _Rule("write_down", _rx(
        _B + r"(?P<w>right)" + _S + r"(?=(?:it|that|this|them|these|those)" +
        _S + r"down" + _E + r")"
    ), "write"),

    # ── hear / here ──────────────────────────────────────────────────────────

    _Rule("hear", _rx(
        _B + r"(?:can|can't|cannot|could|couldn't|didn't|did" + _S + r"you|"
        r"did" + _S + r"they|did" + _S + r"we|will|won't|never)" + _S +
        r"(?P<w>here)" + _S + r"(?=(?:you|me|him|her|them|us|that|what|"
        r"anything|nothing|something|back|from" + _S +
        r"(?:you|him|her|them|us|me)|about" + _S +
        r"(?:it|that|this|them|him|her))" + _E + r")"
    ), "hear"),
    # After "to" the place reading is real ("from there to here you need",
    # "fly to here from London"), so only the unmistakable objects count.
    _Rule("to_hear", _rx(
        _B + r"to" + _S + r"(?P<w>here)" + _S +
        r"(?=(?:back|from" + _S + r"(?:you|him|her|them|us|me)|about" + _S +
        r"(?:it|that|this|them|him|her))" + _E + r")"
    ), "hear"),
    _Rule("in_here", _rx(
        _B + r"(?:right|in|out)" + _S + r"(?P<w>hear)" + _E +
        r"(?=" + _END + r"|" + _S + _alt("and now too with is was for") + _E + r")"
    ), "here"),

    # ── know / no ────────────────────────────────────────────────────────────

    _Rule("let_know", _rx(
        _B + r"let" + _S + r"(?:me|us|you|them|him|her)" + _S +
        r"(?P<w>no)" + _E + r"(?!" + _S + r"(?:longer|more|one)" + _E + r")"
    ), "know"),
    _Rule("dont_know", _rx(
        _B + r"(?:don't|didn't|doesn't|don’t|didn’t|doesn’t|dont)" + _S +
        r"(?P<w>no)" + _E + r"(?!" + _S + r"(?:longer|more|one|matter)" + _E + r")"
    ), "know"),
    _Rule("i_know", _rx(
        _B + r"(?:I|you|we|they)" + _S + r"(?P<w>no)" + _S +
        r"(?=" + _alt("that what how why where when who if whether") + _E + r")"
    ), "know"),

    # ── week / weak ──────────────────────────────────────────────────────────

    _Rule("week", _rx(
        _B + r"(?:this|next|last|per|each|every)" + _S + r"(?P<w>weak)" + _E +
        r"(?=" + _END + r"|" + _S + _alt(
            "we I you they he she it is was the on in at for to with so but "
            "then because if when there now too already though anyway") +
        _E + r")"
    ), "week"),
    _Rule("a_week_ago", _rx(
        _B + r"(?:a|one)" + _S + r"(?P<w>weak)" + _S + r"(?=ago" + _E + r")"
    ), "week"),
    _Rule("weeks_ago", _rx(
        _B + r"(?P<w>weaks)" + _S + r"(?=ago" + _E + r")"
    ), "weeks"),

    # ── fixed phrases ────────────────────────────────────────────────────────

    _Rule("peace_of_mind", _rx(
        _B + r"(?P<w>piece)" + _S + r"(?=of" + _S + r"mind" + _E + r")"
    ), "peace"),
    _Rule("piece_of", _rx(
        _B + r"(?P<w>peace)" + _S + r"(?=of" + _S + _alt(
            "cake paper work code advice information content equipment "
            "software kit furniture feedback evidence news text data writing "
            "the_puzzle") + _E + r")"
    ), "piece"),
    _Rule("out_of_sight", _rx(
        _B + r"out" + _S + r"of" + _S + r"(?P<w>site)" + _E + r"(?=" + _END + r")"
    ), "sight"),
    _Rule("lose_sight_of", _rx(
        _B + r"(?:lose|lost|losing)" + _S + r"(?P<w>site)" + _S +
        r"(?=of" + _E + r")"
    ), "sight"),
    _Rule("roll_out", _rx(
        _B + r"(?P<w>role)" + _S + r"(?=out" + _E + r"(?!" + _S + r"of" + _E + r"))"
    ), "roll"),
    _Rule("role_model", _rx(
        _B + r"(?P<w>roll)" + _S + r"(?=" + _alt("model models play playing") +
        _E + r")"
    ), "role"),
    _Rule("on_a_roll", _rx(
        _B + r"on" + _S + r"a" + _S + r"(?P<w>role)" + _E +
        r"(?=" + _END + r"|" + _S + _alt(
            "lately today recently right_now at_the_moment") + _E + r")"
    ), "roll"),
    _Rule("whole", _rx(
        _B + r"(?:the|a)" + _S + r"(?P<w>hole)" + _S + r"(?=" + _alt(
            "lot thing team day week month year time point idea process "
            "company world project system app page website document bunch "
            "new") + _E + r")"
    ), "whole"),
    _Rule("bear_with", _rx(
        _B + r"(?P<w>bare)" + _S +
        r"(?=(?:with" + _S + r"(?:me|us)|in" + _S + r"mind)" + _E + r")"
    ), "bear"),
    _Rule("the_past", _rx(
        _B + r"the" + _S + r"(?P<w>passed)" + _E +
        r"(?=" + _END + r"|" + _S + _alt(
            "week month year few couple hour days weeks months years decade "
            "day night two three") + _E + r")"
    ), "past"),
    _Rule("take_a_break", _rx(
        _B + r"(?:(?:take|took|taking|takes|grab)" + _S + r"a|lunch|coffee|"
        r"tea|summer|christmas|easter)" + _S + r"(?P<w>brake)" + _E +
        r"(?!" + _S + _alt("pad pads fluid light lights disc discs pedal "
                           "system line lines caliper cable") + _E + r")"
    ), "break"),
    _Rule("where_is", _rx(
        r"(?:^|(?<=[.!?\n]))[ \t]*(?P<w>wear)" + _S + r"(?=" + _alt(
            "is are was were does did can should would has have") + _E + r")"
    ), "where"),
]

# Reported to the fleet error log like the repetition and stutter guards.
_reporter: Optional[Callable[[str, dict], None]] = None


def set_reporter(fn: Optional[Callable[[str, dict], None]]) -> None:
    """Install the telemetry sink. fn(event_type, detail_dict)."""
    global _reporter
    _reporter = fn


def _report(detail: dict) -> None:
    if _reporter is None:
        return
    try:
        _reporter("transcribe_homophone", detail)
    except Exception:
        pass


def _at_sentence_start(text: str, pos: int) -> bool:
    before = text[:pos].rstrip(" \t\"'“‘(")
    return not before or before[-1] in ".!?\n"


def _cased(new: str, old: str, text: str, pos: int, keep_title: bool) -> str:
    """The replacement takes the old word's capital only where a capital
    belongs: a sentence start, or a Title Case phrase for rules that keep one.
    A capital anywhere else was the engine's mistake ("Revenue One")."""
    if len(old) > 1 and old.isupper():
        return new.upper()
    if old[:1].isupper() and (keep_title or _at_sentence_start(text, pos)):
        return new[:1].upper() + new[1:]
    return new


def fix(text: str, source: str = "") -> str:
    """Pick the right spelling of each sound-alike word the rules recognise.

    Returns the text unchanged when no rule fires. Only the one word a rule
    names is ever replaced; spacing, punctuation and line breaks are kept
    exactly."""
    if not text:
        return text
    fired: List[str] = []
    for rule in _RULES:
        current = text

        def _sub(m, _rule=rule, _text=current):
            if _rule.guard is not None and not _rule.guard(_text, m):
                return m.group(0)
            old = m.group("w")
            new = _cased(_rule.replacement, old, _text, m.start("w"),
                         _rule.keep_title)
            if new == old:
                return m.group(0)
            fired.append(_rule.name)
            ws, we = m.start("w") - m.start(), m.end("w") - m.start()
            g = m.group(0)
            return g[:ws] + new + g[we:]

        text = rule.pattern.sub(_sub, current)
    if fired:
        _report({"source": source, "rules": fired, "count": len(fired)})
    return text
