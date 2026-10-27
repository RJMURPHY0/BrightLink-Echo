"""Progress bars: the Updates card's measured bar and the sign-in step bar.

The update bar shows only measured numbers (updater.update_progress). Sign-in
is one network request with nothing to measure, so it gets a step bar with no
percentage: it moves within the current step and only passes a step's end
when that step has really finished.
"""

import math
import time
import tkinter as tk
from typing import Optional, Tuple

import ui_render


class ProgressBar(tk.Canvas):
    """A thin rounded bar that fills its width. set(fraction) redraws it."""

    def __init__(self, master, fill: str, track: str, bg: str, height: int = 6):
        super().__init__(master, height=height, width=1, bg=bg,
                         highlightthickness=0, bd=0)
        self._fill, self._track, self._bgc, self._h = fill, track, bg, height
        self._fraction = 0.0
        self._img = None
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, float(fraction or 0.0)))
        if abs(fraction - self._fraction) < 0.001 and self._img is not None:
            return
        self._fraction = fraction
        self._draw()

    def _draw(self) -> None:
        try:
            w = self.winfo_width()
        except tk.TclError:
            return
        if w <= 1:
            return
        img = ui_render.progress_bar(self, w, self._h, self._fraction,
                                     self._fill, self._track, self._bgc)
        if img is None:
            return
        self._img = img          # keep a reference: Tk drops unreferenced images
        self.delete("all")
        self.create_image(0, 0, image=img, anchor="nw")


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.0f}"


def _time_left(seconds: float) -> str:
    if seconds < 60:
        s = math.ceil(seconds) if seconds < 10 else int(math.ceil(seconds / 5) * 5)
        s = max(1, s)
        return f"about {s} second{'s' if s != 1 else ''} left"
    m = int(math.ceil(seconds / 60))
    return f"about {m} minute{'s' if m != 1 else ''} left"


def _elapsed(started: float, now: float) -> str:
    s = max(0, int(now - started))
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60:02d} s"


def describe_update(p: dict, now: Optional[float] = None) -> Optional[Tuple[float, str]]:
    """(bar fraction, line of text) for updater.update_progress(), or None
    when no bar should show (no update running, or ready and waiting for the
    user to stop dictating, which the status line already says)."""
    phase = p.get("phase") or ""
    now = time.monotonic() if now is None else now
    frac = p.get("fraction")
    if phase == "download":
        done, total = int(p.get("done") or 0), int(p.get("total") or 0)
        if frac is None:
            return 0.0, f"Downloading · {_mb(done)} MB"
        text = f"Downloading {int(frac * 100)}% · {_mb(done)} of {_mb(total)} MB"
        left = p.get("seconds_left")
        if left is not None and frac < 1.0:
            text += f" · {_time_left(left)}"
        return frac, text
    if phase == "verify":
        return 1.0, "Checking the download…"
    if phase == "prepare":
        if frac is None:
            return 0.0, f"Preparing… {_elapsed(p.get('started') or now, now)}"
        return frac, f"Preparing {int(frac * 100)}%"
    if phase == "install":
        return 1.0, "Restarting to finish…"
    return None


class StepProgress:
    """Drives a ProgressBar through *steps* equal segments. The bar eases
    toward 90% of the current segment while that step runs and only enters
    the next segment on advance(); finish() fills it."""

    _TICK_MS = 40
    _EASE = 0.05

    def __init__(self, bar: ProgressBar, steps: int):
        self._bar, self._steps = bar, max(1, steps)
        self._step = 0
        self._value = 0.0
        self._target = 0.0
        self._job = None

    def start(self) -> None:
        self._step, self._value = 0, 0.0
        self._target = self._ceiling()
        self._bar.set(0.0)
        self._tick()

    def advance(self) -> None:
        self._value = max(self._value, (self._step + 1) / self._steps)
        self._step = min(self._step + 1, self._steps - 1)
        self._target = self._ceiling()
        self._bar.set(self._value)

    def finish(self) -> None:
        self._cancel()
        self._value = self._target = 1.0
        self._bar.set(1.0)

    def stop(self) -> None:
        self._cancel()

    def _ceiling(self) -> float:
        return (self._step + 0.9) / self._steps

    def _cancel(self) -> None:
        if self._job is not None:
            try:
                self._bar.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _tick(self) -> None:
        self._value += (self._target - self._value) * self._EASE
        try:
            self._bar.set(self._value)
            self._job = self._bar.after(self._TICK_MS, self._tick)
        except tk.TclError:
            self._job = None
