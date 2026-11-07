"""When an update may restart Echo.

Restarting closes the window and leaves dictation down until the new copy has
loaded, which took 3 minutes on a busy laptop on 6 Nov 2026. So a restart waits
for the person to be away, not merely for a pause between dictations.
"""

import ctypes
import time

DICTATION_QUIET_S = 120.0
AWAY_S = 600.0
# An update must still arrive for someone who never leaves the machine.
FORCE_AFTER_S = 24 * 3600.0


def safe_to_restart(idle_state: bool, since_dictation_s: float,
                    input_idle_s: float, waiting_s: float) -> bool:
    if not idle_state or since_dictation_s <= DICTATION_QUIET_S:
        return False
    return input_idle_s >= AWAY_S or waiting_s >= FORCE_AFTER_S


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def input_idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input anywhere in this session.
    0 when Windows cannot say, so a failed read never restarts anyone."""
    try:
        user32 = ctypes.WinDLL("user32")
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetTickCount.restype = ctypes.c_uint
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        # Both are 32-bit tick counts, which wrap every 49.7 days.
        return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception as e:
        print(f"[Update] Could not read input idle time: {e}")
        return 0.0


class RestartGate:
    """Holds the moment the update first started waiting."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._first = None

    def waiting_s(self) -> float:
        now = self._clock()
        if self._first is None:
            self._first = now
        return now - self._first
