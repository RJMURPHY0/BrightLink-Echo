"""Keeps the speech model in memory so a dictation after a quiet spell is instant.

When RAM is tight Windows pages out whatever has sat idle, and the speech model
is the biggest idle thing we own. The next real decode then has to fault it all
back in while the user waits. Seen live: back from 148 MB to 982 MB at about
17 MB/s, with a 21 s clip taking 57 s to appear. Measured on a 13.6 s clip with
RAM at 96%: 4.7-5.9 s straight after a page-out, against 1.5 s normally and 1.6 s
after one keep-warm pass.

A pass costs about 0.2 s (0.8 s of CPU) when the model is already resident, so:
  - it runs every REFRESH_SECONDS while the person is around and on mains power,
    and never during a dictation
  - it stops once they have been away IDLE_STOP_SECONDS, so a PC left on overnight
    does no work, and runs again within POLL_SECONDS of them coming back
  - a press after a quiet spell runs one straight away, whatever the power source,
    so the pages are back by the time they stop talking

The working set is never trimmed or pinned here: no test showed a hard floor
helping, and it takes RAM from everything else.
"""

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

REFRESH_SECONDS = 180.0
POLL_SECONDS = 20.0
IDLE_STOP_SECONDS = 30 * 60.0
PRESS_STALE_SECONDS = 60.0
# A pass over a resident model takes about 200 ms. Far past that, it had to
# bring pages back: the evidence that paging really is happening on a machine.
PAGED_IN_MS = 600


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def seconds_since_input() -> float:
    """Seconds since the last keyboard or mouse input; 0 when unknown, so a failed
    read keeps the model warm rather than letting it go cold."""
    try:
        info = _LastInput()
        info.cbSize = ctypes.sizeof(info)
        user32 = ctypes.WinDLL("user32")
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetTickCount.restype = wintypes.DWORD
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        # Both are 32-bit millisecond counters that wrap after 49.7 days.
        return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return 0.0


def on_battery() -> bool:
    """True only when Windows says so; unknown counts as mains."""
    try:
        status = _PowerStatus()
        if not ctypes.WinDLL("kernel32").GetSystemPowerStatus(ctypes.byref(status)):
            return False
        return status.ACLineStatus == 0
    except Exception:
        return False


class ModelKeepWarm:
    def __init__(self, engine, is_busy: Callable[[], bool],
                 is_active: Callable[[], bool] = lambda: True,
                 on_paged_in: Optional[Callable[[int, str], None]] = None,
                 idle_seconds: Callable[[], float] = seconds_since_input,
                 battery: Callable[[], bool] = on_battery,
                 monotonic: Callable[[], float] = time.monotonic):
        self._engine = engine
        self._is_busy = is_busy
        self._is_active = is_active
        self._on_paged_in = on_paged_in
        self._idle_seconds = idle_seconds
        self._battery = battery
        self._now = monotonic
        self._wake = threading.Event()
        self._press_pending = False
        self._stopped = False
        self._thread = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="model-keep-warm")
            self._thread.start()

    def stop(self) -> None:
        self._stopped = True
        self._wake.set()

    def note_press(self) -> None:
        """A dictation just started: never waits, safe on the press path."""
        if self._now() - self._engine.last_used >= PRESS_STALE_SECONDS:
            self._press_pending = True
            self._wake.set()

    def _loop(self) -> None:
        while not self._stopped:
            self._wake.wait(POLL_SECONDS)
            self._wake.clear()
            if self._stopped:
                return
            try:
                self.tick()
            except Exception as e:
                print(f"[KeepWarm] Pass skipped: {e}")

    def tick(self) -> Optional[int]:
        """One decision. Returns the pass's milliseconds, None when it ran none."""
        if not self._is_active():
            self._press_pending = False
            return None
        reason = ""
        if self._press_pending:
            self._press_pending = False
            reason = "press"
        elif (self._now() - self._engine.last_used >= REFRESH_SECONDS
              and not self._is_busy()
              and self._idle_seconds() < IDLE_STOP_SECONDS
              and not self._battery()):
            reason = "refresh"
        if not reason:
            return None
        ms = self._engine.keep_warm()
        if ms is not None and ms >= PAGED_IN_MS:
            print(f"[KeepWarm] Model paged back in: {ms} ms ({reason}).")
            if self._on_paged_in:
                self._on_paged_in(ms, reason)
        return ms
