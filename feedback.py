"""
Visual and audio feedback for the application.
Plays sounds on recording start/stop and manages tray icon state changes.

The start/stop cues are a two-tap figure modelled on Glaido's, which is the
sound Ryan actually wanted. They are not guessed: Glaido ships its cues as two
24-bit/48kHz WAVs embedded in `%LOCALAPPDATA%\\Glaido\\glaido-core.exe`, and
those were extracted and measured (see _TAP_* below for exactly what came back).
Everything is a soft sine tap generated once in memory and played synchronously
via winsound.PlaySound — never winsound.Beep, which is a raw square wave at
full volume that reads as a long, harsh, high-pitched alarm.
"""

import io
import math
import struct
import sys
import threading
import time
import wave
from typing import Callable, Optional
import pa_guard  # stdlib only: the one PortAudio lock
# error_reporter pulls in urllib/email (~100ms) — imported on first error
# instead of at startup (this module is on the first-paint path).

_SR = 44100  # generated-blip sample rate: the taps have a ~6ms attack, and
             # 22050 smeared that transient enough to soften the "tick"


# ── Glaido-matched taps ───────────────────────────────────────────────────────
# Measured from the two WAVs embedded in glaido-core.exe (24-bit, 48 kHz, one
# at offset 19033401, the other at 19056203). Both are the SAME shape: two
# mallet-style sine taps, essentially pure (2nd harmonic is 0.4–1.8% of the
# fundamental, 3rd is 0.2%), each with a ~6ms attack and a fast exponential
# decay, the second tap louder than the first.
#
#   rise (79.0 ms):  296.6 Hz @ 0.100 peak, then 442.4 Hz @ 0.153, 33ms apart
#   fall (94.5 ms):  440.9 Hz @ 0.106 peak, then 287.8 Hz @ 0.147, 48ms apart
#
# So it is a perfect fifth (D4↔A4) played up for one cue and down for the
# other. Reproduced rather than shipped verbatim: their asset is theirs.
_TAP_ATTACK_MS = 6.0     # measured 5.5–6.5 across all four taps
_TAP_TAU_MS = 6.3        # decay constant: 10% of peak at ~13ms
_TAP_MS = 34.0           # audible length of one tap before it is inaudible
# Glaido's own cues peak at 0.15 (-16 dBFS), which is quiet on laptop speakers.
# Doubled here — same figure, same character, actually audible across a room.
_TAP_GAIN = 2.0


def _tap(freq: float, peak: float, ms: float = _TAP_MS) -> list:
    """One sine tap: raised-cosine attack, exponential decay. Pure sine, no
    harmonics added, because that is what the measurement showed."""
    n = int(_SR * ms / 1000)
    atk = max(1, int(_SR * _TAP_ATTACK_MS / 1000))
    tau = _SR * _TAP_TAU_MS / 1000
    out = []
    for i in range(n):
        if i < atk:
            env = 0.5 - 0.5 * math.cos(math.pi * i / atk)
        else:
            env = math.exp(-(i - atk) / tau)
        out.append(math.sin(2 * math.pi * freq * i / _SR) * peak * env)
    return out


def _two_tap(f1: float, p1: float, f2: float, p2: float,
             gap_ms: float, total_ms: float) -> list:
    """The Glaido figure: tap, short gap, second tap. Taps are summed rather
    than concatenated so the first one's tail rings under the second, exactly
    as it does in the original."""
    n = int(_SR * total_ms / 1000)
    buf = [0.0] * n
    for start_ms, freq, peak in ((0.0, f1, p1), (gap_ms, f2, p2)):
        off = int(_SR * start_ms / 1000)
        for i, s in enumerate(_tap(freq, peak * _TAP_GAIN)):
            if off + i < n:
                buf[off + i] += s
    return buf


def _wav_bytes(samples: list) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SR)
        w.writeframes(b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767))
            for s in samples))
    return buf.getvalue()


_SOUND_CACHE: dict = {}


def _recipe(name: str) -> list:
    """Sample list for one cue. One family, so the set sounds like one product:
    every cue is the same mallet tap, and only the pitches and count change."""
    if name == "start":
        # Rising fifth, D4 → A4 — "listening". Glaido's own figure.
        return _two_tap(296.6, 0.100, 442.4, 0.153, 33.0, 79.0)
    if name == "stop":
        # The mirror, A4 → D4 — "got it".
        return _two_tap(440.9, 0.106, 287.8, 0.147, 48.0, 94.5)
    if name == "done":
        # Kept for callers that want an explicit "landed" tap, but the normal
        # dictation path no longer fires it — see transcription_complete.
        return _tap(442.4, 0.085 * _TAP_GAIN)
    # error: two low taps a semitone apart — reads as "no" without alarming.
    return _two_tap(233.1, 0.130, 220.0, 0.130, 90.0, 190.0)


def _get_sound(name: str) -> bytes:
    """Lazily build and cache one notification blip. Built off the UI thread
    (callers are daemon threads), a few ms of pure-python sine maths."""
    if name not in _SOUND_CACHE:
        _SOUND_CACHE[name] = _wav_bytes(_recipe(name))
    return _SOUND_CACHE[name]


# Cues go out through a warm shared-mode WASAPI output stream, never winsound
# first. Measured on a Realtek array mic on 12 Nov 2026:
#   * winsound.PlaySound runs on winmm, and opening winmm's wave output inside
#     our process stalls our own MME and DirectSound microphone input for
#     300-520 ms and DROPS that audio (a 2.0 s window kept 1.54-1.73 s with the
#     cue, 1.98 s without). The start cue plays at the press, so that was the
#     first half second of speech; the stop cue cut the release tail short.
#     WASAPI output lost nothing (1.98 s, first block 23-62 ms).
#   * Opening ANY playback stream on that laptop takes 300-550 ms (PlaySound
#     itself took 485-703 ms for a 79 ms cue), so the stream is opened once and
#     kept open; a cue then only queues samples and starts within one block.
# The sound is unchanged: identical samples, rate and level.
_PCM_CACHE: dict = {}
_CUE_BLOCK = 441              # 10 ms at 44.1 kHz per output callback
_CUE_WARM_SECONDS = 1800.0    # keep the stream open this long after a cue
_CUE_REOPEN_DELAY = 2.0       # after a PortAudio re-init, reopen this much
                              # later, once the recorder has its mic back
_CUE_MAX_FAILS = 3            # opens failing in a row before winsound only


def _get_pcm(name: str):
    """The cue as int16 samples, the same numbers its WAV holds."""
    if name not in _PCM_CACHE:
        import numpy as np
        with wave.open(io.BytesIO(_get_sound(name))) as w:
            frames = w.readframes(w.getnframes())
        _PCM_CACHE[name] = np.frombuffer(frames, dtype="<i2").astype(np.int16)
    return _PCM_CACHE[name]


def _wasapi_output_device(sd) -> Optional[int]:
    """Index of the Windows default playback device on the WASAPI host API,
    or None when there is no WASAPI output."""
    for api in sd.query_hostapis():
        if "WASAPI" in str(api.get("name", "")):
            idx = api.get("default_output_device", -1)
            if idx is not None and int(idx) >= 0:
                return int(idx)
    return None


class _CuePlayer:
    """One open WASAPI output stream that plays silence until a cue is queued.

    Every PortAudio call (open, close) happens under pa_guard.PORTAUDIO_LOCK,
    and the recorder's PortAudio re-init closes the stream through the
    before-hook and schedules a reopen through the after-hook. The stream is
    closed once no cue has played for _CUE_WARM_SECONDS."""

    def __init__(self) -> None:
        self._buf_lock = threading.Lock()   # guards _buf / _pos only
        self._buf = None
        self._pos = 0
        self._stream = None
        self._last_use = 0.0
        self._fails = 0
        self._hooked = False
        self._timer = None

    # -- runs on PortAudio's thread ---------------------------------------
    def _callback(self, outdata, frames, _time_info, _status) -> None:
        outdata.fill(0)
        with self._buf_lock:
            buf = self._buf
            if buf is None:
                return
            n = min(frames, len(buf) - self._pos)
            if n > 0:
                outdata[:n, 0] = buf[self._pos:self._pos + n]
                self._pos += n
            if self._pos >= len(buf):
                self._buf = None
                self._pos = 0

    # -- stream lifecycle (callers hold PORTAUDIO_LOCK) --------------------
    def _open_locked(self, sd) -> bool:
        if self._stream is not None:
            return True
        if self._fails >= _CUE_MAX_FAILS:
            return False
        try:
            idx = _wasapi_output_device(sd)
            if idx is None:
                self._fails = _CUE_MAX_FAILS
                print("[Feedback] No WASAPI output device, cues use winsound.")
                return False
            stream = sd.OutputStream(
                samplerate=_SR, channels=1, dtype="int16", device=idx,
                blocksize=_CUE_BLOCK, latency="low", callback=self._callback,
                extra_settings=sd.WasapiSettings(auto_convert=True))
            stream.start()
            self._stream = stream
            self._fails = 0
            return True
        except Exception as e:
            self._fails += 1
            print(f"[Feedback] Cue stream open failed ({self._fails}/"
                  f"{_CUE_MAX_FAILS}), using winsound: {e}")
            return False

    def _close_locked(self) -> None:
        stream, self._stream = self._stream, None
        with self._buf_lock:
            self._buf = None
            self._pos = 0
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                print(f"[Feedback] Cue stream close failed: {e}")

    def _ensure_hooks(self) -> None:
        if self._hooked:
            return
        pa_guard.on_reinit(before=self._before_reinit,
                           after=self._after_reinit)
        self._hooked = True

    def _before_reinit(self) -> None:
        # Re-initialising thread, lock already held. Let a cue that is still
        # sounding finish (under 0.1 s) so it is never cut mid-tap.
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline:
            with self._buf_lock:
                if self._buf is None:
                    break
            time.sleep(0.01)
        self._close_locked()

    def _after_reinit(self) -> None:
        if time.monotonic() - self._last_use > _CUE_WARM_SECONDS:
            return
        t = threading.Timer(_CUE_REOPEN_DELAY, self.warm)
        t.daemon = True
        t.start()

    def _arm_idle_close(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        t = threading.Timer(_CUE_WARM_SECONDS + 1.0, self._idle_close)
        t.daemon = True
        t.start()
        self._timer = t

    def _idle_close(self) -> None:
        if time.monotonic() - self._last_use < _CUE_WARM_SECONDS:
            return
        with pa_guard.PORTAUDIO_LOCK:
            if time.monotonic() - self._last_use >= _CUE_WARM_SECONDS:
                self._close_locked()

    # -- public ------------------------------------------------------------
    def warm(self) -> bool:
        """Open the stream ahead of the first cue. Never raises."""
        try:
            import sounddevice as sd
            self._ensure_hooks()
            if not self._last_use:
                self._last_use = time.monotonic()
            with pa_guard.PORTAUDIO_LOCK:
                ok = self._open_locked(sd)
            if ok:
                self._arm_idle_close()
            return ok
        except Exception as e:
            print(f"[Feedback] Cue warm-up failed: {e}")
            return False

    def play(self, name: str) -> bool:
        """Queue a cue. True when the stream took it; False means use
        winsound. A new cue replaces one still sounding, as PlaySound does."""
        try:
            import sounddevice as sd
            self._ensure_hooks()
            pcm = _get_pcm(name)
            self._last_use = time.monotonic()
            with pa_guard.PORTAUDIO_LOCK:
                if not self._open_locked(sd):
                    return False
                with self._buf_lock:
                    self._buf = pcm
                    self._pos = 0
            self._arm_idle_close()
            return True
        except Exception as e:
            print(f"[Feedback] Cue play failed, using winsound: {e}")
            return False

    def is_open(self) -> bool:
        return self._stream is not None


_CUE_PLAYER = _CuePlayer()


def warm_cues() -> None:
    """Open the cue stream in the background so the first press is instant."""
    threading.Thread(target=_CUE_PLAYER.warm, daemon=True,
                     name="cue-warm").start()


def _play_sound(name: str) -> None:
    """Play a named blip (Windows only, never raises). The warm WASAPI cue
    stream first (see _CuePlayer: winsound drops our own microphone audio),
    winsound only when that stream cannot be opened.

    Plays SYNCHRONOUSLY from memory. This is deliberate and required: winsound
    CANNOT play SND_MEMORY asynchronously — `SND_MEMORY | SND_ASYNC` raises
    "Cannot play asynchronously from memory". The old async flag therefore threw
    on EVERY cue and silently dropped to a raw 700 Hz winsound.Beep fallback, so
    none of the soft generated tones were ever heard (they looked fine in a
    stand-alone SND_MEMORY test, which masked the bug). Every caller already
    runs this on its own daemon thread, so a ~100 ms synchronous play blocks
    nothing that matters."""
    try:
        if _CUE_PLAYER.play(name):
            return
    except Exception as e:
        print(f"[Feedback] WASAPI cue error, using winsound: {e}")
    try:
        import winsound
        # NB: start/stop used to call MessageBeep(MB_OK) — the Windows "ding".
        # It is loud and unmistakable, but it is also the sound of an error in
        # every other app, and users silence it system-wide. The Glaido-matched
        # taps replace it; do not reintroduce MessageBeep here.
        winsound.PlaySound(_get_sound(name), winsound.SND_MEMORY)
    except Exception:
        # Never fall back to winsound.Beep here — a raw square-wave beep is the
        # exact harsh sound these tones replace. Silent-fail instead; the visual
        # popup still signals state. Logged so a silent machine is explainable.
        print(f"[Feedback] Cue '{name}' could not play.")


class Feedback:
    """
    Provides audio and visual feedback for app state changes.

    Audio (soft mallet taps, not raw beeps) — two cues per dictation:
        - Rising two-tap figure (D4→A4) on recording start
        - Falling two-tap figure (A4→D4) on recording stop
        - Nothing on transcription complete; see transcription_complete()

    Visual:
        - Delegates icon updates to a tray callback
    """

    def __init__(
        self,
        sound_enabled: bool = True,
        on_icon_change: Optional[Callable[[str], None]] = None,
        on_error_notify: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            sound_enabled: Whether to play sound feedback
            on_icon_change: Callback to change tray icon. Called with state name:
                            "idle", "recording", "processing"
            on_error_notify: Optional callback invoked with the error message so
                             the app can log it and show a visible notification —
                             additive on top of the buzz, never replaces it
        """
        self.sound_enabled = sound_enabled
        self.on_icon_change = on_icon_change
        self.on_error_notify = on_error_notify

    def prewarm(self) -> None:
        """Open the cue stream now (blocking) so the first press is instant."""
        if self.sound_enabled:
            _CUE_PLAYER.warm()

    def recording_started(self) -> None:
        """Called when recording begins. The cue goes first: it is what the
        user waits for, and the tray repaint must never sit in front of it."""
        if self.sound_enabled:
            threading.Thread(
                target=_play_sound, args=("start",), daemon=True
            ).start()

        if self.on_icon_change:
            self.on_icon_change("recording")

    def recording_stopped(self) -> None:
        """Called when recording ends and processing begins."""
        if self.sound_enabled:
            threading.Thread(
                target=_play_sound, args=("stop",), daemon=True
            ).start()

        if self.on_icon_change:
            self.on_icon_change("processing")

    def transcription_complete(self, text: str) -> None:
        """Called when transcription is done and text has been injected.

        Deliberately SILENT. Two cues per dictation, not three: the falling
        stop cue already says "got it", and with Parakeet's sub-second latency
        a third tap lands under half a second after it, which reads as clutter
        rather than confirmation. The text appearing is its own confirmation,
        and the popup covers the case where it did not."""
        if self.on_icon_change:
            self.on_icon_change("idle")

    def error_occurred(self, error: str) -> None:
        """Called when an error occurs during recording/transcription."""
        if self.on_icon_change:
            self.on_icon_change("idle")

        if self.sound_enabled:
            # Low buzz for error
            threading.Thread(
                target=_play_sound, args=("error",), daemon=True
            ).start()

        print(f"[Feedback] Error: {error}")
        try:
            from error_reporter import report_error
            report_error(error)
        except Exception:
            pass

        # Additive visibility: the buzz alone is easy to miss (and silent when
        # sound is off), print vanishes in console=False builds, and
        # report_error no-ops when unconfigured — let the app log the error
        # and show a visible notification too.
        if self.on_error_notify:
            try:
                self.on_error_notify(error)
            except Exception as e:
                print(f"[Feedback] error notify failed (non-fatal): {e}")
