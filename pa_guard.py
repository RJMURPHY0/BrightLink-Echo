"""One lock for the PortAudio library as a whole, plus re-init hooks.

The recorder re-initialises PortAudio (sd._terminate / sd._initialize) to see
device changes, and that kills every open stream in the process, the cue
player's output stream included. The recorder holds PORTAUDIO_LOCK across the
re-init and calls the hooks around it, so the cue player closes its stream
cleanly first and reopens it after. A cue opening or queueing holds the same
lock, and so does the recorder's warm-stream open, so no two PortAudio opens
or closes ever run at once (PortAudio does not promise that is safe). Kept in
its own module so recorder.py and feedback.py share it without importing each
other."""

import threading

# Re-entrant, so a second take on the same thread (a hook, a nested open) can
# never deadlock.
PORTAUDIO_LOCK = threading.RLock()

# The longest the recorder waits for the lock before re-initialising anyway.
# A cue holds it only to open a stream or queue samples; this bounds a hang.
REINIT_WAIT_SECONDS = 1.0

_before: list = []
_after: list = []


def on_reinit(before=None, after=None) -> None:
    """Register callables run just before and just after a PortAudio re-init.
    Both run on the re-initialising thread, which holds PORTAUDIO_LOCK, so a
    hook must never try to take that lock itself."""
    if before is not None:
        _before.append(before)
    if after is not None:
        _after.append(after)


def _run(hooks: list, label: str) -> None:
    for fn in list(hooks):
        try:
            fn()
        except Exception as e:
            print(f"[PortAudio] {label} hook failed: {e}")


def notify_before_reinit() -> None:
    _run(_before, "before-reinit")


def notify_after_reinit() -> None:
    _run(_after, "after-reinit")
