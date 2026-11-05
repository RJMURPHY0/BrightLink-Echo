"""Where the app starts in the sign-in queue (Settings: Start with Windows).

The slider picks a stop. A sign-in launch (--startup, from either the logon task
or the Run entry) waits that long before doing anything heavy, and loads at that
stop's priority so it stays out of the way of whatever is opening. It changes
start-up only: once the speech model is ready the process goes back to the
above-normal class it always dictates at, so dictation speed is the same at
every stop. A launch by hand never waits.

Runs ahead of every project import in app.py, so stdlib only, and it reads the
one value it needs straight from config.json rather than through Config.
"""

import ctypes
import json
import os
import sys
import time
from typing import NamedTuple

ABOVE_NORMAL = 0x00008000
NORMAL = 0x00000020

STARTUP_ARG = "--startup"


class Stop(NamedTuple):
    label: str          # under the slider
    caption: str        # the one line that says what this stop does
    delay_seconds: int  # after sign-in
    load_class: int     # process priority class while the model loads


# Index 0 is what every install did before this setting existed, and the default.
STOPS = (
    Stop("First", "Ready the moment you sign in, ahead of Teams and other apps.",
         0, ABOVE_NORMAL),
    Stop("With others", "Starts about 20 seconds after sign-in, alongside your other apps.",
         20, NORMAL),
    Stop("After others", "Starts about 90 seconds after sign-in, once other apps have opened.",
         90, NORMAL),
    Stop("Last", "Starts about 3 minutes after sign-in, when your PC has settled.",
         180, NORMAL),
)
DEFAULT_STOP = 0

_lowered = False


def clamp(value) -> int:
    """A valid stop index for anything a config file may hold."""
    if isinstance(value, bool):
        return DEFAULT_STOP
    try:
        return max(0, min(int(value), len(STOPS) - 1))
    except (TypeError, ValueError):
        return DEFAULT_STOP


def launched_at_sign_in(argv) -> bool:
    return any(str(a).lower() == STARTUP_ARG for a in argv[1:])


def _config_path() -> str:
    # The same rule as config.get_config_path(), which cannot be imported yet.
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "config.json")


def saved_stop(path: str = "") -> int:
    """The saved stop; the default when the file is missing or unreadable, so a
    damaged config can never hold the app back at sign-in."""
    try:
        with open(path or _config_path(), "r", encoding="utf-8") as f:
            return clamp(json.load(f).get("startup_priority", DEFAULT_STOP))
    except (OSError, ValueError, AttributeError):
        return DEFAULT_STOP


def _set_priority_class(value: int) -> bool:
    try:
        # A private WinDLL: argtypes on the shared ctypes.windll leak into every
        # other module (the popup wrong-monitor saga).
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), value))
    except Exception as e:
        print(f"[Startup] Could not set process priority: {e}", file=sys.stderr)
        return False


def wait_at_sign_in(argv, sleep=time.sleep, set_class=_set_priority_class,
                    stop=None) -> int:
    """Called once, at the very top of app.py. Returns the seconds waited."""
    global _lowered
    if not launched_at_sign_in(argv):
        return 0
    chosen = STOPS[saved_stop() if stop is None else clamp(stop)]
    if chosen.delay_seconds <= 0:
        return 0
    _lowered = True
    # Never below normal: a sleeping process costs nothing anyway, and with a
    # build running a 2 s sleep at below-normal class took 11.9 s to come back,
    # which would make a stop's promised time meaningless.
    set_class(chosen.load_class)
    sleep(chosen.delay_seconds)
    return chosen.delay_seconds


def restore_dictation_priority(set_class=_set_priority_class) -> None:
    """The model is ready (or failed): dictate at the usual class. No-op unless
    wait_at_sign_in lowered it."""
    global _lowered
    if _lowered:
        _lowered = False
        set_class(ABOVE_NORMAL)
