"""
The AI accuracy check and paragraph planner, run WHILE the user is speaking.

Echo's stop must stay instant, so nothing here ever runs at the release. While
the user talks, the streaming session hands over its text so far (`feed`). A
background thread checks each finished sentence once (`context_fix` with the
speaker's names) and, every few sentences, asks where the paragraphs go. At the
release the app calls `apply_fixes` and `apply_paragraphs`, which only read
what is already known: no network, no wait.

Fixes are kept as small word swaps with the words either side ("and clawed
or" -> "and Claude or"), not as whole sentences, because the final decode can
differ from the text heard mid-speech in punctuation or a word elsewhere in
the sentence; a swap whose surrounding words are still there still applies.
Paragraph breaks are kept as the first words of each sentence that starts one.

Whatever was not checked before the release (usually the last sentence) is
left as the engine wrote it and the app offers the usual post-paste check.
"""

import difflib
import re
import threading
import time
from typing import Callable, Optional

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=\S)")
_PUNCT = ".,!?;:\"'()"
_KEY_WORDS = 6


def _bare(w: str) -> str:
    return w.strip(_PUNCT).lower()


def sentences(text: str) -> list:
    return [s for s in _SENT_SPLIT.split((text or "").strip()) if s.strip()]


def _norm(s: str) -> str:
    return " ".join(_bare(w) for w in s.split() if _bare(w))


def sentence_key(s: str) -> str:
    return " ".join(_norm(s).split()[:_KEY_WORDS])


class _Swap:
    __slots__ = ("left", "old", "right", "new")

    def __init__(self, left, old, right, new):
        self.left, self.old, self.right, self.new = left, old, right, new

    def __repr__(self):
        return f"<{self.left} [{' '.join(self.old)}] {self.right} -> {' '.join(self.new)}>"


def derive_swaps(before: str, after: str) -> list:
    """Small word swaps that turn `before` into `after`, each with the bare
    words either side of it. Insertions and deletions are dropped (the check
    may not add or remove words), as is any swap touching a number."""
    a = before.split()
    b = after.split()
    ab = [_bare(w) for w in a]
    bb = [_bare(w) for w in b]
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ab, bb, autojunk=False).get_opcodes():
        if op != "replace":
            continue
        if not (1 <= i2 - i1 <= 4 and 1 <= j2 - j1 <= 4):
            continue
        old = tuple(ab[i1:i2])
        new = tuple(w.strip(_PUNCT) for w in b[j1:j2])
        if any(re.search(r"\d", w) for w in old + new):
            continue
        if not all(old) or not all(new):
            continue
        # Words may join into a name ("chat gbt" -> "ChatGPT", "pine cone" ->
        # "Pinecone") or split, but only when the letters still spell it.
        # "clawed cloud" -> "Claude" and "has cloud" -> "Claude" drop a word
        # the speaker said (real-model check, 2026-11-20). Same for a swap of
        # several words at once: "clawed cloud" -> "Claude Code" (a claw
        # shaped cloud in a Halloween scene) rewrote two words.
        if len(old) > 1 or len(new) > 1:
            a_l = "".join(old)
            b_l = "".join(w.lower() for w in new)
            if difflib.SequenceMatcher(None, a_l, b_l).ratio() < 0.75:
                continue
        left = ab[i1 - 1] if i1 > 0 else None
        right = ab[i2] if i2 < len(ab) else None
        out.append(_Swap(left, old, right, new))
    return out


def _is_listed(words, names_block: str, left=None, right=None) -> bool:
    """Whether the swapped-in words are exactly one of the NAMES handed to the
    check: only the comma-separated list after vocab_context.LIST_MARK, never
    the block's own wording (a search of the whole block let "there" ->
    "here" through because the header says "written here", review
    2026-11-20)."""
    phrase = " ".join(words).strip().lower()
    if not phrase or not names_block:
        return False
    import vocab_context
    names = [n.lower() for n in vocab_context.listed_names(names_block)]
    if phrase in names:
        return True
    # Part of a longer name, with the rest of that name right beside it:
    # "John Smit" -> "John Smith" swaps only "Smith" (review 2026-11-20).
    new = [_bare(w) for w in words]
    for n in names:
        parts = [_bare(w) for w in n.split()]
        k = len(new)
        for i in range(len(parts) - k + 1):
            if parts[i:i + k] != new:
                continue
            if (i > 0 and left == parts[i - 1]) or (
                    i + k < len(parts) and right == parts[i + k]):
                return True
    return False


def apply_swaps(text: str, swaps) -> tuple:
    """Apply each swap wherever its words AND its neighbours appear. Returns
    (text, number applied). Line breaks are kept: only spaces inside a line
    are ever rewritten."""
    if not text or not swaps:
        return text, 0
    lines = text.split("\n")
    applied = 0
    for li, line in enumerate(lines):
        toks = line.split(" ")
        bare = [_bare(t) for t in toks]
        for sw in swaps:
            n = len(sw.old)
            i = 0
            while i + n <= len(toks):
                if tuple(bare[i:i + n]) != sw.old:
                    i += 1
                    continue
                left_ok = (sw.left is None and i == 0) or (i > 0 and bare[i - 1] == sw.left)
                right_ok = ((sw.right is None and i + n == len(toks))
                            or (i + n < len(toks) and bare[i + n] == sw.right))
                if not (left_ok and right_ok):
                    i += 1
                    continue
                first, last = toks[i], toks[i + n - 1]
                lead = first[:len(first) - len(first.lstrip(_PUNCT))]
                trail = last[len(last.rstrip(_PUNCT)):]
                new = list(sw.new)
                # A plain lower-case word that opens a sentence keeps its capital.
                if new[0] == new[0].lower() and first.lstrip(_PUNCT)[:1].isupper():
                    new[0] = new[0][:1].upper() + new[0][1:]
                new[0] = lead + new[0]
                new[-1] = new[-1] + trail
                toks[i:i + n] = new
                bare[i:i + n] = [_bare(w) for w in new]
                applied += 1
                i += len(new)
        lines[li] = " ".join(toks)
    return "\n".join(lines), applied


class SpeculativeFixer:
    """One per dictation. Thread-safe: `feed` from the stream thread, the rest
    from the app's pipeline thread."""

    MIN_GAP = 2.0          # seconds between AI calls (relay: 60 per 5 minutes)
    MAX_CALLS = 20         # per dictation, fixes and paragraph plans together
    PLAN_EVERY = 3         # new finished sentences before the plan is redone
    PLAN_MIN = 4           # finished sentences before the first plan

    def __init__(self, refiner, names_for: Callable[[str], str],
                 paragraphs: bool = True, fixes: bool = True):
        self._refiner = refiner
        self._names_for = names_for
        self._want_paras = bool(paragraphs)
        self._want_fixes = bool(fixes)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopped = False
        self._latest = ""
        self._checked: set = set()          # _norm of sentences already checked
        self._swaps: list = []
        self._break_keys: set = set()
        self._planned_keys: set = set()     # every sentence the latest plan saw
        self._planned_n = 0
        self._calls = 0
        self._last_call = 0.0
        self.stats = {"fix_calls": 0, "plan_calls": 0, "failed": 0}
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="speculative-fix")
        self._thread.start()

    # ── stream side ──────────────────────────────────────────────────────
    def feed(self, text_so_far: str) -> None:
        with self._lock:
            if self._stopped:
                return
            self._latest = text_so_far or ""
        self._wake.set()

    # ── worker ───────────────────────────────────────────────────────────
    def _run(self) -> None:
        while True:
            self._wake.wait(0.5)
            self._wake.clear()
            with self._lock:
                if self._stopped:
                    return
                text = self._latest
            try:
                self._step(text)
            except Exception as exc:   # never lose the dictation over this
                self.stats["failed"] += 1
                print(f"[SpecFix] step failed: {type(exc).__name__}: {exc}")

    def _budget_ok(self) -> bool:
        return (self._calls < self.MAX_CALLS
                and time.monotonic() - self._last_call >= self.MIN_GAP)

    def _spend(self) -> None:
        self._calls += 1
        self._last_call = time.monotonic()

    def _step(self, text: str) -> None:
        sents = sentences(text)
        done = sents[:-1]            # the last one may still be being spoken
        if not done:
            return
        if self._want_fixes and self._budget_ok():
            fresh = [i for i, s in enumerate(done) if _norm(s) not in self._checked]
            if fresh:
                first = fresh[0]
                ctx = done[max(0, first - 2):first]
                batch_s = ctx + [done[i] for i in fresh]
                batch = " ".join(batch_s)
                self._spend()
                self.stats["fix_calls"] += 1
                names = self._names_for(batch) or ""
                fixed = self._refiner.context_fix(batch, names)
                # Kept even after stop(): a fix that lands during the tail
                # decode is still read by apply_fixes.
                if (fixed or "") and fixed != batch:
                    # Only swaps INTO a listed name or work word are applied
                    # without asking. The real model also "fixed" plain words
                    # wrongly ("all clawed" -> "all crashed", "moon" ->
                    # "mood"); those stay the pop-up offer's job, where the
                    # user decides.
                    swaps = [w for w in derive_swaps(batch, fixed)
                             if _is_listed(w.new, names, w.left, w.right)]
                    with self._lock:
                        self._swaps.extend(swaps)
                    if swaps:
                        print(f"[SpecFix] {len(swaps)} fix(es) ready: {swaps}")
                if getattr(self._refiner, "last_relay_error", "") in ("", None):
                    with self._lock:
                        for i in fresh:
                            self._checked.add(_norm(done[i]))
                else:
                    # Rate limited or offline: stop asking for this dictation.
                    self._calls = self.MAX_CALLS
                return
        if (self._want_paras and len(done) >= self.PLAN_MIN
                and len(done) - self._planned_n >= self.PLAN_EVERY and self._budget_ok()):
            self._spend()
            self.stats["plan_calls"] += 1
            idx = self._refiner.plan_paragraphs(done)
            if idx is None:
                return
            with self._lock:
                self._break_keys = {sentence_key(done[i]) for i in idx}
                self._planned_keys = {sentence_key(s) for s in done}
                self._planned_n = len(done)
            print(f"[SpecFix] paragraph plan: {len(idx)} break(s) over {len(done)} sentences")

    # ── release side (never waits) ───────────────────────────────────────
    def stop(self) -> None:
        with self._lock:
            self._stopped = True
        self._wake.set()

    def apply_fixes(self, final_text: str) -> tuple:
        """(text, swaps applied, sentences checked, sentences total)."""
        with self._lock:
            swaps = list(self._swaps)
            checked = set(self._checked)
        out, n = apply_swaps(final_text, swaps)
        sents = sentences(final_text.replace("\n", " "))
        hit = sum(1 for s in sents if _norm(s) in checked)
        return out, n, hit, len(sents)

    def paragraph_plan(self) -> tuple:
        """(break keys, keys the plan covered)."""
        with self._lock:
            return set(self._break_keys), set(self._planned_keys)


def apply_paragraphs(text: str, break_keys: set, covered_keys: set,
                     local_rules: Optional[Callable] = None) -> str:
    """Put a blank line before each sentence the plan said starts a
    paragraph; for the sentences the plan never saw (the tail), the local
    rules decide. Text that already has single line breaks (a list, an email
    layout) is left exactly as it is."""
    if not text or re.search(r"(?<!\n)\n(?!\n)", text):
        return text
    paras = text.split("\n\n")
    out_paras = []
    for para in paras:
        sents = sentences(para)
        if not sents:
            out_paras.append(para)
            continue
        groups = [[sents[0]]]
        for s in sents[1:]:
            k = sentence_key(s)
            if k in break_keys:
                groups.append([s])
            else:
                groups[-1].append(s)
        out_paras.extend(" ".join(g) for g in groups)
    joined = "\n\n".join(out_paras)
    if local_rules is not None:
        joined = local_rules(joined, covered_keys)
    return joined
