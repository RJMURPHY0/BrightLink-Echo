"""Tell a spoiled screen recording apart from a real glitch.

page_change_check and scroll_check --screen record the screen itself, so
anything another program puts over the test window (a Snipping Tool overlay,
a browser brought forward, the window minimised from its taskbar button) is
filmed as if Echo drew it. On 4 Nov 2026 that read as GLITCH on a different
page every run while the frames showed Chrome. This watches the recorded box
from inside the checker process: every few milliseconds it asks Windows which
window owns a grid of points across the box, and notes any moment where one
belongs to another process, or where the test window is minimised or hidden.
A spoiled run is reported as such (exit 2), never judged.
"""

import ctypes
import os
import threading
import time
from ctypes import wintypes as W

_u32 = ctypes.WinDLL("user32")
_u32.WindowFromPoint.restype = W.HWND
_u32.WindowFromPoint.argtypes = [W.POINT]
_u32.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
_u32.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
_u32.IsIconic.argtypes = [W.HWND]
_u32.IsWindowVisible.argtypes = [W.HWND]
_u32.GetAncestor.restype = W.HWND
_u32.GetAncestor.argtypes = [W.HWND, W.UINT]
_u32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]

_GRID = 5          # points per side across the box
_POLL_S = 0.015


def _pid(hwnd) -> int:
    p = W.DWORD()
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def _title(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(80)
    _u32.GetWindowTextW(_u32.GetAncestor(hwnd, 2) or hwnd, buf, 80)
    return buf.value or "untitled window"


class ScreenGuard:
    """watch(hwnd) one window (whole client area, or the rect of `box_hwnd`
    when given) until stop(); `spoiled` then lists what got in the way."""

    def __init__(self, hwnd: int, box_hwnd: int = 0):
        self._hwnd = hwnd
        self._box = box_hwnd or hwnd
        self._me = os.getpid()
        self._stop = threading.Event()
        self.spoiled = []          # (perf_counter, reason), first per reason
        self._seen = set()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "ScreenGuard":
        self._thread.start()
        return self

    def stop(self) -> list:
        self._stop.set()
        self._thread.join(2)
        return self.spoiled

    def _note(self, reason: str) -> None:
        if reason not in self._seen:
            self._seen.add(reason)
            self.spoiled.append((time.perf_counter(), reason))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._check()
            except Exception as exc:        # a broken guard must not pass
                self._note(f"screen guard failed: {exc}")
            time.sleep(_POLL_S)

    def _check(self) -> None:
        if _u32.IsIconic(self._hwnd):
            self._note("test window minimised")
            return
        if not _u32.IsWindowVisible(self._hwnd):
            return          # hidden by Echo itself (sign-in swap): not filmed
        r = W.RECT()
        _u32.GetWindowRect(self._box, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if w <= 8 or h <= 8:
            return
        for i in range(_GRID):
            for j in range(_GRID):
                pt = W.POINT(r.left + 4 + (w - 8) * i // (_GRID - 1),
                             r.top + 4 + (h - 8) * j // (_GRID - 1))
                hw = _u32.WindowFromPoint(pt)
                if hw and _pid(hw) != self._me:
                    self._note(f"'{_title(hw)}' (another program) was over "
                               f"the test window")
                    return


def report(spoiled, t0: float = 0.0) -> str:
    return "; ".join(f"{reason} at +{t - t0:.1f}s" for t, reason in spoiled)
