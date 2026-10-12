"""
Apply the newest value of something on a background thread, never on the
caller's.

The hotkey thread used to repaint the tray icon and the dashboard's status
label itself, before the start cue played and before capture began. The tray
repaint writes the icon to a temporary .ico file, reads it back and messages
Explorer (12-22 ms per press on Ryan's laptop, 1.1 s cold, longer while
antivirus scans the file); the label waits for the Tk loop to be free. A press
should never wait for either.

Only the latest value matters for both (the icon and label show the current
state), so a burst of submits collapses into one apply of the last value, and
the final state is always the one the caller set last.
"""

import threading
from typing import Any, Callable


class LatestWorker:
    def __init__(self, apply: Callable[[Any], None], name: str):
        self._apply = apply
        self._name = name
        self._cond = threading.Condition()
        self._pending = False
        self._value: Any = None
        # Started now, at app start-up, so the first press of a run does not
        # pay for creating it.
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=name)
        self._thread.start()

    def submit(self, value: Any) -> None:
        """Queue `value`; returns at once. A value not yet applied is replaced."""
        with self._cond:
            self._value = value
            self._pending = True
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._pending:
                    self._cond.wait()
                value = self._value
                self._pending = False
            try:
                self._apply(value)
            except Exception as e:
                print(f"[{self._name}] apply failed: {e}")
