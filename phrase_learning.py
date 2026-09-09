"""Learned phrases — the things this person actually says, boosted back at them.

The recogniser is general; a user is not. Ryan says "Brightlink pipeline" and
"scrape anything" dozens of times a week, and the engine has no idea either is
a thing. This module watches what he actually dictates, keeps the phrases he
repeats, and uses them to rescue the next time the engine fumbles one.

Two confidence gates, deliberately opposite:

  Learning — a phrase is only COUNTED when the engine was SURE about every word
    in it. Counting a shaky span would be learning the mistake and then
    enforcing it, which is the one way this feature could actively make
    dictation worse.

  Rescuing — a span is only REWRITTEN when the engine was UNSURE about it. Where
    the engine was confident it heard "the sell", it heard "the sell"; putting a
    learned phrase there would be putting words in the user's mouth. So the
    rescue only ever fires in the gap where the engine itself is hedging.

Both are real numbers, not a proxy: Parakeet's decoder emits a log-probability
per token (`need_logprobs`), which costs one softmax per emitted token — a few
microseconds on a whole dictation — and the whisper fallback supplies its
segment average. Where confidence is unknown BOTH gates fail closed: nothing is
learned and nothing is rewritten.

Speed: everything here runs on the finished transcript, after injection has
already been decided, never on the transcription path. The rescue is bounded
exactly like `text_expansion.apply_vocabulary_fuzzy` (one Double Metaphone
encode per word, a cheap first-phoneme prefilter) and returns immediately when
nothing has been learned yet. Writes to disk are debounced onto a daemon
thread, so a dictation never waits on IO.

Storage is deliberately LOCAL and per-account: these are statistics about one
person at one keyboard, they are not worth a sync table, and a machine's own
counts merging with another machine's would only blur the threshold.
"""

import json
import math
import os
import re
import threading
import time
from datetime import datetime, timezone

# Primitives shared with the hand-typed vocabulary path. Imported rather than
# copied so the phonetic firewall, the common-word list and the sentence-casing
# rule can only ever have one definition — a second copy that drifted is how a
# safety gate quietly stops being a gate.
from text_expansion import (_COMMON_WORDS, _WORD_RE, _cased, _dm,
                            _jaro_winkler, _phonetic_match)

# ── Thresholds ───────────────────────────────────────────────────────────────

MIN_PHRASE_WORDS = 1
# Three, not four. A four-word chain is almost never mis-heard as a unit, so it
# can rescue almost nothing, while every extra window size multiplies what gets
# stored and eats the capped hotword budget. The value is in the short
# distinctive units — "Brightlink", "prospect intel", "lead finder".
MAX_PHRASE_WORDS = 3

# How often something must be said before it counts as "how this person talks".
PROMOTE_COUNT = 4           # multi-word phrases
PROMOTE_COUNT_SINGLE = 8    # a single word is far likelier to collide, so it
                            # has to earn the place twice over — AND the engine
                            # has to have fumbled something that sounds like it
                            # at least once (see _fumbled)

# A word must be recognised at least this confidently to COUNT towards a
# phrase. 0.75 is well clear of the engine's ordinary range on clean speech
# (measured: correct words sit at 0.9+, a genuine fumble drops below 0.5).
LEARN_CONF = 0.75

# A span is only a rescue candidate BELOW this. The band between the two is
# deliberately dead: neither confident enough to learn from nor doubtful enough
# to overwrite.
RESCUE_CONF = 0.55

# Near-identical or nothing — stricter even than the managed/CRM tier (0.86),
# because a learned phrase was never reviewed by a human: the user typed
# nothing and approved nothing. Measured on the real corpus, the genuine
# rescues sit at 0.94-1.00 ("leedfinder"/"leadfinder" 0.947,
# "brightling"/"brightlink" 0.960, "vercell"/"vercel" 0.971) while the one
# false positive the corpus produced sits at 0.869 ("wanting"/"anything"). 0.92
# separates them with room on both sides.
RESCUE_JW = 0.92
# A safe rescue is a RE-SPELLING, so the letters either side must be about the
# same in number. The old managed-tier window (0.7-1.4) is too generous for
# this tier: it let "actual" reach "actually" (ratio 0.75, jw 0.95, identical
# metaphone), which is a different word and turned up eight times in the corpus
# run. The real rescues all sit inside 0.82-1.22 — "vercell"/"vercel" is 1.17,
# and every measured respelling of a name is 1.0.
RESCUE_LEN_LO = 0.82
RESCUE_LEN_HI = 1.22

# A span with a DIFFERENT number of words to the phrase it matches is the case
# that can destroy speech rather than repair it: collapsing "really a" onto
# "really" deletes a word the user said, and "to main" is phonetically almost
# "domain". Measured against the 200 real transcripts in history.json, both of
# those happen at the ordinary floor. So a cross-count match must be
# near-identical in letters AND may not be shorter than the span it replaces —
# which still lets the case this whole feature exists for through, because
# "bright link" and "Brightlink" are the SAME letters (jw 1.0, equal length).
RESCUE_SPLIT_JW = 0.95

MIN_SINGLE_LEN = 6          # single learned words shorter than this are dropped
MIN_PHRASE_CHARS = 8        # a multi-word phrase must have some substance

MAX_CANDIDATES = 600        # counting table ceiling (pruned lowest-count first)
MAX_PHRASES = 200           # promoted ceiling
MAX_HOTWORDS = 40           # how many reach the whisper decoder prompt

FLUSH_SECONDS = 20.0        # debounce on the disk write

_STORE_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Per-word confidence ──────────────────────────────────────────────────────

def probability(logprobs) -> float:
    """A word's confidence from its tokens' log-probabilities.

    Geometric mean, i.e. the mean in log space — the standard reading, and the
    one that stops a long word being punished simply for having more tokens.
    """
    vals = [float(v) for v in (logprobs or []) if v is not None]
    if not vals:
        return 0.0
    try:
        return math.exp(sum(vals) / len(vals))
    except (OverflowError, ValueError):
        return 0.0


_CONF_WORD_RE = re.compile(r"[a-z0-9']+")


def normalise_word(word: str) -> str:
    """A word reduced to what two spellings of the same sound share: lower
    case, letters/digits/apostrophe only. Empty when nothing survives (a lone
    comma token), and callers drop those."""
    m = _CONF_WORD_RE.search((word or "").lower())
    return m.group(0) if m else ""


def words_from_tokens(tokens, logprobs) -> list:
    """[(word, confidence)] from a SentencePiece token/logprob pair.

    onnx-asr rewrites the ``▁`` word marker to a leading SPACE when it loads
    the vocab, so a token starting with a space opens a new word. Punctuation-
    only tokens carry no word and are dropped rather than becoming empty
    entries that would knock the alignment out of step.
    """
    if not tokens or not logprobs or len(tokens) != len(logprobs):
        return []
    out = []
    cur, lps = "", []

    def _flush():
        if not cur:
            return
        w = normalise_word(cur)
        if w:
            out.append((w, probability(lps)))

    for tok, lp in zip(tokens, logprobs):
        if isinstance(tok, str) and tok[:1] == " ":
            _flush()
            cur, lps = tok[1:], [lp]
        else:
            cur += str(tok)
            lps.append(lp)
    _flush()
    return out


# How far ahead in the recording the aligner will look for the next word of the
# final text. Post-processing DELETES words (stutters, fillers, a suppressed
# hallucination), so the record legitimately runs ahead; it never inserts a run
# this long.
_ALIGN_LOOKAHEAD = 12


def align(text: str, recorded) -> list:
    """Confidence per word of `text`, or None where it cannot be established.

    `recorded` is the engine's own [(word, confidence)] in spoken order. The
    final text is close to, but never exactly, that sequence: destuttering and
    filler-stripping remove words, the spoken-symbol and list passes rewrite
    some, and the user's vocabulary replaces others. So this is a forgiving
    two-pointer — skip forward in the record to find the next match, and give up
    on a word rather than guess.

    An unknown confidence fails both gates, so a bad alignment costs the feature
    a dictation. That is the correct direction to fail in.
    """
    words = [normalise_word(m.group(0)) for m in _WORD_RE.finditer(text or "")]
    out = [None] * len(words)
    if not recorded:
        return out
    j = 0
    for i, w in enumerate(words):
        if not w:
            continue
        hit = -1
        for k in range(j, min(len(recorded), j + _ALIGN_LOOKAHEAD)):
            if recorded[k][0] == w:
                hit = k
                break
        if hit < 0:
            continue        # rewritten or invented — leave it unknown
        out[i] = recorded[hit][1]
        j = hit + 1
    return out


# ── What is worth learning ───────────────────────────────────────────────────

# Split the transcript into runs of words separated by whitespace only. A
# phrase may not straddle punctuation: "…the pipeline. Brightlink is…" contains
# no phrase "pipeline brightlink", and learning one would teach the engine to
# glue two sentences together.
def _runs(text: str) -> list:
    """[[(index, word)]] — consecutive word positions with nothing but spaces
    between them."""
    toks = list(_WORD_RE.finditer(text or ""))
    runs, cur = [], []
    for i, t in enumerate(toks):
        if cur:
            prev = toks[i - 1]
            if text[prev.end():t.start()].strip() != "":
                runs.append(cur)
                cur = []
        cur.append((i, normalise_word(t.group(0))))
    if cur:
        runs.append(cur)
    return [r for r in runs if all(w for _i, w in r)]


def is_learnable(words) -> bool:
    """True when this run of normalised words is worth counting.

    Refused: anything with a digit (numbers are one-offs — "forty two contacts"
    is not a phrase somebody has), anything made entirely of ordinary English
    (a phrase the engine already gets right by construction, and the one most
    likely to collide with real speech), and anything too short to be
    distinctive.
    """
    if not words or not (MIN_PHRASE_WORDS <= len(words) <= MAX_PHRASE_WORDS):
        return False
    if any(any(ch.isdigit() for ch in w) for w in words):
        return False
    if all(w in _COMMON_WORDS for w in words):
        return False
    # The EDGES must carry weight. Every window of a sentence is offered here,
    # so without this the store fills with fragments — "the brightlink",
    # "pipeline to" — which are not things anybody says, they are things that
    # happen to sit next to things somebody says. A phrase that begins or ends
    # on a function word is one of those.
    if words[0] in _COMMON_WORDS or words[-1] in _COMMON_WORDS:
        return False
    if len(words) == 1:
        return len(words[0]) >= MIN_SINGLE_LEN
    return sum(len(w) for w in words) >= MIN_PHRASE_CHARS


def promote_at(words) -> int:
    return PROMOTE_COUNT_SINGLE if len(words) == 1 else PROMOTE_COUNT


# ── The store ────────────────────────────────────────────────────────────────

def _safe_name(key: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "_", (key or "_local").lower())[:80] or "_local"


def store_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "FTC Whisper", "phrases")


class PhraseStore:
    """One account's phrase counts and promoted phrases, on this machine.

    Thread-safe (the dictation thread observes, the UI thread lists and
    forgets) and never blocking: the disk write is debounced onto a daemon
    thread, so nothing the user is waiting for ever touches IO.
    """

    def __init__(self, email: str = "", directory: str = ""):
        self.key = _safe_name((email or "").strip().lower() or "_local")
        self.path = os.path.join(directory or store_dir(), f"{self.key}.json")
        self._lock = threading.Lock()
        self._candidates = {}       # norm -> [count, last_iso]
        self._phrases = {}          # norm -> {phrase, count, learned_at}
        # Double Metaphone codes of words the engine has been UNSURE about.
        # Keyed by sound, not spelling, on purpose: when it fumbles
        # "Brightlink" what it writes is "brightling", so the only thing the
        # mistake and the target share is the code. See `_has_fumbled`.
        self._fumbled = {}          # code -> count
        self._dirty = False
        self._flush_at = 0.0
        self._flushing = False
        self._load()

    # -- disk -------------------------------------------------------------

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        cands = data.get("candidates")
        if isinstance(cands, dict):
            for norm, row in cands.items():
                try:
                    self._candidates[norm] = [int(row[0]), str(row[1])]
                except (TypeError, ValueError, IndexError):
                    continue
        fum = data.get("fumbled")
        if isinstance(fum, dict):
            for code, n in fum.items():
                try:
                    self._fumbled[str(code)] = int(n)
                except (TypeError, ValueError):
                    continue
        for row in data.get("phrases") or []:
            if not isinstance(row, dict):
                continue
            phrase = " ".join((row.get("phrase") or "").split())
            norm = phrase.lower()
            if phrase and norm not in self._phrases:
                self._phrases[norm] = {
                    "phrase": phrase,
                    "count": int(row.get("count") or 0),
                    "learned_at": str(row.get("learned_at") or ""),
                }

    def _snapshot(self) -> dict:
        return {
            "version": _STORE_VERSION,
            "candidates": {k: list(v) for k, v in self._candidates.items()},
            "fumbled": dict(self._fumbled),
            "phrases": list(self._phrases.values()),
        }

    def flush(self) -> bool:
        """Write now, on this thread. Returns success; never raises — losing a
        few counts is not worth losing a dictation over."""
        with self._lock:
            data = self._snapshot()
            self._dirty = False
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
            return True
        except OSError as exc:
            print(f"[Phrases] save failed (non-fatal): {exc}")
            return False

    def _touch(self, urgent: bool = False) -> None:
        """Mark dirty and arrange a write. Coalesced: repeated dictations inside
        the debounce window share one write."""
        self._dirty = True
        now = time.monotonic()
        if not urgent and now < self._flush_at:
            return
        if self._flushing:
            return
        self._flushing = True
        self._flush_at = now + FLUSH_SECONDS

        def _run():
            try:
                if not urgent:
                    time.sleep(FLUSH_SECONDS)
                self.flush()
            finally:
                self._flushing = False

        threading.Thread(target=_run, daemon=True, name="phrase-flush").start()

    # -- counting ---------------------------------------------------------

    def _prune(self) -> None:
        if len(self._candidates) > MAX_CANDIDATES:
            keep = sorted(self._candidates.items(),
                          key=lambda kv: (kv[1][0], kv[1][1]),
                          reverse=True)[:MAX_CANDIDATES]
            self._candidates = dict(keep)
        if len(self._fumbled) > MAX_CANDIDATES:
            keep = sorted(self._fumbled.items(), key=lambda kv: kv[1],
                          reverse=True)[:MAX_CANDIDATES]
            self._fumbled = dict(keep)
        if len(self._phrases) > MAX_PHRASES:
            keep = sorted(self._phrases.items(),
                          key=lambda kv: kv[1].get("count") or 0,
                          reverse=True)[:MAX_PHRASES]
            self._phrases = dict(keep)

    def _has_fumbled(self, word: str) -> bool:
        """Has the engine ever been unsure about something that SOUNDS like
        this word?

        This is what stops the store filling with words the recogniser already
        gets right every time. Ryan says "actually" sixty-three times in two
        hundred dictations and it is never once wrong, so boosting it buys
        nothing and only spends a hotword slot; "Brightlink" is said less often
        and mangled regularly, and that is the word worth remembering. Only
        single words are gated this way — a multi-word phrase is constrained
        enough by having to match across consecutive words.
        """
        dm = _dm()
        if dm is None:
            return True         # no encoder, no gate — degrade to count alone
        try:
            code = dm(word)[0]
        except Exception:
            return False
        # Twice, not once: a single low-confidence blip on a word the engine
        # normally nails is noise, not a struggle.
        return bool(code) and self._fumbled.get(code, 0) >= 2

    def _note_fumbles(self, text: str, conf) -> None:
        dm = _dm()
        if dm is None:
            return
        for i, m in enumerate(_WORD_RE.finditer(text or "")):
            c = conf[i] if i < len(conf) else None
            if c is None or c >= RESCUE_CONF:
                continue
            w = normalise_word(m.group(0))
            if len(w) < MIN_SINGLE_LEN:
                continue
            try:
                code = dm(w)[0]
            except Exception:
                continue
            if code:
                self._fumbled[code] = self._fumbled.get(code, 0) + 1

    def observe(self, text: str, word_conf=None) -> list:
        """Count every learnable phrase in `text` the engine was sure about.

        Returns the phrases promoted by THIS dictation (usually none), so the
        caller can tell the user something was learned.
        """
        if not text:
            return []
        conf = list(word_conf or [])
        promoted = []
        with self._lock:
            self._note_fumbles(text, conf)
            for run in _runs(text):
                n = len(run)
                for size in range(MIN_PHRASE_WORDS,
                                  min(MAX_PHRASE_WORDS, n) + 1):
                    for start in range(0, n - size + 1):
                        span = run[start:start + size]
                        words = [w for _i, w in span]
                        if not is_learnable(words):
                            continue
                        # Every word must be present AND confidently heard.
                        ok = True
                        for idx, _w in span:
                            c = conf[idx] if idx < len(conf) else None
                            if c is None or c < LEARN_CONF:
                                ok = False
                                break
                        if not ok:
                            continue
                        norm = " ".join(words)
                        if norm in self._phrases:
                            self._phrases[norm]["count"] += 1
                            continue
                        row = self._candidates.get(norm)
                        if row is None:
                            row = [0, ""]
                            self._candidates[norm] = row
                        row[0] += 1
                        row[1] = _now()
                        if size == 1 and not self._has_fumbled(words[0]):
                            continue    # the engine has never struggled with
                                        # this word — boosting it is dead weight
                        if row[0] >= promote_at(words):
                            self._phrases[norm] = {
                                "phrase": norm,
                                "count": row[0],
                                "learned_at": _now(),
                            }
                            self._candidates.pop(norm, None)
                            promoted.append(norm)
            self._prune()
        self._touch(urgent=bool(promoted))
        return promoted

    # -- reading ----------------------------------------------------------

    def phrases(self) -> list:
        """Promoted phrases, most-said first. A copy — the caller may sort,
        filter and hold it without touching the store."""
        with self._lock:
            rows = [dict(r) for r in self._phrases.values()]
        rows.sort(key=lambda r: (-(r.get("count") or 0), r.get("phrase") or ""))
        return rows

    def phrase_texts(self) -> list:
        with self._lock:
            return [r["phrase"] for r in self._phrases.values()]

    def forget(self, phrase: str) -> bool:
        """Drop a learned phrase AND its counter, so a phrase the user rejected
        does not simply climb back over the threshold next week."""
        norm = " ".join((phrase or "").split()).lower()
        with self._lock:
            hit = self._phrases.pop(norm, None) is not None
            if hit:
                self._candidates.pop(norm, None)
        if hit:
            self._touch(urgent=True)
        return hit

    def clear(self) -> None:
        with self._lock:
            self._candidates.clear()
            self._phrases.clear()
            self._fumbled.clear()
        self._touch(urgent=True)

    def stats(self) -> tuple:
        with self._lock:
            return len(self._phrases), len(self._candidates)


# ── Boosting ─────────────────────────────────────────────────────────────────

def hotwords(phrases, limit: int = MAX_HOTWORDS) -> str:
    """Comma-joined phrases for the whisper decoder's `hotwords=`.

    Capped, most-said first. Parakeet is deliberately NOT given these: its
    `hotwords_str` only drives a per-term casing regex over the finished text,
    so two hundred learned phrases would buy nothing and cost two hundred
    regex passes on every dictation.
    """
    rows = list(phrases or [])
    if rows and isinstance(rows[0], dict):
        rows.sort(key=lambda r: -(r.get("count") or 0))
    out, seen = [], set()
    for row in rows:
        text = row.get("phrase") if isinstance(row, dict) else str(row)
        text = " ".join((text or "").split())
        low = text.lower()
        if not text or low in seen:
            continue
        seen.add(low)
        out.append(text)
        if len(out) >= limit:
            break
    return ", ".join(out)


def _span_is_unsure(conf, i, size) -> bool:
    """True when the engine hedged on this span. Every word must have a known
    confidence — an unknown one means the alignment lost the thread there, and
    guessing over a span we cannot see is exactly what this must not do."""
    vals = []
    for k in range(i, i + size):
        c = conf[k] if k < len(conf) else None
        if c is None:
            return False
        vals.append(c)
    if not vals:
        return False
    return (sum(vals) / len(vals)) < RESCUE_CONF


def apply_learned_phrases(text: str, phrases, word_conf=None) -> str:
    """Rewrite low-confidence spans that SOUND like something this user says.

    The same phonetic machinery as the vocabulary safety net, with two extra
    locks: the span must be one the engine itself was unsure about, and the
    similarity floor is the strict one. No-op without learned phrases, without
    confidence, or without the (optional) metaphone encoder.
    """
    if not text or not phrases:
        return text
    conf = list(word_conf or [])
    if not any(c is not None for c in conf):
        return text
    dm = _dm()
    if dm is None:
        return text

    terms = []
    seen = set()
    for row in phrases:
        phrase = row.get("phrase") if isinstance(row, dict) else str(row)
        phrase = " ".join((phrase or "").split())
        low = phrase.lower()
        if not phrase or low in seen:
            continue
        words = low.split()
        # Re-apply the learning filter at USE time as well. A store written by
        # an older build, or hand-edited, must not be able to smuggle in a
        # single common word and start rewriting ordinary speech.
        if not is_learnable(words):
            continue
        seen.add(low)
        try:
            codes = dm(low.replace(" ", ""))
        except Exception:
            continue
        if codes and codes[0]:
            terms.append((phrase, low, codes))
    if not terms:
        return text

    tokens = list(_WORD_RE.finditer(text))
    if not tokens:
        return text

    term_first = {c[0] for _p, _l, codes in terms for c in codes if c}
    word_low = [normalise_word(t.group(0)) for t in tokens]
    word_dm = []
    for w in word_low:
        try:
            word_dm.append(dm(w) if w else ("", ""))
        except Exception:
            word_dm.append(("", ""))

    replacements = []
    consumed = [False] * len(tokens)
    for size in range(MAX_PHRASE_WORDS, 0, -1):
        for i in range(0, len(tokens) - size + 1):
            wp = word_dm[i][0]
            if not wp or wp[0] not in term_first:
                continue
            if any(consumed[i:i + size]):
                continue
            if not _span_is_unsure(conf, i, size):
                continue
            span = tokens[i:i + size]
            gaps_ok = all(
                text[span[k].end():span[k + 1].start()].strip() == ""
                for k in range(size - 1)
            )
            if not gaps_ok:
                continue
            # A span is only a candidate if it could itself have been learned
            # as a phrase — same rule, one definition. That is what stops a
            # match reaching over a function word at either edge ("to main",
            # "really a", "whatever you"), which is where every measured
            # corruption came from.
            cand_words = word_low[i:i + size]
            if not is_learnable(cand_words):
                continue
            cand_low = " ".join(cand_words)
            cand_key = cand_low.replace(" ", "")
            try:
                cand_codes = word_dm[i] if size == 1 else dm(cand_key)
            except Exception:
                continue
            best, best_jw = None, 0.0
            for phrase, low, codes in terms:
                if cand_low == low:
                    best = None
                    break
                if not _phonetic_match(codes, cand_codes):
                    continue
                term_key = low.replace(" ", "")
                lr = len(cand_key) / float(len(term_key) or 1)
                if not (RESCUE_LEN_LO <= lr <= RESCUE_LEN_HI):
                    continue
                jw = _jaro_winkler(cand_key, term_key)
                floor = RESCUE_JW
                if len(low.split()) != size:
                    # Re-splitting words, not just re-spelling them.
                    if len(term_key) < len(cand_key):
                        continue        # the phrase is short a letter the
                                        # user said — that is a deletion
                    floor = RESCUE_SPLIT_JW
                if jw >= floor and jw > best_jw:
                    best, best_jw = phrase, jw
            if best is not None:
                start, end = span[0].start(), span[-1].end()
                replacements.append((start, end, _cased(best, text, start)))
                for k in range(i, i + size):
                    consumed[k] = True

    if not replacements:
        return text
    replacements.sort()
    out, pos = [], 0
    for start, end, rep in replacements:
        out.append(text[pos:start])
        out.append(rep)
        pos = end
    out.append(text[pos:])
    return "".join(out)
