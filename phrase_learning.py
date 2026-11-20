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
import brand
import data_paths
import os
import re
import threading
import time
from datetime import datetime, timezone

# Primitives shared with the hand-typed vocabulary path. Imported rather than
# copied so the phonetic firewall, the common-word list and the sentence-casing
# rule can only ever have one definition — a second copy that drifted is how a
# safety gate quietly stops being a gate.
from text_expansion import (_COMMON_WORDS, _FUNCTION_WORDS, _WORD_RE, _cased,
                            _dm, _jaro_winkler, _phonetic_match)

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
MAX_PHRASES = 200           # promoted ceiling, for phrases LEARNED from speech
# Starter terms user_context seeds (tech words, product names) have their own
# ceiling. They used to share MAX_PHRASES at a seeded count of 40-50, so once
# the seed list filled the table every newly learned phrase (promoted at 4) was
# the lowest row and was pruned the moment it was promoted, its counter already
# gone: on Ryan's PC 183 of the 200 slots were seeds and nothing new had been
# learned since the seed landed (26 Oct 2026).
MAX_SEEDED = 400

# ── Habits: the whole phrases a person says over and over ────────────────────
#
# A learned phrase (above) is a NAME-like unit: edges and insides must be
# distinctive, so "pushed to main" can never be one ("to" is a function word).
# But the commands someone repeats all day are exactly that shape, and the
# engine slips on the small word inside them: Ryan says "push everything to
# main" or "pushed to main" in most dictations, and in four days it came out
# "to mean", "to me", "domain" and "Two main". A habit is a 3-5 word run with
# content words at both ends and anything in between, counted from confidently
# heard speech. It repairs ONE slipped word inside a run where every other word
# matches exactly, so the context on both sides is what proves the repair.
HABIT_MIN_WORDS = 3
HABIT_MAX_WORDS = 5
HABIT_MIN_CHARS = 10
MAX_HABITS = 5000           # windows are cheap; the cap only has to outlast
                            # the gap between two times a habit is said
# Repair a word the engine was UNSURE of (< LEARN_CONF) once the habit has been
# heard this often...
HABIT_REPAIR_COUNT = 5
# ...and a word it was SURE of only when the habit is said all the time and the
# variant it heard is at most an eighth as common. Measured: "push it to me"
# came back at 0.97, so a hedging-only gate cannot reach the commonest slip.
# Not "never heard": a slip heard confidently before the habit reached 15 is
# counted as a variant, and "never" would then block that repair for good.
HABIT_STRONG_COUNT = 15
HABIT_STRONG_RATIO = 8
# The variant the engine wrote must be at least this many times rarer than the
# habit, or it is something the person also says and is left alone.
HABIT_RATIO = 4
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


def is_habit(words) -> bool:
    """True when this run of normalised words can be a habit: 3-5 words,
    no digits, a content word at each END (a run that starts or stops on
    "to"/"the" is a fragment of a sentence, not something anybody says), and
    at least one word that is not ordinary English, so "make sure that"-style
    filler never becomes a frame that rewrites other people's sentences."""
    if not words or not (HABIT_MIN_WORDS <= len(words) <= HABIT_MAX_WORDS):
        return False
    if any(not w or any(ch.isdigit() for ch in w) for w in words):
        return False
    # A quote mark stuck to a word ("'verified") is punctuation the run picked
    # up, not part of anything said.
    if any(w[0] == "'" or w[-1] == "'" for w in words):
        return False
    if words[0] in _FUNCTION_WORDS or words[-1] in _FUNCTION_WORDS:
        return False
    if all(w in _COMMON_WORDS for w in words):
        return False
    return sum(len(w) for w in words) >= HABIT_MIN_CHARS


def _looks_seeded(rows: dict) -> set:
    """Norms of rows written by an old user_context seed (before rows carried
    `seeded`). A seed writes every starter term in one go with one timestamp
    and a count of 40 or more; a real promotion never lands twenty phrases in
    the same second."""
    by_at = {}
    for norm, row in rows.items():
        if (row.get("count") or 0) >= 40 and row.get("learned_at"):
            by_at.setdefault(row["learned_at"], []).append(norm)
    out = set()
    for norms in by_at.values():
        if len(norms) >= 20:
            out.update(norms)
    return out


def _is_variant(words, index: dict) -> bool:
    """Is this run one word away from a usable habit (see build_habit_index)?"""
    if any(not w or any(ch.isdigit() for ch in w) for w in words):
        return False
    for j in range(len(words)):
        key = tuple(words[:j]) + ("*",) + tuple(words[j + 1:])
        for _norm, target in index.get(key, ()):
            if target.replace(" ", "") != words[j]:
                return True
    return False


def _row(row: dict, phrase: str) -> dict:
    out = {
        "phrase": phrase,
        "count": int(row.get("count") or 0),
        "learned_at": str(row.get("learned_at") or ""),
    }
    if row.get("seeded"):
        out["seeded"] = True
    return out


def _load_counts(raw) -> dict:
    out = {}
    for norm, row in (raw.items() if isinstance(raw, dict) else ()):
        try:
            out[str(norm)] = [int(row[0]), str(row[1])]
        except (TypeError, ValueError, IndexError):
            continue
    return out


# ── The store ────────────────────────────────────────────────────────────────

def _safe_name(key: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "_", (key or "_local").lower())[:80] or "_local"


def store_dir() -> str:
    return os.path.join(data_paths.local_dir(), "phrases")


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
        # Phrases the user told us to forget, with when. Only matters to
        # Cloud Sync: without it, another PC still holding the phrase would
        # hand it straight back on the next merge.
        self._forgotten = {}        # norm -> iso
        # Habit runs (see is_habit) -> [count, last_iso]. Dictated fragments,
        # so they live on THIS PC only: never in snapshot(), never synced.
        self._habits = {}
        self._habit_gen = 0         # bumped when the usable set may change
        self._habit_index = None    # (gen, build_habit_index result)
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
                self._phrases[norm] = _row(row, phrase)
        forg = data.get("forgotten")
        if isinstance(forg, dict):
            self._forgotten = {str(k): str(v) for k, v in forg.items()}
        self._habits = _load_counts(data.get("habits"))
        self._mark_legacy_seeds()

    def _mark_legacy_seeds(self) -> None:
        for norm in _looks_seeded(self._phrases):
            self._phrases[norm]["seeded"] = True

    def _snapshot(self, habits: bool = True) -> dict:
        data = {
            "version": _STORE_VERSION,
            "candidates": {k: list(v) for k, v in self._candidates.items()},
            "fumbled": dict(self._fumbled),
            "phrases": [dict(v) for v in self._phrases.values()],
            "forgotten": dict(self._forgotten),
        }
        if habits:
            data["habits"] = {k: list(v) for k, v in self._habits.items()}
        return data

    def snapshot(self) -> dict:
        """A copy of what Cloud Sync may carry. Habits are left out: they are
        runs of what was dictated, and stay on this PC whatever the switch."""
        with self._lock:
            return self._snapshot(habits=False)

    def replace_with(self, data: dict) -> None:
        """Adopt a merged snapshot (Cloud Sync pulled one) and save it."""
        if not isinstance(data, dict):
            return
        with self._lock:
            self._candidates, self._fumbled = {}, {}
            self._phrases, self._forgotten = {}, {}
            cands = data.get("candidates")
            for norm, row in (cands.items() if isinstance(cands, dict) else ()):
                try:
                    self._candidates[norm] = [int(row[0]), str(row[1])]
                except (TypeError, ValueError, IndexError):
                    continue
            fum = data.get("fumbled")
            for code, n in (fum.items() if isinstance(fum, dict) else ()):
                try:
                    self._fumbled[str(code)] = int(n)
                except (TypeError, ValueError):
                    continue
            for row in data.get("phrases") or []:
                if isinstance(row, dict) and row.get("phrase"):
                    phrase = " ".join(row["phrase"].split())
                    self._phrases[phrase.lower()] = _row(row, phrase)
            forg = data.get("forgotten")
            if isinstance(forg, dict):
                self._forgotten = {str(k): str(v) for k, v in forg.items()}
            # Habits never travel (see snapshot), so the local ones survive.
            self._mark_legacy_seeds()
            self._prune()
        self._touch(urgent=True)

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
        # user_context writes its seed straight into _phrases and prunes, so
        # the seed has to be recognised here, before the budgets are applied.
        self._mark_legacy_seeds()
        learned = {k: v for k, v in self._phrases.items() if not v.get("seeded")}
        seeded = {k: v for k, v in self._phrases.items() if v.get("seeded")}
        if len(learned) > MAX_PHRASES or len(seeded) > MAX_SEEDED:
            def _top(rows, n):
                return sorted(rows.items(),
                              key=lambda kv: kv[1].get("count") or 0,
                              reverse=True)[:n]
            self._phrases = dict(_top(learned, MAX_PHRASES)
                                 + _top(seeded, MAX_SEEDED))
        if len(self._habits) > MAX_HABITS:
            keep = sorted(self._habits.items(),
                          key=lambda kv: (kv[1][0], kv[1][1]),
                          reverse=True)[:MAX_HABITS]
            self._habits = dict(keep)

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

    def _count_habits(self, run, conf) -> None:
        """Count every habit-shaped window of one run whose words were ALL
        heard confidently. MUST hold self._lock."""
        n = len(run)
        sure = []
        for idx, _w in run:
            c = conf[idx] if idx < len(conf) else None
            sure.append(c is not None and c >= LEARN_CONF)
        now = None
        # The last index built, for spotting VARIANTS: a confidently heard run
        # one word away from a usable habit ("pushed to me" beside "pushed to
        # main") is counted even though it cannot be a habit itself, because
        # that count is what tells apply_habits the person really says it.
        index = self._habit_index[1] if self._habit_index else {}
        for size in range(HABIT_MIN_WORDS - 1, min(HABIT_MAX_WORDS, n) + 1):
            for start in range(0, n - size + 1):
                if not all(sure[start:start + size]):
                    continue
                words = [w for _i, w in run[start:start + size]]
                norm = " ".join(words)
                if self._is_forgotten(norm):
                    continue
                if not is_habit(words):
                    if not (index and _is_variant(words, index)):
                        continue
                row = self._habits.get(norm)
                if row is None:
                    row = [0, ""]
                    self._habits[norm] = row
                row[0] += 1
                row[1] = now = now or _now()
                if row[0] == HABIT_REPAIR_COUNT:
                    self._habit_gen += 1    # a new habit became usable

    def _is_forgotten(self, norm: str) -> bool:
        """A run holding a phrase the user told us to forget is not learned
        again as a habit. MUST hold self._lock."""
        if not self._forgotten:
            return False
        padded = f" {norm} "
        return any(f" {f} " in padded for f in self._forgotten)

    def forgotten_norms(self) -> tuple:
        with self._lock:
            return tuple(self._forgotten)

    def habit_counts(self) -> dict:
        """norm -> times heard confidently. A copy, for apply_habits."""
        with self._lock:
            return {k: v[0] for k, v in self._habits.items()}

    def habit_index(self) -> dict:
        """build_habit_index over this store, rebuilt only when a habit first
        becomes usable, so a dictation pays for a lookup, not a rebuild."""
        with self._lock:
            if self._habit_index is not None and self._habit_index[0] == self._habit_gen:
                return self._habit_index[1]
            gen = self._habit_gen
            counts = {k: v[0] for k, v in self._habits.items()}
        index = build_habit_index(counts)
        with self._lock:
            self._habit_index = (gen, index)
        return index

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
                self._count_habits(run, conf)
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
                self._forgotten[norm] = _now()
                # Forget reaches habits too, or the forgotten phrase would go
                # on repairing other words into itself.
                padded = f" {norm} "
                for h in [h for h in self._habits if padded in f" {h} "]:
                    del self._habits[h]
                self._habit_gen += 1
        if hit:
            self._touch(urgent=True)
        return hit

    def clear(self) -> None:
        with self._lock:
            now = _now()
            for norm in self._phrases:
                self._forgotten[norm] = now
            self._candidates.clear()
            self._phrases.clear()
            self._fumbled.clear()
            self._habits.clear()
            self._habit_gen += 1
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


# ── Habit repair ─────────────────────────────────────────────────────────────

def _sounds_close(said: str, target: str, dm, nasal: bool) -> bool:
    """Does the word the engine wrote sound like the habit's word(s)?

    Equal Double Metaphone codes ("mean"/"main", "domain"/"to main",
    "two"/"to"). With `nasal`, also a swallowed final nasal: the habit's code
    is the written one plus a closing N or M and both start with the same
    letter ("me" M for "main" MN). Only a nasal: any other extra sound turned
    "go" into "gate" in the corpus run, and an extra sound in what was WRITTEN
    is evidence of a different word, never a slip."""
    try:
        cs = [c for c in dm(said) if c]
        ct = [c for c in dm(target.replace(" ", "")) if c]
    except Exception:
        return False
    if not cs or not ct:
        return False
    if set(cs) & set(ct):
        return True
    if not nasal or said[:1] != target[:1]:
        return False
    return any(t[:-1] == s and t[-1] in "NM" for s in cs for t in ct)


# Endings that make one word another form of the same word. "push" for
# "pushed" or "Claude" for "Claude's" is a different thing said, not a slip,
# and the corpus run turned "a push to main deploys" into "a pushed to main".
_INFLECTIONS = ("s", "es", "'s", "d", "ed", "ing", "er", "ers", "ly", "n")


def _inflected(a: str, b: str) -> bool:
    """Another form of the same word: a regular ending ("push"/"pushed") or a
    one-vowel tense change ("ran"/"run", "sit"/"sat"). "mean"/"main" differ in
    two letters and stay a candidate."""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if long_.startswith(short) and long_[len(short):] in _INFLECTIONS:
        return True
    if len(a) == len(b):
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        if len(diff) == 1 and diff[0][0] in "aeiou" and diff[0][1] in "aeiou":
            return True
    return False


def _recase(target: str, text: str, start: int) -> str:
    """Capital only where a sentence starts. A capital the engine put on the
    slipped word mid-sentence ("Two main", "to Maine") is part of its mistake,
    the same finding as homophones.py ("Revenue One this quarter")."""
    return _cased(target, text, start)


def build_habit_index(habits: dict) -> dict:
    """Wildcard skeletons of every usable habit, for apply_habits.

    ("push", "everything", "to", "*") -> [(habit norm, slot word)]. A
    substitution keeps the habit's length; a merge is one word short, its
    wildcard standing for two adjacent habit words ("domain" for "to main").
    Counts are NOT baked in: apply_habits reads them live, so the index only
    has to be rebuilt when a habit first becomes usable."""
    skel = {}
    for norm, count in (habits or {}).items():
        if count < HABIT_REPAIR_COUNT:
            continue
        words = norm.split()
        if not is_habit(words):
            continue
        n = len(words)
        for k in range(n):
            key = tuple(words[:k]) + ("*",) + tuple(words[k + 1:])
            skel.setdefault(key, []).append((norm, words[k]))
        for k in range(n - 1):
            key = tuple(words[:k]) + ("*",) + tuple(words[k + 2:])
            skel.setdefault(key, []).append(
                (norm, words[k] + " " + words[k + 1]))
    return skel


def apply_habits(text: str, habits: dict, word_conf=None, index=None,
                 forgotten=(), heard=None) -> str:
    """Repair one slipped word inside a phrase this person says all the time.

    `habits` is PhraseStore.habit_counts(), `index` its habit_index() (built
    here when not given). A window of the text is repaired to habit H only
    when every word but one matches H exactly and in order, with nothing but
    spaces between them, and the odd word out:
      * sounds like H's word in that place (see _sounds_close), or is one word
        of the same length and sound standing for two of H's ("domain");
      * in a substitution, is replaced by a word that is NOT ordinary English
        ("main", "absolutely"), is not another form of it ("push"/"pushed"),
        and has two anchors either side: swapping one everyday word for
        another ("was"/"is", "like"/"look", "rule"/"real") is a different
        sentence, not a slip, and every such swap in the corpus run was wrong;
      * sits among anchors that are not all ordinary English;
      * carries no digit, and neither does its replacement;
      * belongs to a variant run heard at most 1/HABIT_RATIO as often as H;
      * was heard UNSURELY and H has been said HABIT_REPAIR_COUNT times, or was
        heard surely but H has been said HABIT_STRONG_COUNT times and the
        variant never once.
    No confidence at all for the dictation, or none for that word, means no
    repair: an alignment that lost the thread must not guess. A repair that
    would spell out a phrase in `forgotten` (PhraseStore.forgotten_norms) is
    refused: Forget means the app stops producing it, by any route.

    `heard`, when a list, receives (window text, its confidences) for every
    window repaired although its odd word was heard SURELY: the caller counts
    what was really said, so a variant the person truly says ("pushed to me")
    builds up its own count and stops being repaired. Counted only after the
    repair, it never got one (2026-11-20 audit).
    """
    if not text or not habits:
        return text
    conf = list(word_conf or [])
    if not any(c is not None for c in conf):
        return text
    dm = _dm()
    if dm is None:
        return text
    skel = index if index is not None else build_habit_index(habits)
    if not skel:
        return text
    lengths = sorted({len(k) for k in skel}, reverse=True)

    tokens = list(_WORD_RE.finditer(text))
    low = [normalise_word(t.group(0)) for t in tokens]
    # Run id per token: a window may not straddle punctuation.
    run_of, run = [], 0
    for q, t in enumerate(tokens):
        if q and text[tokens[q - 1].end():t.start()].strip():
            run += 1
        run_of.append(run)
    codes = {}

    def _close(said, target, nasal):
        key = (said, target, nasal)
        if key not in codes:
            codes[key] = _sounds_close(said, target, dm, nasal)
        return codes[key]

    consumed = [False] * len(tokens)
    replacements = []
    for i in range(len(tokens)):
        if consumed[i]:
            continue
        for size in lengths:
            end = i + size
            if end > len(tokens) or run_of[i] != run_of[end - 1]:
                continue
            if any(consumed[i:end]):
                continue
            window = low[i:end]
            if not all(window):
                continue
            best = None
            for j in range(size):
                cands = skel.get(tuple(window[:j]) + ("*",) + tuple(window[j + 1:]))
                if not cands:
                    continue
                anchors = window[:j] + window[j + 1:]
                if all(w in _COMMON_WORDS for w in anchors):
                    continue
                said = window[j]
                c = conf[i + j] if i + j < len(conf) else None
                if c is None:
                    continue
                for norm, target in cands:
                    count = habits.get(norm, 0)
                    if count < HABIT_REPAIR_COUNT:
                        continue
                    merge = " " in target
                    if said.replace(" ", "") == target.replace(" ", ""):
                        continue
                    if any(ch.isdigit() for ch in said + target):
                        continue
                    if merge:
                        lr = len(said) / float(len(target.replace(" ", "")))
                        if not (RESCUE_LEN_LO <= lr <= RESCUE_LEN_HI):
                            continue
                        # "asked" is not "ask it": a form of one of the two
                        # words is that word said, not two words run together.
                        if any(_inflected(said, w) for w in target.split()):
                            continue
                    elif (len(anchors) < 2 or target in _COMMON_WORDS
                          or _inflected(said, target)):
                        continue
                    variant = habits.get(" ".join(window), 0)
                    if variant * HABIT_RATIO > count:
                        continue
                    if c >= LEARN_CONF and not (
                            count >= HABIT_STRONG_COUNT
                            and variant * HABIT_STRONG_RATIO <= count):
                        continue
                    if not _close(said, target, not merge):
                        continue
                    if forgotten:
                        lo = max(0, i - 3)
                        near = low[lo:i + j] + [target] + low[i + j + 1:end + 3]
                        padded = " " + " ".join(near) + " "
                        if any(f" {f} " in padded for f in forgotten):
                            continue
                    if best is None or count > best[0]:
                        best = (count, i + j, target, c)
            if best is not None:
                _count, at, target, c_said = best
                if heard is not None and c_said >= LEARN_CONF:
                    heard.append((text[tokens[i].start():tokens[end - 1].end()],
                                  conf[i:end]))
                tok = tokens[at]
                replacements.append(
                    (tok.start(), tok.end(), _recase(target, text, tok.start())))
                for q in range(i, end):
                    consumed[q] = True
                break

    if not replacements:
        return text
    replacements.sort()
    out, pos = [], 0
    for start, stop, rep in replacements:
        out.append(text[pos:start])
        out.append(rep)
        pos = stop
    out.append(text[pos:])
    return "".join(out)
