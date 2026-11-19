"""
Voice isolation: drop a colleague's speech before or after the user's own.

In an office the thing that hurts accuracy is other people talking: measured
2026-08-17, a colleague's speech raised word errors to 20/47/83% at 10/5/0 dB
and caused every word the user never said, while music and steady noise barely
mattered. Silero cannot help (a colleague's voice really is speech), and
denoisers make clean dictations worse. So this module learns what the user's
own voice sounds like (a voiceprint, from their own past dictations) and cuts
out a stretch at the START or END of a clip that is confidently somebody else:
the remark from the next desk before the user began, the reply after they
stopped talking but before they let go of the key.

It never cuts inside the user's own speech. The first bench (2026-11-13) cut
short "unlike the user" dips mid-sentence too and changed 8% of the words of
clean dictations; every one of those cuts was the user. Everything here leans
towards keeping audio:
  * nothing is cut unless a window confidently matches the user;
  * a window is only judged when it is mostly speech, so silence, breath and a
    quiet first word are never judged "someone else";
  * a stretch is cut only when every judged window over it sounds unlike the
    user, and KEEP_S of it nearest the user's speech is always kept;
  * no voiceprint yet, a missing or failed model, a clip too short to judge:
    the clip goes through exactly as with voice isolation switched off.

Measured cost is about 0.15 s of CPU per 3 s window. The judging happens
WHILE the user talks (VoiceTrack, fed by stream_session): each window is
embedded on a background thread as soon as it is complete, and the commit and
stop paths only read the cached results, so the stop costs nothing extra. The
first version (2026-11-13) checked at the stop beside the decode and added
0.1-0.3 s median, 1-2 s at p90; it must never come back. Live Typing is never
filtered: its words are typed before a cut could be decided.

The voiceprint never leaves the device. It is stored as numbers only (no audio)
in the local data folder and is deleted when the setting is switched off.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional

import numpy as np

from speaker_embed import MODEL_TAG, SAMPLE_RATE, SpeakerEmbedder

PROFILE_FILE = "voice_profile.json"

# TitaNet judges 3 s windows reliably (bench: user 0.63, others about 0);
# 1.5 s windows overlapped badly.
WIN_S = 3.0
HOP_S = 1.0
# A window is judged only when this share of its 20 ms blocks is speech-level
# (at least a quarter of the clip's loud level, and above SILENCE_RMS).
VOICED_SHARE = 0.5
# An unjudged window with at least this share of speech is not silence: it
# may hold the user's quiet word, so a cut never reaches into it.
SOME_SPEECH = 0.15
SILENCE_RMS = 0.002
# Cosine similarity to the voiceprint. At or above USER_ABOVE a window is the
# user; below OTHER_BELOW it is someone else; between, nobody is sure and the
# window protects everything it covers.
USER_ABOVE = 0.40
OTHER_BELOW = 0.10
# At most this many windows are scanned from each end (about 16 s). A clean
# dictation stops after the first window; only someone else keeps it going.
MAX_SCAN = 14
# A cut must be at least this long, and this much of it nearest the user's
# speech is always kept (a quiet first word right after a colleague).
MIN_CUT_S = 1.0
KEEP_S = 0.5
# The voiceprint needs this many dictations before the filter acts at all.
MIN_ENROLL = 5
# Rolling store: the most recent dictations' voiceprints.
MAX_ENROLL = 60
# A dictation only joins the voiceprint when it already matches it this well
# (once enrolled), so a clip full of a colleague never drags it towards them.
JOIN_ABOVE = 0.40
# Enrolment uses this much audio of a dictation (the model fails past ~2 min).
ENROLL_MIN_S = 3.0
ENROLL_MAX_S = 30.0


class VoiceProfile:
    """The user's voiceprint: recent per-dictation embeddings and their
    robust centre. Thread-safe; saved as numbers only."""

    def __init__(self, path: str, log=print):
        self._path = path
        self._log = log
        self._lock = threading.Lock()
        # Bumped by every delete. A learner that started before a delete (the
        # setting switched off, another account signed in) holds the old
        # number and every write it tries is refused, so nothing it learned
        # can bring a deleted voiceprint back or reach someone else's.
        self.generation = 0
        self._closed = False
        self._vectors: list[np.ndarray] = []
        self._centroid: Optional[np.ndarray] = None
        self.seen: list[str] = []   # dictation files already looked at
        # Whose voice this is: a one-way hash of the signed-in account ("" =
        # not yet known), and since when (unix time) that account's saved
        # dictations count. A voiceprint belongs to one person only.
        self.owner = ""
        self.since = 0.0
        self.last_error = ""
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("model") != MODEL_TAG:
                return  # another model's voiceprint is not comparable
            self._vectors = [np.asarray(v, dtype=np.float32)
                             for v in data.get("vectors", [])][-MAX_ENROLL:]
            self.seen = [str(s) for s in data.get("seen", [])][-1000:]
            self.owner = str(data.get("owner", "") or "")
            self.since = float(data.get("since", 0) or 0)
            self._recompute()
        except FileNotFoundError:
            pass
        except Exception as e:
            self._error(f"voice profile unreadable, starting again: {e}")
            self._vectors = []
            self._centroid = None

    def _error(self, what: str) -> None:
        self.last_error = what
        self._log(f"[VoiceIsolation] {what}")

    def _save(self) -> None:
        if self._closed:
            return
        tmp = self._path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"model": MODEL_TAG, "updated": int(time.time()),
                           "owner": self.owner, "since": self.since,
                           "seen": self.seen[-1000:],
                           "vectors": [[round(float(x), 5) for x in v]
                                       for v in self._vectors]}, fh)
            os.replace(tmp, self._path)
        except Exception as e:
            self._error(f"voice profile not saved: {e}")

    def delete(self, close: bool = False) -> bool:
        """Forget the voiceprint and remove its file. close=True also refuses
        every later write (the feature was switched off). False when the file
        could not be removed."""
        with self._lock:
            self.generation += 1
            self._closed = self._closed or close
            self._vectors = []
            self._centroid = None
            self.seen = []
            self.owner = ""
            self.since = 0.0
            ok = True
            for path in (self._path, self._path + ".tmp"):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
                except Exception as e:
                    ok = False
                    self._error(f"voice profile not deleted: {e}")
            return ok

    def _recompute(self) -> None:
        if len(self._vectors) < MIN_ENROLL:
            self._centroid = None
            return
        m = np.stack(self._vectors)
        c = m.mean(axis=0)
        c /= max(float(np.linalg.norm(c)), 1e-9)
        # Drop the outliers (a clip that was mostly someone else) and re-centre.
        sims = m @ c
        keep = sims >= np.median(sims) - 0.15
        if keep.sum() >= MIN_ENROLL:
            c = m[keep].mean(axis=0)
            c /= max(float(np.linalg.norm(c)), 1e-9)
        self._centroid = c.astype(np.float32)

    @property
    def ready(self) -> bool:
        return self._centroid is not None

    @property
    def count(self) -> int:
        return len(self._vectors)

    def centroid(self) -> Optional[np.ndarray]:
        return self._centroid

    def set_owner(self, owner: str, since: float) -> None:
        with self._lock:
            if self._closed:
                return
            self.owner, self.since = owner, since
            self._save()

    def mark_seen(self, name: str, save: bool = True,
                  generation: Optional[int] = None) -> bool:
        with self._lock:
            if self._closed or (generation is not None and generation != self.generation):
                return False
            self.seen.append(name)
            self.seen = self.seen[-1000:]
            if save:
                self._save()
            return True

    def add(self, vector: Optional[np.ndarray], save: bool = True,
            generation: Optional[int] = None) -> bool:
        """Add one dictation's voiceprint. Once enrolled, only a dictation that
        already sounds like the user joins. A learner holding an old
        generation (a delete happened since it began) is refused."""
        if vector is None:
            return False
        with self._lock:
            if self._closed or (generation is not None and generation != self.generation):
                return False
            if self._centroid is not None and float(vector @ self._centroid) < JOIN_ABOVE:
                return False
            self._vectors.append(np.asarray(vector, dtype=np.float32))
            self._vectors = self._vectors[-MAX_ENROLL:]
            self._recompute()
            if save:
                self._save()
            return True


def _block_levels(audio: np.ndarray) -> np.ndarray:
    n = len(audio) // 320 * 320
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    return np.sqrt(np.mean(np.square(audio[:n].reshape(-1, 320)), axis=1))


def enrol_audio(audio: np.ndarray) -> Optional[np.ndarray]:
    """The part of a dictation used to learn the voice: its speech-level
    blocks, up to ENROLL_MAX_S. None when there is too little speech."""
    lv = _block_levels(audio)
    if not len(lv):
        return None
    floor = max(SILENCE_RMS, 0.25 * float(np.percentile(lv, 90)))
    keep = np.repeat(lv >= floor, 320)
    speech = audio[: len(keep)][keep]
    if len(speech) < ENROLL_MIN_S * SAMPLE_RATE:
        return None
    return speech[: int(ENROLL_MAX_S * SAMPLE_RATE)]


class VoiceFilter:
    """Finds a stretch at either end of a 16 kHz clip that is confidently
    another voice."""

    def __init__(self, embedder: SpeakerEmbedder, profile: VoiceProfile):
        self.embedder = embedder
        self.profile = profile
        self.last_ms = 0
        self.last_removed_s = 0.0
        self.last_windows = 0

    def _sims(self, audio, starts, voiced, centre, cancel):
        """Yield (start, similarity) inward, one window at a time so the scan
        stops paying the moment it has decided; similarity None for a window
        not judged. Raises LookupError when the model is unavailable."""
        win = int(WIN_S * SAMPLE_RATE)
        for s in starts:
            if cancel is not None and cancel.is_set():
                raise LookupError("cancelled")
            share = voiced(s, s + win)
            if share < VOICED_SHARE:
                yield s, None, share
                continue
            embs = self.embedder.embed_many([audio[s:s + win]])
            if embs is None:
                raise LookupError("voice model unavailable")
            self.last_windows += 1
            yield s, float(embs[0] @ centre), share

    def other_spans(self, audio: np.ndarray,
                    cancel: Optional[threading.Event] = None) -> list[tuple[int, int]]:
        """Sample ranges to remove. Empty whenever there is any doubt. A set
        `cancel` stops the check at its next window. Used by the bench and
        the tests; the app judges through VoiceTrack instead."""
        self.last_ms, self.last_removed_s, self.last_windows = 0, 0.0, 0
        centre = self.profile.centroid()
        n = 0 if audio is None else len(audio)
        win, hop = int(WIN_S * SAMPLE_RATE), int(HOP_S * SAMPLE_RATE)
        if centre is None or n < win:
            return []
        started = time.perf_counter()
        lv = _block_levels(audio)
        floor = max(SILENCE_RMS, 0.25 * float(np.percentile(lv, 90)))
        loud = lv >= floor

        def voiced(s, e) -> float:
            seg = loud[s // 320:e // 320]
            return float(np.mean(seg)) if len(seg) else 0.0

        try:
            head = self._scan(audio, list(range(0, n - win + 1, hop))[:MAX_SCAN],
                              voiced, centre, True, cancel)
            tail_starts = list(range(n - win, -1, -hop))[:MAX_SCAN]
            tail = self._scan(audio, tail_starts, voiced, centre, False, cancel)
        except LookupError:
            return []
        finally:
            self.last_ms = int((time.perf_counter() - started) * 1000)
        spans = _to_spans(n, head, tail)
        self.last_removed_s = sum(e - s for s, e in spans) / SAMPLE_RATE
        return spans

    def _scan(self, audio, starts, voiced, centre, forward: bool,
              cancel=None) -> Optional[int]:
        return _scan(self._sims(audio, starts, voiced, centre, cancel), forward)


def _to_spans(n: int, head: Optional[int], tail: Optional[int],
              tail_end: Optional[int] = None) -> list[tuple[int, int]]:
    """The cut ranges from the two scan boundaries, keeping KEEP_S nearest the
    user's speech and dropping a cut shorter than MIN_CUT_S. tail_end stops
    the tail cut short of audio nobody judged (default: the clip's end)."""
    end_at = n if tail_end is None else min(n, tail_end)
    keep, min_cut = int(KEEP_S * SAMPLE_RATE), int(MIN_CUT_S * SAMPLE_RATE)
    spans = []
    if head is not None:            # head = start of the first window not "other"
        end = head - keep
        if end >= min_cut:
            spans.append((0, end))
    if tail is not None:            # tail = end of the last window not "other"
        start = tail + keep
        if end_at - start >= min_cut and (not spans or start > spans[0][1]):
            spans.append((start, end_at))
    return spans


def _scan(items, forward: bool) -> Optional[int]:
    """Walk (start, similarity, speech share) windows inward from one end.
    Returns the boundary of the someone-else stretch (the first protected
    window's near edge), or None when nothing at this end should be cut.
    A similarity of None is a window that was not judged."""
    win = int(WIN_S * SAMPLE_RATE)
    saw_other = False
    boundary: Optional[int] = None
    for s, sim, share in items:
        if sim is None:
            if share < SOME_SPEECH:
                continue        # silence: says nothing either way
            # Too little speech to judge, but not silence: it may be the
            # user's own quiet word, so the cut never reaches it.
            if not saw_other:
                return None
            if boundary is None:
                boundary = s if forward else s + win
            continue
        if sim < OTHER_BELOW:
            if boundary is None:
                saw_other = True
            continue
        # Not confidently someone else. The cut can never go past the
        # first such window (a window over both voices lands here), but
        # keep looking for one that is confidently the user: without it
        # nothing at this end is cut.
        if boundary is None:
            boundary = s if forward else s + win
        if sim >= USER_ABOVE:
            return boundary if saw_other else None
    return None


def subtract(chunks: list[dict], spans: list[tuple[int, int]],
             min_piece: int) -> list[dict]:
    """Speech regions minus the removed spans. Pieces shorter than min_piece go."""
    if not spans:
        return chunks
    out = []
    for c in chunks:
        pieces = [(int(c["start"]), int(c["end"]))]
        for s, e in spans:
            nxt = []
            for a, b in pieces:
                if e <= a or s >= b:
                    nxt.append((a, b))
                    continue
                if s > a:
                    nxt.append((a, s))
                if e < b:
                    nxt.append((e, b))
            pieces = nxt
        out.extend({"start": a, "end": b} for a, b in pieces if b - a >= min_piece)
    return out


class VoiceTrack:
    """Judges one dictation's voice WHILE it is being recorded.

    The streaming session feeds every new sample in (feed); a background
    thread embeds each 3 s window on a fixed 1 s grid as soon as it is
    complete and keeps only its similarity to the voiceprint. At the commit
    of a chunk and at the stop, spans() runs the same edge-only decision as
    VoiceFilter.other_spans over those cached results, with no model call, so
    the stop path pays nothing (the 2026-11-13 version ran the check beside
    the stop decode and added up to 1-2 s at p90 on a busy laptop).

    Anything not judged in time protects the audio it covers: a window still
    waiting for the model, a model failure, or more than TAIL_GAP_S of audio
    after the last judged window at the stop all mean "keep".
    """

    # At the stop, the audio after the last judged window is up to one hop
    # plus the window being judged plus the release tail. Past this, the end
    # of the clip is not known well enough to cut.
    TAIL_GAP_S = 1.5

    def __init__(self, filt: "VoiceFilter", threaded: bool = True, log=print):
        self._emb = filt.embedder
        self._centre = filt.profile.centroid()
        self._log = log
        self._win = int(WIN_S * SAMPLE_RATE)
        self._hop = int(HOP_S * SAMPLE_RATE)
        self._lock = threading.Lock()
        self._buf = np.zeros(0, dtype=np.float32)   # audio from _buf_start on
        self._buf_start = 0
        self._received = 0          # absolute end of the audio fed so far
        self._levels: list[float] = []   # 20 ms block levels from sample 0
        self._carry = np.zeros(0, dtype=np.float32)
        self._next = 0              # start of the next window to judge
        self._sims: dict[int, float] = {}
        self._inflight = -1          # window being judged right now
        self.failed = self._centre is None
        self.windows = 0
        self.embed_ms = 0
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if threaded and not self.failed:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="voice-track")
            self._thread.start()

    # ── input ──
    def feed(self, abs_start: int, audio: Optional[np.ndarray]) -> None:
        """Audio covering [abs_start, abs_start + len). Only the part not fed
        before is kept. A gap (audio that was never fed) stops the track."""
        if self.failed or audio is None or not len(audio):
            return
        with self._lock:
            if abs_start > self._received:
                self.failed = True
                self._log("[VoiceIsolation] track lost audio; this dictation is kept whole")
                return
            new = np.asarray(audio[self._received - abs_start:], dtype=np.float32).reshape(-1)
            if not len(new):
                return
            self._buf = np.concatenate([self._buf, new])
            self._received += len(new)
            blocks = np.concatenate([self._carry, new])
            n = len(blocks) // 320 * 320
            if n:
                self._levels.extend(np.sqrt(np.mean(np.square(
                    blocks[:n].reshape(-1, 320)), axis=1)).tolist())
            self._carry = blocks[n:].copy()
        self._wake.set()

    def _floor(self, levels) -> float:
        return max(SILENCE_RMS, 0.25 * float(np.percentile(levels, 90))) if len(levels) else 1.0

    @staticmethod
    def _share(levels, floor, s, e) -> float:
        seg = levels[s // 320:e // 320]
        return float(np.mean(seg >= floor)) if len(seg) else 0.0

    # ── background judging ──
    def step(self) -> bool:
        """Judge the next complete window. False when none is ready."""
        with self._lock:
            if self.failed or self._stop.is_set() or self._next + self._win > self._received:
                return False
            s = self._next
            self._inflight = s
            off = s - self._buf_start
            seg = self._buf[off:off + self._win].copy()
            levels = np.asarray(self._levels, dtype=np.float32)
            self._next += self._hop
            cut = self._next - self._buf_start
            self._buf = self._buf[cut:]
            self._buf_start = self._next
        # The floor may still move as the dictation goes on, so judge every
        # window that has any speech; spans() applies the final floor.
        try:
            if self._share(levels, self._floor(levels), s, s + self._win) < SOME_SPEECH:
                return True
            t = time.perf_counter()
            embs = self._emb.embed_many([seg])
            self.embed_ms += int((time.perf_counter() - t) * 1000)
            if embs is None:
                self.failed = True
                self._log("[VoiceIsolation] voice model unavailable; dictation kept whole")
                return False
            with self._lock:
                self._sims[s] = float(embs[0] @ self._centre)
                self.windows += 1
            return True
        finally:
            self._inflight = -1

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                while self.step():
                    pass
            except Exception as e:
                self.failed = True
                self._log(f"[VoiceIsolation] track stopped: {e}")
                return
            self._wake.wait(0.5)

    def close(self) -> None:
        """Stop judging at once. Never waits: a window in flight finishes on
        its own thread and its result is simply not used."""
        self._stop.set()
        self._wake.set()

    # ── decision ──
    def head_horizon(self) -> int:
        """No head cut can reach past this sample: only the first MAX_SCAN
        windows are ever looked at from the start."""
        return (MAX_SCAN - 1) * self._hop + self._win

    def head_settled(self) -> bool:
        """True once the start of the dictation can no longer turn out to be
        someone else: its first voiced window was not someone else's, or
        every window the head scan may look at has been judged. Used with an
        empty head cut, to stop keeping early chunks for a re-decode."""
        with self._lock:
            if self.failed:
                return True
            levels = np.asarray(self._levels, dtype=np.float32)
            sims = dict(self._sims)
            judged_to = self._next
            inflight = self._inflight
        if not len(levels):
            return False
        floor = self._floor(levels)
        for s in range(0, min(judged_to, MAX_SCAN * self._hop), self._hop):
            share = self._share(levels, floor, s, s + self._win)
            if share < SOME_SPEECH:
                continue
            if s == inflight:
                return False        # still being judged: not decided yet
            sim = sims.get(s) if share >= VOICED_SHARE else None
            return sim is None or sim >= OTHER_BELOW
        return judged_to >= MAX_SCAN * self._hop

    def spans(self, head_only: bool = False) -> list[tuple[int, int]]:
        """Absolute sample ranges to cut, from cached results only."""
        with self._lock:
            if self.failed or self._centre is None:
                return []
            n = self._received
            levels = np.asarray(self._levels, dtype=np.float32)
            sims = dict(self._sims)
            judged_to = self._next      # windows starting before this were seen
        win, hop = self._win, self._hop
        if n < win or not len(levels):
            return []
        floor = self._floor(levels)
        starts = [s for s in range(0, n - win + 1, hop) if s < judged_to]

        def items(order):
            for s in order:
                share = self._share(levels, floor, s, s + win)
                sim = sims.get(s) if share >= VOICED_SHARE else None
                yield s, sim, share

        head = _scan(items(starts[:MAX_SCAN]), True)
        if head_only:
            return _to_spans(n, head, None)
        tail, tail_end = None, None
        if starts and n - (starts[-1] + win) <= int(self.TAIL_GAP_S * SAMPLE_RATE):
            tail = _scan(items(list(reversed(starts))[:MAX_SCAN]), False)
            # Audio after the last judged window was never judged: the cut
            # may run over it only when it holds no speech at all (silence
            # before the key-up). Speech there may be the user's last words.
            judged_end = starts[-1] + win
            if self._share(levels, floor, judged_end, n) >= SOME_SPEECH:
                tail_end = judged_end
        return _to_spans(n, head, tail, tail_end)


def relative_spans(spans, start: int, end: int) -> list[tuple[int, int]]:
    """Absolute spans clipped to [start, end) and shifted to start at 0."""
    out = []
    for s, e in spans or []:
        a, b = max(s, start), min(e, end)
        if b > a:
            out.append((a - start, b - start))
    return out


class VoiceIsolation:
    """Owns the voiceprint and hands out a VoiceTrack per dictation.

    A background thread downloads the voice model once, then learns the
    user's voice from their own saved dictations (the local audio folder),
    one file at a time and only while Echo is idle, so nothing here ever runs
    on the press or stop path. The filter goes live once MIN_ENROLL
    dictations are learned. stop() switches it off at once: a dictation that
    starts afterwards gets no track.
    """

    POLL_S = 60.0          # look for new dictations this often
    RETRY_DOWNLOAD_S = 1800.0

    def __init__(self, model_dir: str, profile_path: str, audio_dir: str,
                 is_busy=lambda: False, log=print, report=None, embedder=None,
                 owner=lambda: ""):
        # One thread: with intra-op 1, onnxruntime computes on the calling
        # thread, so a track never takes more than one core from the decode.
        self.embedder = embedder or SpeakerEmbedder(model_dir, threads=1)
        self.profile = VoiceProfile(profile_path, log=log)
        self.filter = VoiceFilter(self.embedder, self.profile)
        self._audio_dir = audio_dir
        self._is_busy = is_busy
        self._log = log
        self._report = report      # report(event, details) for failures
        self._owner_fn = owner     # the signed-in account's id, or ""
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._live = False

    @property
    def active(self) -> bool:
        """True once enough dictations are learned to judge a voice."""
        return self._live and self.profile.ready and not self._stop.is_set()

    def new_track(self) -> Optional[VoiceTrack]:
        """A tracker for the dictation that is starting, or None (not ready,
        or someone other than the voiceprint's owner is signed in: the
        dictation then runs exactly as with the feature off)."""
        if not self._owner_ok() or not self.active:
            return None
        return VoiceTrack(self.filter, log=self._log)

    def _owner_ok(self) -> bool:
        """True when the voiceprint belongs to whoever is signed in. Another
        account on this PC starts a fresh voiceprint, learned only from its
        own dictations from then on; the old one is deleted, never shared."""
        import hashlib
        try:
            raw = str(self._owner_fn() or "")
            if raw == "local":
                raw = ""        # offline use: not an account
        except Exception as e:
            self._log(f"[VoiceIsolation] could not read the signed-in account: {e}")
            return False
        cur = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24] if raw else ""
        have = self.profile.owner
        if cur == have:
            return True
        if not cur:
            # Signed out: nobody to match, so no learning and no filtering.
            return False
        if not have:
            # First account seen: the saved dictations on this PC are theirs.
            self.profile.set_owner(cur, self.profile.since)
            return True
        self._log("[VoiceIsolation] a different account signed in; starting a new voiceprint")
        self._live = False
        if not self.profile.delete():
            self._fail(self.profile.last_error or "voice profile not deleted")
        self.profile.set_owner(cur, time.time())
        return True

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="voice-isolation")
        self._thread.start()

    def stop(self, forget: bool = False) -> None:
        """Off at once. forget=True also deletes the voiceprint."""
        self._stop.set()
        self._live = False
        if forget and not self.profile.delete(close=True):
            self._fail(self.profile.last_error or "voice profile not deleted")

    def _fail(self, what: str) -> None:
        self._log(f"[VoiceIsolation] {what}")
        if self._report:
            try:
                self._report("voice_isolation_failed", {"reason": what[:200]})
            except Exception as e:
                self._log(f"[VoiceIsolation] could not report failure: {e}")

    def _wait_idle(self) -> bool:
        while self._is_busy():
            if self._stop.wait(2.0):
                return False
        return not self._stop.is_set()

    def _new_files(self) -> list[str]:
        try:
            names = sorted(n for n in os.listdir(self._audio_dir)
                           if n.lower().endswith(".wav"))
        except FileNotFoundError:
            return []
        seen = set(self.profile.seen)
        since = self.profile.since
        if since:
            def _mine(n: str) -> bool:
                try:
                    return os.path.getmtime(os.path.join(self._audio_dir, n)) >= since
                except OSError:
                    return False
            names = [n for n in names if _mine(n)]
        # Newest first: the voiceprint should reflect the user's current mic.
        return [n for n in reversed(names) if n not in seen][:MAX_ENROLL]

    def _read(self, path: str) -> Optional[np.ndarray]:
        import wave
        try:
            with wave.open(path) as w:
                if w.getframerate() != SAMPLE_RATE or w.getsampwidth() != 2:
                    return None
                ch = w.getnchannels()
                a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            a = a.astype(np.float32) / 32768.0
            if ch > 1:
                a = a.reshape(-1, ch).mean(axis=1)
            return a
        except Exception as e:
            self._log(f"[VoiceIsolation] skipped unreadable dictation: {e}")
            return None

    def learn_once(self) -> int:
        """Learn from any new saved dictations; returns how many joined."""
        joined = 0
        if self._stop.is_set() or not self._owner_ok():
            return 0
        # Every write below carries this number: a delete in the meantime
        # (switched off, another account) makes them all refused.
        gen = self.profile.generation
        for name in self._new_files():
            if not self._wait_idle() or not self._owner_ok() \
                    or gen != self.profile.generation:
                break
            a = self._read(os.path.join(self._audio_dir, name))
            speech = enrol_audio(a) if a is not None else None
            if speech is not None:
                vec = self.embedder.embed(speech)
                if self._stop.is_set():
                    break
                if vec is None:
                    self._fail(self.embedder.last_error or "voice model unavailable")
                    break       # model trouble: retry this file next round
                if self.profile.add(vec, save=False, generation=gen):
                    joined += 1
            if not self.profile.mark_seen(name, generation=gen):
                break
        if self.profile.ready and not self._stop.is_set():
            self._live = True
        return joined

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.embedder.is_downloaded():
                if not self.embedder.download():
                    self._fail(self.embedder.last_error or "voice model download failed")
                    if self._stop.wait(self.RETRY_DOWNLOAD_S):
                        return
                    continue
            try:
                self.learn_once()
            except Exception as e:
                self._fail(f"learning stopped: {e}")
            if self._stop.wait(self.POLL_S):
                return
