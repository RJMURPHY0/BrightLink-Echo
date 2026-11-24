"""Is the microphone actually working while the pill says "Recording"?

Ryan (24 Nov 2026): if the microphone has stopped working, pressing the hotkey
must not show "Recording"; the pill says it failed.

Judged live from the mic level loop (never on the press path), from what the
recorder already measures:

  * no audio arriving at all (the stream delivered nothing since the press, or
    its callbacks stopped): the device is gone or the audio stack is stuck;
  * nothing but exact digital silence, AND Windows says why (the microphone
    privacy switch is off, or the device is muted or at volume 0);
  * a dead input: nothing above -80 dBFS (mic_access.DEAD_PEAK) for DEAD_S,
    on a device that has never carried real signal since Echo started. James
    Murphy's "usb mic" (24 Nov 2026) peaked at 0.00001 on every press while he
    talked. Once a device has carried sound it is never judged this way, so a
    noise-suppressed mic sitting at zero before you talk is safe (only its
    very first press after Echo starts could show it, and that flips back to
    "Recording" the moment you speak).

Exact silence on its own is NOT a failure here: noise suppression (Krisp,
NVIDIA Broadcast, some drivers) outputs exact zeros while the user has not
started talking yet, and calling that "failed" would be a false alarm. The
existing check after a dictation still names that case (mic_access).

The verdict can flip back: a stream the watchdog revives shows "Recording"
again.
"""

# Grace after recorder.start() has RETURNED (the app never judges before
# that) before anything is judged: a cold stream's first callback.
START_GRACE_S = 0.8
# No callback for this long while recording = the stream has stalled. Never
# tighter than the recorder's own staleness bar (_HEARTBEAT_STALE_SECONDS).
STALL_S = 1.5
# Exact silence for this long before Windows is asked whether it is blocked.
SILENT_S = 1.5
# A device that has never carried real signal, dead this long = failed.
DEAD_S = 2.0


def needs_block_check(silent_run: float) -> bool:
    """True once the silence has lasted long enough to ask Windows why."""
    return silent_run >= SILENT_S


def mic_failed(elapsed: float, new_samples: int, heartbeat_age: float,
               silent_run: float, blocked: bool, dead_run: float = 0.0,
               ever_live: bool = True) -> bool:
    """The verdict for one tick of the level loop.

    elapsed: seconds since recording started.
    new_samples: samples captured since then (the pre-roll seed excluded).
    heartbeat_age: seconds since the stream's last callback.
    silent_run: seconds of unbroken exact-zero callbacks.
    blocked: Windows reports the mic switched off, muted or at volume 0.
    dead_run: seconds of blocks at or below the dead-input peak.
    ever_live: this device has carried real signal since Echo started.
    """
    if elapsed < START_GRACE_S:
        return False
    if new_samples <= 0:
        return True
    if heartbeat_age > STALL_S:
        return True
    if not ever_live and dead_run >= DEAD_S:
        return True
    return silent_run >= SILENT_S and blocked
