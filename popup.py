"""
Floating UI popup — light grey pill with animated waveform during recording.

Three modes:
  status     — pill shown during recording / transcribing
  icon       — small FTC badge near cursor after injection
  refinement — full AI refinement panel
"""

import contextlib
import ctypes
import ctypes.wintypes
import math
import brand
import os
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable, Optional


_POS_LOG_PATH = os.path.join(os.environ.get("TEMP", "."), "ftc_pos_debug.log")


def pos_log(msg: str) -> None:
    """One-line placement log for the multi-monitor saga. Every anchor
    decision and every popup placement writes its inputs and its result, so
    the next 'it opened on the wrong screen' report comes with the exact
    numbers instead of a guess (ask for %TEMP%\\ftc_pos_debug.log). Capped:
    the file is dropped once it passes ~256KB. Never raises."""
    try:
        try:
            if os.path.getsize(_POS_LOG_PATH) > 262144:
                os.remove(_POS_LOG_PATH)
        except OSError:
            pass
        with open(_POS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


# ctypes structs
class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
    ]


# The monitor APIs on a PRIVATE WinDLL instance. ctypes.windll.user32 is one
# CACHED object shared by every module in the process: app_window pinned
# GetMonitorInfoW's argtypes to ITS OWN _MONITORINFO class there (v1.6.51), so
# this module's byref(_MONITORINFO) raised ArgumentError on every call, the
# except swallowed it, and every popup placement fell back to the PRIMARY
# monitor. The entire wrong-screen saga (v1.6.51→v1.6.64) was that one shared
# mutation, not the anchor policy. A private instance has its own function
# objects and cannot be poisoned from outside this module.
_U32_MON = None


def _monitor_user32():
    global _U32_MON
    if _U32_MON is None:
        u32 = ctypes.WinDLL("user32")
        u32.MonitorFromPoint.restype = ctypes.c_void_p
        u32.MonitorFromPoint.argtypes = [_POINT, ctypes.c_ulong]
        u32.MonitorFromWindow.restype = ctypes.c_void_p
        u32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        u32.GetMonitorInfoW.restype = ctypes.c_int
        u32.GetMonitorInfoW.argtypes = [ctypes.c_void_p,
                                        ctypes.POINTER(_MONITORINFO)]
        try:
            u32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            u32.GetThreadDpiAwarenessContext.argtypes = []
        except AttributeError:
            pass
        u32.GetWindowRect.restype = ctypes.c_int
        u32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
        u32.GetParent.restype = ctypes.c_void_p
        u32.GetParent.argtypes = [ctypes.c_void_p]
        u32.MapWindowPoints.restype = ctypes.c_int
        u32.MapWindowPoints.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.POINTER(_RECT), ctypes.c_uint]
        u32.MoveWindow.restype = ctypes.c_int
        u32.MoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int]
        try:  # Windows 10 1607+; absent means real pixels are unreadable
            u32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            u32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            u32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
            u32.GetWindowDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            u32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
            u32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        except AttributeError:
            pass
        _U32_MON = u32
    return _U32_MON


# ── Real pixels for the popup ────────────────────────────────────────────────
# The app is DPI-UNAWARE, so on a scaled monitor every Win32 coordinate it reads
# (monitor rects, window rects, the cursor) is in Windows' scaled space: a 150%
# 1920x1200 laptop reads as 1280x800. For a Tk BORDERLESS window, Windows then
# decides from whichever app window was shown last whether to scale it, all
# measured on Ryan's rig (2026-10-06): with the dashboard open on a 100% screen
# a pill placed at (1443,1700) lands at real pixel (1443,1700) at 1x size; with
# the dashboard hidden, or open on the laptop, it lands at (1690,2010) at 1.5x.
# The dashboard's own dropdowns, tips and toasts open on the dashboard's screen,
# so the two always agree for them. The pill opens on ANOTHER screen, so it
# was placed in one space and drawn in the other: mid-window on the 150% laptop
# while the dashboard sat on a 100% screen, and 1.5x size when it did land.
# The popup is therefore a per-monitor DPI window placed in real pixels.
_DPI_CTX_PER_MONITOR_V2 = -4


class _RealPixels:
    """Context manager: Win32 calls on this thread read real pixels. Restores
    the thread's own DPI context on exit. A no-op where unsupported, which
    leaves the old scaled numbers (correct on an unscaled monitor)."""

    def __enter__(self):
        self._prev = None
        try:
            fn = _monitor_user32().SetThreadDpiAwarenessContext
            self._prev = fn(ctypes.c_void_p(_DPI_CTX_PER_MONITOR_V2))
        except Exception:
            self._prev = None
        return self

    def __exit__(self, *_exc):
        if self._prev:
            try:
                _monitor_user32().SetThreadDpiAwarenessContext(
                    ctypes.c_void_p(self._prev))
            except Exception:
                pass
        return False


class _ThreadDpi:
    """Context manager: put this thread back in a saved DPI context (the
    app's own, from _pill_edit) for the length of the block."""

    def __init__(self, ctx):
        self._ctx = ctx

    def __enter__(self):
        self._prev = None
        if self._ctx:
            try:
                self._prev = _monitor_user32().SetThreadDpiAwarenessContext(
                    ctypes.c_void_p(self._ctx))
            except Exception:
                self._prev = None
        return self

    def __exit__(self, *_exc):
        if self._prev:
            try:
                _monitor_user32().SetThreadDpiAwarenessContext(
                    ctypes.c_void_p(self._prev))
            except Exception:
                pass
        return False


class _NoContext:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _rect_tuple(r) -> tuple:
    return (int(r.left), int(r.top), int(r.right), int(r.bottom))


class OverlayMonitor:
    """One monitor seen two ways: `scaled` is its rect in the app's own
    (DPI-scaled) coordinates, `real` its rect in real pixels, `work` its work
    area (taskbar excluded) in real pixels. real_point/scaled_point convert
    between the two spaces on this monitor."""

    __slots__ = ("scaled", "real", "work")

    def __init__(self, scaled: tuple, real: tuple, work: tuple):
        self.scaled, self.real, self.work = scaled, real, work

    def _ratio(self) -> tuple:
        sw = self.scaled[2] - self.scaled[0]
        sh = self.scaled[3] - self.scaled[1]
        rw = self.real[2] - self.real[0]
        rh = self.real[3] - self.real[1]
        if sw <= 0 or sh <= 0 or rw <= 0 or rh <= 0:
            return 1.0, 1.0
        return rw / sw, rh / sh

    def real_point(self, x: int, y: int) -> tuple:
        fx, fy = self._ratio()
        return (self.real[0] + round((x - self.scaled[0]) * fx),
                self.real[1] + round((y - self.scaled[1]) * fy))

    def scaled_point(self, x: int, y: int) -> tuple:
        fx, fy = self._ratio()
        return (self.scaled[0] + round((x - self.real[0]) / fx),
                self.scaled[1] + round((y - self.real[1]) / fy))


def _overlay_monitor_from_handle(hmon) -> Optional["OverlayMonitor"]:
    if not hmon:
        return None
    u32 = _monitor_user32()
    scaled = _MONITORINFO()
    scaled.cbSize = ctypes.sizeof(_MONITORINFO)
    if not u32.GetMonitorInfoW(hmon, ctypes.byref(scaled)):
        return None
    real = _MONITORINFO()
    real.cbSize = ctypes.sizeof(_MONITORINFO)
    with _RealPixels():
        ok = u32.GetMonitorInfoW(hmon, ctypes.byref(real))
    if not ok:
        real = scaled
    r = real.rcWork
    if r.right <= r.left or r.bottom <= r.top:
        return None
    return OverlayMonitor(_rect_tuple(scaled.rcMonitor),
                          _rect_tuple(real.rcMonitor), _rect_tuple(r))


def overlay_monitor(x: int = 0, y: int = 0,
                    hwnd: int = 0) -> Optional["OverlayMonitor"]:
    """The monitor a borderless window belongs on: the one holding *hwnd* when
    given, else the one nearest the app-coordinate point (x, y). None when
    Win32 is unavailable (test doubles), so callers keep their old maths."""
    try:
        u32 = _monitor_user32()
        if hwnd:
            hmon = u32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        else:
            pt = _POINT()
            pt.x, pt.y = int(x), int(y)
            hmon = u32.MonitorFromPoint(pt, 2)
        return _overlay_monitor_from_handle(hmon)
    except Exception:
        return None


def real_window_rect(hwnd: int) -> Optional[tuple]:
    """Where a window really is on screen, in real pixels."""
    try:
        r = _RECT()
        with _RealPixels():
            ok = _monitor_user32().GetWindowRect(hwnd, ctypes.byref(r))
        return _rect_tuple(r) if ok else None
    except Exception:
        return None


# ── Popup palette (light grey floating pill) ──────────────────────────────────
# The main app window stays dark; the small floating popups use a softer look.
CP = {
    "bg": "#2b2b2b",  # dark-ish grey pill background
    "bg_light": "#3a3a3a",  # slightly lighter for icon/refinement
    "text": "#ffffff",
    "subtext": "#aaaaaa",
    "accent": "#f39200",  # FTC orange
    "accent_hover": "#e08200",
    "divider": "#4a4a4a",
    "btn_bg": "#444444",
    "btn_hover": "#555555",
    # The mic button rides INSIDE the Ask bar, so its circle has to read against
    # btn_bg rather than against the panel background.
    "mic_bg": "#555555",
    "mic_hover": "#666666",
    "bar_idle": "#666666",  # waveform bar — not speaking
    "bar_active": "#f39200",  # waveform bar — speaking (FTC orange)
    "error": "#ff5555",
    "success": "#4ade80",
}

# Keep the dark-theme names aliased so refinement frame code is consistent
C = CP

# Waveform config
NUM_BARS = 16
BAR_W    = 4
BAR_GAP  = 2
BAR_MAX_H = 30
BAR_MIN_H = 5
CANVAS_W = NUM_BARS * (BAR_W + BAR_GAP) - BAR_GAP
CANVAS_H = BAR_MAX_H + 6


def _bar_geom(index: int, height: float) -> tuple[float, float]:
    """(centre_x, half_length) for the line segment that draws bar `index`.

    Bars are round-capped lines rather than rectangles, so the cap adds BAR_W/2
    past each endpoint. The segment is shortened by BAR_W so the drawn height
    still equals `height` and the tallest bar keeps fitting inside CANVAS_H.
    Floored just above zero so the shortest bar renders as a dot — a
    zero-length line draws nothing.
    """
    cx = index * (BAR_W + BAR_GAP) + BAR_W / 2
    return cx, max(0.5, (height - BAR_W) / 2)


# Live-caption bar (shown beneath the waveform when captions are on).
# The bar is a FIXED-WIDTH paragraph block (CAPTION_MAX_CHARS wide) from the very
# first word: text wraps and grows vertically up to CAPTION_MAX_LINES, then
# scrolls. Fixed width means the bar never widens or slides sideways as you speak
# — it reads as a stable left-aligned paragraph the whole time.
# The full transcript-so-far stays in the widget — the view tails the newest
# words, and the user can wheel-scroll back through everything said.
CAPTION_MIN_CHARS = 16   # legacy floor (bar now renders at CAPTION_MAX_CHARS)
CAPTION_MAX_CHARS = 60
CAPTION_MAX_LINES = 5
CAPTION_SCROLL_HOLDOFF = 4.0  # secs after a manual scroll before auto-tail resumes

# The Ask-AI instruction box grows downward as the typed text wraps past the
# right edge, up to this many visible lines, then scrolls internally.
ASK_MAX_LINES = 6
ASK_PLACEHOLDER = "Ask AI, e.g. 'change language to French' or 'make this shorter'"

# How long the post-transcription icon badge stays before auto-dismissing, so it
# never lingers on screen indefinitely.
ICON_AUTO_DISMISS_SECS = 30.0

# The badge gets out of the way the moment the user does anything: ANY key, or
# switching to another app. Both are gated behind a short grace window, because
# the badge appears the instant the text lands — without it, the keystroke the
# user was already mid-way through typing (or the focus settling after
# injection) kills the badge before they can register the ✓/⚠ at all, which
# reads as a flicker rather than a confirmation.
#
# 0.25s, down from 1.2s (v1.6.71). At 1.2s the badge visibly ignored the first
# thing the user did after dictating, which reads as the app being stuck rather
# than as a confirmation — reported as "there's a delay where I can press any
# button and it won't go away". The long window is no longer needed, because
# the two things it was really absorbing are now filtered by identity instead
# of by time:
#
#   * the hotkey's own modifier, still physically held as the badge appears
#     (a held key auto-repeats, and every repeat is another key DOWN), and
#   * the base key of the combo, held for the same reason.
#
# _MODIFIER_KEY_NAMES drops the first; the auto-repeat guard drops both. What
# is left for the grace to cover is only synthetic input from OUR OWN injection
# still draining through the hook thread, which is microseconds, not seconds.
KEY_DISMISS_GRACE_SECS = 0.25

# Keys that never count as "the user pressed a button". A modifier on its own
# does nothing to the document, and the hotkey's modifier is by definition down
# at the moment the badge appears — dismissing on it would kill the badge
# before it could be read, which is the flicker the grace window used to exist
# to prevent. Shift held to capitalise the next word is the same story.
_MODIFIER_KEY_NAMES = frozenset({
    "alt", "alt gr", "left alt", "right alt",
    "ctrl", "left ctrl", "right ctrl",
    "shift", "left shift", "right shift",
    "windows", "left windows", "right windows",
    "caps lock", "num lock", "scroll lock", "fn",
})
# Taking a screenshot is looking AT the badge, not moving on from it. PrtSc
# (every variant arrives as one of these names) and any key pressed while a
# Windows key is held (Win+Shift+S, Win+PrtSc: shell shortcuts that never type
# into the document) must not dismiss it, or the badge is gone before the
# capture happens. Whether it then appears in the capture is decided by the
# "Hide Popup in Screenshots" setting (set_capture_hidden), not by this.
_SCREENSHOT_KEY_NAMES = frozenset({"print screen", "snapshot", "sysrq",
                                   "prtsc", "prt sc"})

# Screen-capture tools take the foreground while the user frames a shot (the
# Win+Shift+S overlay is ScreenClippingHost). Moving focus to one of them is
# not switching apps, so the badge stays for the capture.
_CAPTURE_TOOL_EXES = frozenset({
    "snippingtool.exe", "screenclippinghost.exe", "screensketch.exe",
    "sharex.exe", "greenshot.exe", "lightshot.exe", "snagit32.exe",
    "snagiteditor.exe", "gamebar.exe", "picpick.exe",
})


def _windows_key_held() -> bool:
    """True while either Windows key is physically down (fails closed)."""
    try:
        gaks = ctypes.windll.user32.GetAsyncKeyState
        return bool((gaks(0x5B) | gaks(0x5C)) & 0x8000)
    except Exception:
        return False


def _key_dismisses_badge(name: str, windows_held: bool) -> bool:
    """Whether a fresh key DOWN counts as the user moving on from the badge."""
    name = (name or "").lower()
    if name in _MODIFIER_KEY_NAMES:
        return False          # a modifier alone is not "pressing a button"
    if name in _SCREENSHOT_KEY_NAMES:
        return False          # screenshotting the badge
    if windows_held:
        return False          # Win+Shift+S and other shell shortcuts
    return True


def _foreground_is_capture_tool() -> bool:
    """True when the foreground window belongs to a screen-capture tool."""
    try:
        from injector import _get_fg_exe
        return _get_fg_exe().lower() in _CAPTURE_TOOL_EXES
    except Exception:
        return False


# How often the badge re-checks whether the user has switched away from the app
# the text was injected into. Matches the Dropdown foreground watcher.
_FG_WATCH_INTERVAL_MS = 250

# Z-order upkeep. SetWindowPos flags for "raise to the front of the topmost band
# without touching position, size or focus".
_HWND_TOP          = 0
_HWND_TOPMOST      = -1
_GWL_EXSTYLE       = -20
_WS_EX_TOPMOST     = 0x0008
_SWP_NOSIZE        = 0x0001
_SWP_NOMOVE        = 0x0002
_SWP_NOACTIVATE    = 0x0010
_SWP_NOOWNERZORDER = 0x0200
# How often to re-assert while the popup is on screen. Fast enough that being
# covered is never something the user sees for long, slow enough to be free.
_ONTOP_INTERVAL_MS = 500

# Fine vertical nudge for the fixed popup. The pill sits _POPUP_OFFSET_DEFAULT px
# ABOVE its popup_height baseline out of the box, so it clears the (centred)
# taskbar icons instead of hugging them; the ▴▾ arrows on the pill move it by
# _OFFSET_STEP per click and the result is saved. Clamped to _OFFSET_MAX so it
# can never be parked off the top of the work-area.
_POPUP_OFFSET_DEFAULT = 30
_OFFSET_STEP          = 18
_OFFSET_MAX           = 400
# ▾ can now go BELOW the tier baseline (negative offset), because offset 0 was a
# floor the user hit while still wanting the pill lower — the "low" baseline
# sits just above the taskbar, so 0 is as far down as the work area goes. A
# negative offset deliberately moves the pill into the taskbar strip, and
# _reposition clamps those against the monitor's FULL rect rather than its work
# area so it can still never leave the screen. Bounded, because a pill parked
# entirely off the bottom edge would be unrecoverable without Settings.
_OFFSET_MIN           = -120

# Horizontal placement of the fixed popup. The ◂ ▸ arrows step through these in
# order; each end is a hard stop. "centre" is the shipped default.
_ALIGN_ORDER = ("left", "centre", "right")

# Status-pill padding = the gutter the position arrows live in. Kept at the
# ORIGINAL pill values (14/10) so the box is exactly the size it always was; the
# arrows are small enough to sit in these gutters with a hair of gap to the
# content. NB tk place() coordinates on a PADDED frame are measured from the
# INNER (padded) corner, so the arrows are placed at NEGATIVE offsets
# (-_STATUS_PAD_*) to reach the real box edge; placing them at 0 would pin them
# to the content edge, which is the whole overlap bug.
_STATUS_PAD_X = 14
_STATUS_PAD_Y = 10

# The expanded refinement panel dismisses itself after this long with no
# interaction. Typing in the Ask box, a running AI call, a voice prompt, an
# in-flight upgrade, or the pointer resting over the panel all count as
# activity and restart the countdown.
PANEL_IDLE_DISMISS_SECS = 45.0

# How often an open popup checks whether its content changed size (its size
# is pinned, see FloatingPopup._watch_pinned_size).
_SIZE_WATCH_MS = 50


def _apply_popup_corners(hwnd: int) -> bool:
    """Apply Win11 DWM rounded corners — no GDI clipping, no black artifacts.

    `hwnd` may be a Tk *child* handle: on Windows `Toplevel.winfo_id()` returns
    the inner Tk window, not the frame DWM actually composes. Passing that
    straight to DwmSetWindowAttribute fails with E_HANDLE (0x80070006) and the
    corners stay square — silently, because ctypes does not raise on a bad
    HRESULT. Resolve to the real top-level via GA_ROOT first, and return whether
    the call actually succeeded so callers can tell a no-op from a success.
    """
    try:
        GA_ROOT = 2
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        top = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT) or hwnd
        pref = ctypes.c_int(DWMWCP_ROUND)
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            top, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref), ctypes.sizeof(pref),
        )
        return hr == 0
    except Exception:
        return False


def _display_lines(widget) -> int:
    """How many wrapped rows a tk.Text actually occupies (minimum 1).

    `count(..., "displaylines")` returns the number of display-line BOUNDARIES
    between the two indices, not the number of lines: text occupying three
    wrapped rows answers 2. Every caller here feeds the answer straight into
    `configure(height=…)`, so taking it at face value renders one row short and
    clips the last line — which is what cut the tail off long Ask instructions,
    long captions and long AI results.
    """
    try:
        widget.update_idletasks()
        res = widget.count("1.0", "end-1c", "displaylines")
        if isinstance(res, (tuple, list)):
            n = int(res[0]) if res else 0
        elif res is None:
            n = 0
        else:
            n = int(res)
        return max(1, n + 1)
    except Exception:
        try:
            return max(1, int(widget.index("end-1c").split(".")[0]))
        except Exception:
            return 1


class _RoundedField(tk.Canvas):
    """Hosts a square-cornered tk widget on a rounded-rect background.

    tk.Text has no corner radius and paints an opaque rectangle, so the only way
    to round one is to inset it far enough that its own corners never reach the
    curve and paint the rounding underneath. `fill` matches the child's own bg,
    so the seam between the two is invisible.

    The child keeps driving the layout: callers still size it in character units
    and `sync()` re-reads its requested size, so the popup geometry that hangs
    off that sizing (caption growth, Ask-box autosize) behaves exactly as before.
    """

    def __init__(self, parent, *, fill, radius=6, pad=4, on_resize=None, **kw):
        super().__init__(parent, bg=parent.cget("bg"),
                         highlightthickness=0, bd=0, **kw)
        self._fill = fill
        self._radius = radius
        self._pad = pad
        # Fired when the usable inner width changes. A child that measures its
        # own wrapped height (the Ask box) must re-measure afterwards: until the
        # canvas has laid out, the child still reports its natural width and
        # would count every line as fitting on one row.
        self._on_resize = on_resize
        self._last_inner_w = None
        self._shape = None
        self._shape_photo = None
        self._child = None
        self._win = None
        self._stretch = False
        self._trailing = None
        self._trailing_win = None
        self._trailing_gap = 6
        self._trailing_inset = 6
        self.bind("<Configure>", lambda _e: self._paint())

    def host(self, child, *, stretch: bool = False, trailing=None,
             trailing_gap: int = 6, trailing_inset: int = 6):
        """Embed `child`. stretch=True fills the canvas width (for pack expand),
        else the canvas takes its width from the child's own requested size.

        `trailing` rides INSIDE the field, pinned to its right edge and centred
        on the full height (chat-bar shape: text left, round button right). It is
        inset by `trailing_inset` from the edge rather than by `pad`, so a button
        taller than one text row still sits snugly in the curve, and the text's
        usable width shrinks by the button plus `trailing_gap`.
        """
        self._child = child
        self._stretch = stretch
        self._trailing = trailing
        self._trailing_gap = trailing_gap
        self._trailing_inset = trailing_inset
        self._win = self.create_window(self._pad, self._pad, anchor="nw",
                                       window=child)
        if trailing is not None:
            self._trailing_win = self.create_window(0, 0, anchor="e",
                                                    window=trailing)
        self.sync()
        return child

    def _trailing_w(self) -> int:
        if self._trailing is None:
            return 0
        return self._trailing.winfo_reqwidth() + self._trailing_gap \
            + self._trailing_inset

    def sync(self) -> None:
        """Re-read the child's requested size and resize to wrap it."""
        if self._child is None:
            return
        h = self._child.winfo_reqheight() + self._pad * 2
        if self._trailing is not None:
            # A trailing button taller than one text row must still fit.
            h = max(h, self._trailing.winfo_reqheight()
                    + self._trailing_inset * 2)
        self.configure(height=h)
        if not self._stretch:
            self.configure(width=self._child.winfo_reqwidth()
                           + self._pad * 2 + self._trailing_w())
        self._paint()

    def _paint(self) -> None:
        if self._child is None:
            return
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            return
        if self._shape is not None:
            self.delete(self._shape)
        # PIL first: Canvas polygons have no anti-aliasing, and the smooth=True
        # spline _rr uses does not pass through its control points, so it draws
        # roughly HALF the radius asked for — a bar that reads as barely rounded
        # however high the number goes. round_rect is a true, cached radius.
        photo = None
        try:
            import ui_render
            photo = ui_render.round_rect(self, w, h, self._radius, self._fill,
                                         bg=self.cget("bg"))
        except Exception:
            photo = None
        if photo is not None:
            self._shape_photo = photo  # keep a reference so Tk can't collect it
            self._shape = self.create_image(0, 0, image=photo, anchor="nw")
        else:
            from app_window import _rr
            self._shape = _rr(self, 0, 0, w - 1, h - 1, self._radius,
                              fill=self._fill)
        self.tag_lower(self._shape)
        if self._trailing_win is not None:
            self.coords(self._trailing_win, w - self._trailing_inset, h // 2)
        inner_w = ((w - self._pad * 2 - self._trailing_w()) if self._stretch
                   else self._child.winfo_reqwidth())
        self.itemconfigure(self._win, width=max(1, inner_w),
                           height=max(1, h - self._pad * 2))
        if inner_w != self._last_inner_w:
            self._last_inner_w = inner_w
            if self._on_resize is not None:
                # after_idle so the child has actually re-wrapped at the new
                # width before anything measures it.
                self.after_idle(self._on_resize)


class _CircleButton(tk.Canvas):
    """A round icon button — a filled circle with a centred glyph.

    Drop-in for the old tk.Label mic so its call sites keep working unchanged:
    .configure(text=/fg=/bg=) maps to the glyph/colour/fill and redraws, and the
    <Button-1>/<Enter>/<Leave> binds behave as before. `bg` == the circle fill,
    matching RoundedButton's contract. Fixed diameter so it stays a true circle
    (auto-sizing to the glyph would leave an oval).
    """

    def __init__(self, parent, text="", *, diameter=28, fill=None, fg=None,
                 font=("Segoe UI", 11), command=None, **kw):
        parent_bg = kw.pop("bg", None) or parent.cget("bg")
        super().__init__(parent, width=diameter, height=diameter,
                         bg=parent_bg, highlightthickness=0, bd=0,
                         cursor=kw.pop("cursor", "hand2"), **kw)
        fam = font[0]
        size = font[1] if len(font) > 1 else 11
        weight = "bold" if (len(font) > 2 and font[2] == "bold") else "normal"
        self._font = tkfont.Font(family=fam, size=size, weight=weight)
        self._d = diameter
        self._text = text
        self._fill = fill if fill is not None else CP["btn_bg"]
        self._fg = fg if fg is not None else CP["subtext"]
        self._photo = None
        self._command = command
        if command is not None:
            self.bind("<Button-1>", lambda _e: self._command())
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        d = self._d
        photo = None
        try:
            import ui_render
            # A circle is a rounded rect whose corner radius is half its side.
            photo = ui_render.round_rect(self, d, d, d // 2, self._fill,
                                         bg=self.cget("bg"))
        except Exception:
            photo = None
        if photo is not None:
            self._photo = photo  # keep a reference so Tk can't collect it
            self.create_image(0, 0, image=photo, anchor="nw")
        else:
            self.create_oval(1, 1, d - 1, d - 1, fill=self._fill, outline="")
        # Nudge the glyph up a hair — emoji sit low on their baseline.
        self.create_text(d // 2, d // 2 - 1, text=self._text,
                         fill=self._fg, font=self._font)

    def configure(self, cnf=None, **kw):
        redraw = False
        if "text" in kw:
            self._text = kw.pop("text"); redraw = True
        for k in ("bg", "background"):
            if k in kw:
                self._fill = kw.pop(k); redraw = True
        for k in ("fg", "foreground"):
            if k in kw:
                self._fg = kw.pop(k); redraw = True
        if cnf or kw:
            super().configure(cnf, **kw)
        if redraw:
            self._draw()
    config = configure


class FloatingPopup:
    def __init__(self):
        self.root: Optional[tk.Toplevel] = None

        self._mode: Optional[str] = None
        self._on_insert: Optional[Callable] = None
        self._on_replace: Optional[Callable] = None
        self._on_insert_result: Optional[Callable] = None
        self._session_token: int = 0
        self._target_hwnd: int = 0
        self._cursor_x: int = 0
        self._cursor_y: int = 0
        self._ai_refiner = None
        self._voice_prompt_fn = None
        self._voice_capture_start = None
        self._voice_capture_read = None
        self._voice_capture_stop = None
        self._mic_recording: bool = False
        self._mic_pulse_on: bool = True
        # Voice-prompt bookkeeping — see _apply_voice_text. _voice_last is the
        # exact string the mic last wrote into the Ask box (None = never
        # written), so any other content means the user edited it by hand.
        self._voice_token: int = 0
        self._voice_base: str = ""
        self._voice_drop: int = 0
        self._voice_written_words: int = 0
        self._voice_last: Optional[str] = None
        self._original_text: str = ""
        self._sender_name: str = ""  # the signed-in user's name, for email sign-offs
        self._current_result: Optional[str] = None
        self._inserted_ok: bool = True
        self._ai_busy: bool = False
        # Refine measurement — the raw numbers behind the "Time saved" card's
        # AI-refine line. Elapsed is wall-clock from opening the panel to the
        # user applying a result, so the saving is computed against what the
        # refine ACTUALLY cost, never an assumed figure. See stats.refine_saved_seconds.
        self._refine_started_at: Optional[float] = None
        self._refine_prompt_words: int = 0
        self._refine_prompt_spoken: bool = False
        self._popup_hwnd: int = 0
        self._popup_height: str = "low"  # "low" | "medium" | "high" — vertical placement of the fixed popup
        self._popup_offset: int = _POPUP_OFFSET_DEFAULT  # px lifted above the popup_height baseline (set live by the pill's ▴▾ arrows)
        self._popup_align: str = "centre"  # "left" | "centre" | "right" — horizontal placement (set live by the pill's ◂ ▸ arrows)
        self._arrows_visible: bool = True   # show the ▴▾◂▸ nudge arrows on the pill (config.show_pill_arrows)
        self._dismiss_on_key: bool = True   # the ✓ badge gets out of the way on any keypress (config.badge_dismiss_on_key)
        self._capture_hidden: bool = False  # exclude the popup from screenshots/recordings (config.hide_popup_in_screenshots)
        self._settings_saver = None  # fn(key, value) — persists a nudged position back to config
        self._upgrading: bool = False
        self._upgrade_result: Optional[str] = None

        # Waveform state
        self._mic_level: float = 0.0  # 0.0–1.0, updated by audio thread
        self._waveform_running: bool = False
        self._bar_phases = [i * (2 * math.pi / NUM_BARS) for i in range(NUM_BARS)]

        # Cursor position at last show_status call — used for monitor selection
        self._status_cx: int = 0
        self._status_cy: int = 0

        # Watchdog: guarantees the popup is never left visible-but-empty/stuck.
        # _last_activity is refreshed by the recording animation / caption ticks;
        # _status_entered marks when the current status pill appeared.
        self._last_activity: float = 0.0
        self._status_entered: float = 0.0
        self._icon_entered: float = 0.0
        self._last_shown: float = 0.0  # when any mode last became visible (grace window)
        self._watchdog_started: bool = False
        # Z-order upkeep: -topmost only puts the window in the topmost band, it
        # does not keep it at the front of it (see _assert_topmost).
        self._popup_top_hwnd: int = 0
        self._ontop_tick = None
        self._last_geometry: str = ""

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_ai_refiner(self, refiner) -> None:
        self._ai_refiner = refiner

    def set_sender_name(self, name: str) -> None:
        """The signed-in user's real name (from their FTC account profile), used
        to sign off Email refinements instead of a '[Sender's Name]' placeholder."""
        self._sender_name = (name or "").strip()

    def set_popup_height(self, value: str) -> None:
        """Vertical placement of the fixed popup: "low" (near the taskbar,
        default), "medium" (mid-screen) or "high" (near the top). Applies to the
        next _reposition — no restart needed."""
        self._popup_height = value if value in ("low", "medium", "high") else "low"

    def set_popup_offset(self, value) -> None:
        """Fine vertical nudge (px) applied ON TOP of the popup_height baseline,
        lifting the fixed popup clear of the taskbar. Clamped so a stray value
        can never park it off-screen. Applies to the next _reposition."""
        try:
            self._popup_offset = max(_OFFSET_MIN, min(int(value), _OFFSET_MAX))
        except (TypeError, ValueError):
            self._popup_offset = _POPUP_OFFSET_DEFAULT

    def set_popup_align(self, value) -> None:
        """Horizontal placement of the fixed popup: "left" | "centre" | "right".
        Applies to the next _reposition."""
        self._popup_align = value if value in _ALIGN_ORDER else "centre"

    def set_badge_dismiss_on_key(self, value) -> None:
        """Whether the post-insert ✓ badge disappears the moment the user
        presses any key. Off leaves it up until its own timeout, the ✕, or a
        switch to another app. Applies to the NEXT badge; a badge already on
        screen keeps the behaviour it was armed with, so the setting can never
        change under a badge the user is currently looking at."""
        self._dismiss_on_key = bool(value)

    def set_pill_arrows(self, value) -> None:
        """Show or hide the ▴▾◂▸ nudge arrows on the recording pill. Safe to
        call before initialize() — the flag is applied when the arrows are
        built, and live afterwards. Hiding never loses the saved position."""
        self._arrows_visible = bool(value)
        self._apply_arrow_visibility()

    def _apply_arrow_visibility(self) -> None:
        """place/place_forget the four arrow canvases per the flag. The place
        specs are captured at build time, so a re-show restores the exact
        negative-offset placement that puts each arrow on the box border."""
        specs = getattr(self, "_arrow_place_specs", None)
        if not specs:
            return          # arrows not built yet (pre-initialize)
        with self._pill_edit():
            for canvas, spec in specs:
                try:
                    if self._arrows_visible:
                        canvas.place(**spec)
                    else:
                        canvas.place_forget()
                except tk.TclError:
                    pass

    def set_capture_hidden(self, value) -> None:
        """Exclude (or re-include) the popup in screenshots and screen
        recordings. Safe to call before initialize() — applied on creation."""
        self._capture_hidden = bool(value)
        self._apply_capture_affinity()

    def _apply_capture_affinity(self) -> None:
        """SetWindowDisplayAffinity on the REAL top-level (winfo_id() is the
        CHILD window — the same gotcha _top_hwnd exists for; the affinity call
        on the child succeeds but captures still show the popup). Excluded
        windows stay fully visible on the user's screen but vanish from
        screenshots, Snipping Tool and recorders. Needs Win10 2004+; on older
        builds the call fails and the popup simply stays capturable."""
        if self.root is None:
            return
        try:
            WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11
            wins = getattr(self, "_windows", None) or {}
            children = [h for _w, h in wins.values()] or [self._popup_hwnd]
            for child in children:
                hw = (ctypes.windll.user32.GetAncestor(child, 2) or child
                      if child else 0)
                if hw:
                    ctypes.windll.user32.SetWindowDisplayAffinity(
                        hw,
                        WDA_EXCLUDEFROMCAPTURE if self._capture_hidden
                        else WDA_NONE)
        except Exception:
            pass

    def set_settings_saver(self, fn) -> None:
        """Register a callback fn(key, value) that persists a nudged position
        back to config — called whenever the ▴▾ ◂ ▸ arrows move the pill."""
        self._settings_saver = fn

    def set_voice_prompt_callback(self, fn) -> None:
        self._voice_prompt_fn = fn

    def set_voice_capture_fns(self, start, read, stop) -> None:
        """Recorder-backed audio capture for the voice-prompt mic.
        start() -> bool; read() -> (audio|None, rate); stop() -> (audio|None, rate).
        Replaces the popup opening its own sounddevice stream, which recorded
        the Windows default mic (not the configured device) and could be killed
        mid-read by the recorder watchdog's PortAudio re-init."""
        self._voice_capture_start = start
        self._voice_capture_read = read
        self._voice_capture_stop = stop

    def show_status(
        self,
        text: str,
        hwnd: int = 0,
        recording: bool = False,
        cursor_x: int = 0,
        cursor_y: int = 0,
    ) -> None:
        self._target_hwnd = hwnd
        # Store the anchor the app computed (window-centre first, cursor as
        # fallback — see app._popup_anchor) so the popup opens on the monitor
        # the user is actually working on.
        if cursor_x or cursor_y:
            self._status_cx, self._status_cy = cursor_x, cursor_y
        else:
            self._status_cx, self._status_cy = self._get_cursor_pos()
        if self.root:
            # Use lambda — avoids tkinter after() quirks with boolean positional args
            self.root.after(0, lambda: self._enter_status_mode(text, recording))

    def flash_status(
        self,
        text: str,
        hwnd: int = 0,
        cursor_x: int = 0,
        cursor_y: int = 0,
        ms: int = 1800,
    ) -> None:
        """Show a transient status label, then auto-hide it. Used for one-off
        notices like 'No text selected'. Stamp-guarded so a newer popup (a real
        dictation / refine that starts within the window) is never hidden by this
        timer."""
        self.show_status(text, hwnd=hwnd, recording=False,
                         cursor_x=cursor_x, cursor_y=cursor_y)
        if not self.root:
            return

        def _schedule() -> None:
            stamp = self._status_entered

            def _maybe_hide(s=stamp) -> None:
                if self._mode == "status" and self._status_entered == s:
                    self._do_hide()

            self.root.after(ms, _maybe_hide)

        # _status_entered is stamped inside _enter_status_mode (queued by
        # show_status via after(0)); read it there, after that has run.
        self.root.after(0, _schedule)

    def set_status_text(self, text: str) -> None:
        """Update the status pill label in place, no re-layout. Used to flip
        the honest 'Starting…' cue to 'Recording' once the mic stream is
        proven live. No-op outside status mode, and in caption mode, where
        the label is deliberately empty (the caption bar is the cue there)."""
        if not self.root:
            return

        def _apply() -> None:
            if self._mode != "status":
                return
            try:
                if self._status_label.cget("text"):
                    with self._pill_edit():
                        self._status_label.configure(text=text)
            except tk.TclError:
                pass

        self.root.after(0, _apply)

    def show_cursor_icon(
        self,
        text: str,
        on_insert: Callable = None,
        on_replace: Callable[[str], None] = None,
        inserted: bool = True,
        hwnd: int = 0,
        cursor_x: int = 0,
        cursor_y: int = 0,
        upgrading: bool = False,
        session: int = 0,
        on_insert_result: Callable[[str], None] = None,
        direct_panel: bool = False,
    ) -> None:
        self._on_insert = on_insert
        self._on_replace = on_replace
        self._on_insert_result = on_insert_result
        self._inserted_ok = inserted
        self._target_hwnd = hwnd
        self._original_text = text
        self._current_result = None
        self._upgrading = upgrading
        self._upgrade_result = None
        self._refine_started_at = None
        self._refine_prompt_words = 0
        self._refine_prompt_spoken = False
        # Session token: a slow upgrade thread from a PREVIOUS dictation must
        # not attach its text to this popup (Replace would then undo the new
        # dictation and inject the old one).
        self._session_token = session
        # If explicit cursor coords are provided (e.g. refine-selection flow where
        # show_status was never called), also update _status_cx/cy so _enter_icon_mode
        # and _expand_to_panel position the popup on the correct monitor.
        if cursor_x or cursor_y:
            self._cursor_x, self._cursor_y = cursor_x, cursor_y
            self._status_cx, self._status_cy = cursor_x, cursor_y
        else:
            self._cursor_x, self._cursor_y = self._get_cursor_pos()
        if self.root:
            # direct_panel skips the badge and lands straight on the refine
            # panel. It is the REFINE-SELECTION path only: the user already
            # selected text and pressed the key, so the badge is a step that
            # only asks them to click again. The post-dictation popup keeps
            # its badge -- there the text is already in the document and the
            # panel is the optional second act, not the request.
            self.root.after(
                0, self._expand_to_panel if direct_panel else self._enter_icon_mode)

    def update_mic_level(self, level: float) -> None:
        """Called from the audio thread with RMS level (0.0–1.0)."""
        self._mic_level = max(0.0, min(1.0, level))
        self._last_activity = time.time()

    def set_captions_enabled(self, enabled: bool) -> None:
        """Toggle live-caption display mode (replaces the waveform when on).
        Call before show_status() so the next recording renders the right bar."""
        self._captions_enabled = bool(enabled)

    def update_caption(self, text: str) -> None:
        """Called from the caption loop (background thread) with live partial text.
        The full transcript-so-far is kept in the bar: the view tails the newest
        words, and the user can scroll back through everything said. (Text size
        is trivial even for long dictations — no need to truncate.)"""
        if not text:
            return
        self._last_activity = time.time()
        if self.root:
            self.root.after(0, lambda: self._update_caption_widget(text))

    def hide(self) -> None:
        if self.root:
            self.root.after(0, self._do_hide)

    @property
    def is_user_facing(self) -> bool:
        return self._mode in ("icon", "refinement")

    # ── Tkinter setup ──────────────────────────────────────────────────────────

    def initialize(self, main_root: tk.Tk) -> None:
        """Create the popup Toplevels on the main thread. Call once after main Tk is running.

        Two windows. The recording pill (recording and transcribing) lives in
        a per-monitor DPI window (see _RealPixels): Windows never rescales it,
        so it is the same small, crisp size on every screen and sits exactly
        where _reposition puts it. The badge and the refine panel live in an
        ordinary DPI-unaware window, sized by Windows exactly as before; only
        their placement is measured and corrected (see _reposition)."""
        if self.root is not None:
            return
        pill = self._make_window(main_root, real_px=True)
        main = self._make_window(main_root, real_px=False)
        self._windows = {"pill": pill, "main": main}

        self.root, self._popup_hwnd = pill
        self._popup_top_hwnd = 0
        self._build_status_frame()
        self.root, self._popup_hwnd = main
        self._popup_top_hwnd = 0
        self._build_icon_frame()
        self._build_refinement_frame()

        # Screenshot exclusion may have been requested before the windows
        # existed (config is pushed at startup) — apply it now that they do.
        self._apply_capture_affinity()
        self._start_watchdog()

    def _make_window(self, main_root: tk.Tk, real_px: bool) -> tuple:
        """One borderless popup Toplevel; returns (toplevel, winfo_id)."""
        with (_RealPixels() if real_px else _NoContext()):
            win = tk.Toplevel(main_root)
            # Distinct title (never rendered — the window is borderless): a
            # second window titled "FTC Whisper" made every FindWindowW-by-title
            # lookup a coin flip between the dashboard and this popup.
            win.title(f"{brand.PRODUCT_NAME} Overlay")
            # Hide immediately and park far off-screen BEFORE anything else, so
            # the freshly-created dark Toplevel can never flash as a little black
            # box at the top-left (0,0) for a frame before it's
            # positioned/withdrawn.
            win.withdraw()
            win.geometry("+-4000+-4000")
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.attributes("-alpha", 0.97)
            win.attributes("-toolwindow", True)
            win.configure(bg=CP["bg"])
            win.withdraw()
            win.update_idletasks()
            hwnd = win.winfo_id()

        # WS_EX_NOACTIVATE: popup can never steal focus from the foreground app.
        # This is the critical fix for ChatGPT / browser inputs — without it the
        # recording pill steals focus from Chrome, which clears the ProseMirror /
        # contenteditable focus state so Ctrl+V lands nowhere.
        # Mouse clicks on the popup's own buttons still work normally.
        try:
            GWL_EXSTYLE      = -20
            WS_EX_NOACTIVATE = 0x08000000
            u32 = ctypes.windll.user32
            style = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            u32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        except Exception:
            pass

        # Apply Win11 DWM rounded corners once — no GDI region, no black artifacts.
        _apply_popup_corners(hwnd)
        win.bind("<Configure>", self._on_popup_configure)
        return win, hwnd

    def _use_window(self, name: str) -> None:
        """Point self.root at window `name` ("pill" or "main"), hiding the
        other one."""
        wins = getattr(self, "_windows", None)
        if not wins:
            return
        win, hwnd = wins[name]
        if win is self.root:
            return
        try:
            self.root.withdraw()
        except tk.TclError:
            pass
        self.root, self._popup_hwnd = win, hwnd
        self._popup_top_hwnd = 0
        self._last_geometry = ""

    def _content_size(self) -> tuple:
        """The size the popup's content asks for. The pill's frame is placed
        (see _enter_status_mode), which does not pass its size up to the
        window, so the pill reads it off the frame."""
        if self._is_pill_root():
            f = self._status_frame
            return f.winfo_reqwidth(), f.winfo_reqheight()
        return self.root.winfo_reqwidth(), self.root.winfo_reqheight()

    def _is_pill_root(self) -> bool:
        wins = getattr(self, "_windows", None)
        return bool(wins) and self.root is wins["pill"][0]

    @contextlib.contextmanager
    def _pill_edit(self):
        """Wrap every change to the pill's contents.

        The pill is a per-monitor DPI window but the app's thread is not, and
        Windows rescales every move or resize Tk makes on the pill's inner
        pieces from the app's context: on the 150% laptop each piece came out
        1.5x the size Tk painted, and the unpainted part showed black (the
        glitchy pill, measured 2026-10-06). Tk lays pieces out from its idle
        queue, so the change and the flush must both happen in real pixels:
        everything else pending is flushed first in the app's own context (so
        the dashboard and the badge window are never laid out in real
        pixels), then the pill is edited and laid out inside _RealPixels."""
        if not self._is_pill_root() or getattr(self, "_pill_depth", 0):
            yield
            return
        try:
            self.root.update_idletasks()
        except tk.TclError:
            pass
        try:
            self._pill_app_ctx = (
                _monitor_user32().GetThreadDpiAwarenessContext())
        except Exception:
            self._pill_app_ctx = None
        self._pill_depth = 1
        try:
            with _RealPixels():
                yield
                try:
                    self.root.update_idletasks()
                except tk.TclError:
                    pass
        finally:
            self._pill_depth = 0

    def _heal_pill_layout(self) -> int:
        """Safety net for _pill_edit: put back any pill piece Windows has
        rescaled (a change that slipped past _pill_edit). Compares each mapped
        piece's real rect with where Tk laid it out and moves it back.
        Returns how many pieces it moved; logged, never silent."""
        if not self._is_pill_root():
            return 0
        try:
            u32 = _monitor_user32()
        except Exception:
            return 0
        fixed = []
        with _RealPixels():
            stack = [self.root]
            while stack:
                w = stack.pop()
                try:
                    if not w.winfo_ismapped():
                        continue
                    kids = w.winfo_children()
                    hwnd = int(w.winfo_id())
                    if w is self.root:
                        want = (0, 0, w.winfo_width(), w.winfo_height())
                    else:
                        want = (w.winfo_x(), w.winfo_y(),
                                w.winfo_width(), w.winfo_height())
                except tk.TclError:
                    continue
                stack.extend(kids)
                r = _RECT()
                if not u32.GetWindowRect(hwnd, ctypes.byref(r)):
                    continue
                parent = u32.GetParent(hwnd)
                if not parent:
                    continue
                u32.MapWindowPoints(None, parent, ctypes.byref(r), 2)
                got = (r.left, r.top, r.right - r.left, r.bottom - r.top)
                if got != want and want[2] > 1 and want[3] > 1:
                    u32.MoveWindow(hwnd, *want, 1)
                    fixed.append(f"{w.winfo_class()}{got}->{want}")
        if fixed:
            pos_log(f"pill heal moved {len(fixed)}: " + " ".join(fixed[:6]))
            self._repaint_popup()
        return len(fixed)

    def owned_hwnds(self) -> tuple:
        """Every window handle the popup owns (both windows, tkinter's child
        and the real top-level), so a foreground check can't miss either."""
        out = []
        wins = getattr(self, "_windows", None) or {}
        pairs = list(wins.values()) or [(self.root, self._popup_hwnd)]
        for _win, hwnd in pairs:
            if not hwnd:
                continue
            out.append(int(hwnd))
            try:
                out.append(int(ctypes.windll.user32.GetAncestor(hwnd, 2) or 0))
            except Exception:
                pass
        return tuple(h for h in out if h)

    def _start_watchdog(self) -> None:
        if self._watchdog_started or not self.root:
            return
        self._watchdog_started = True
        self.root.after(2000, self._watchdog)

    def _watchdog(self) -> None:
        """Safety net: never leave an empty/stuck box on screen.

        A real recording animates the waveform (or ticks the caption timer)
        every <100 ms, so _last_activity stays fresh; this only fires when the
        animation has stopped but the pill is still up (a stuck/blank box).
        Never touches the user-facing icon/refinement badges.
        """
        try:
            now = time.time()

            # Content-truth check FIRST: if the window is on screen but NO frame
            # is packed, it's a contentless box no matter what _mode claims → hide.
            # winfo_ismapped reflects this Toplevel's own shown/withdrawn state.
            try:
                viewable = bool(self.root.winfo_ismapped())
            except Exception:
                viewable = False
            # Grace period: never act on a pill that JUST appeared — its frame
            # may be packed but not yet mapped for one event-loop cycle.
            shown_recently = (now - self._last_shown) < 4.0
            if viewable and not shown_recently:
                try:
                    any_frame = any(
                        f.winfo_ismapped()
                        for f in (self._status_frame, self._icon_frame, self._refine_frame)
                    )
                except Exception:
                    any_frame = True  # fail-safe: never hide on inspection error
                if not any_frame:
                    print("[Popup] Watchdog: visible window with no packed frame -> hiding")
                    self._do_hide()
                    if self.root:
                        self.root.after(2000, self._watchdog)
                    return

            if self._mode == "status":
                stuck_recording = (
                    self._rec_start is not None and (now - self._last_activity) > 12.0
                )
                hung_transcribing = (
                    self._rec_start is None and (now - self._status_entered) > 60.0
                )
                if stuck_recording or hung_transcribing:
                    print(
                        f"[Popup] Watchdog hiding stuck status pill "
                        f"(recording={stuck_recording}, transcribing={hung_transcribing})"
                    )
                    self._do_hide()
            elif self._mode == "icon":
                # The post-transcription badge is a brief affordance — auto-dismiss
                # it so it never sits on screen indefinitely (the user's complaint).
                if self._icon_entered and (now - self._icon_entered) > ICON_AUTO_DISMISS_SECS:
                    print("[Popup] Watchdog auto-dismissing lingering icon badge")
                    self._do_hide()
            elif self._mode is None:
                # Mode says hidden but the window is somehow still on screen → re-hide.
                try:
                    if self.root.winfo_viewable():
                        self.root.withdraw()
                except Exception:
                    pass
        except Exception:
            pass
        if self.root:
            self.root.after(2000, self._watchdog)

    def _top_hwnd(self) -> int:
        """The REAL top-level window handle.

        On Windows tkinter's winfo_id() hands back a CHILD window whose parent is
        the wrapper Tk actually manages (verified: the child carries exstyle
        0x04, the parent carries TOPMOST|TOOLWINDOW). Z-order, topmost and
        repaint all belong to the parent, so calling them on winfo_id() silently
        does nothing at all."""
        if not self._popup_top_hwnd:
            try:
                GA_ROOT = 2
                self._popup_top_hwnd = (
                    ctypes.windll.user32.GetAncestor(self._popup_hwnd, GA_ROOT)
                    or self._popup_hwnd)
            except Exception:
                self._popup_top_hwnd = self._popup_hwnd
        return self._popup_top_hwnd

    def _assert_topmost(self) -> None:
        """Push the popup back to the FRONT of the topmost band.

        `-topmost` only puts a window in that band; it does not keep it at the
        front of it. The taskbar is topmost too, and so is every other app's
        always-on-top window — whichever was raised last wins, which is how the
        recording pill ended up behind the taskbar after an app switch. Cheap
        (one SetWindowPos), and SWP_NOACTIVATE means re-asserting never takes
        focus off whatever the user is typing into.

        The raise MUST be HWND_TOP, not HWND_TOPMOST: SetWindowPos with
        HWND_TOPMOST on a window that is ALREADY topmost fails outright — it
        returns 0 and the Z-order does not move (measured, both ways round).
        HWND_TOP raises within whichever band the window is in, so it is
        HWND_TOPMOST that establishes the band and HWND_TOP that wins it."""
        h = self._top_hwnd()
        if not h:
            return
        try:
            u32 = ctypes.windll.user32
            flags = (_SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
                     | _SWP_NOOWNERZORDER)
            if not (u32.GetWindowLongW(h, _GWL_EXSTYLE) & _WS_EX_TOPMOST):
                u32.SetWindowPos(h, _HWND_TOPMOST, 0, 0, 0, 0, flags)
            u32.SetWindowPos(h, _HWND_TOP, 0, 0, 0, 0, flags)
        except Exception:
            pass

    def _keep_on_top(self) -> None:
        """Re-assert Z-order for as long as anything is on screen. One pass at
        show time is not enough: the pill is up for the whole dictation and the
        user switches apps, clicks the taskbar and opens other always-on-top
        windows while it is."""
        self._ontop_tick = None
        if not self.root or self._mode is None:
            return
        self._assert_topmost()
        try:
            self._ontop_tick = self.root.after(_ONTOP_INTERVAL_MS, self._keep_on_top)
        except tk.TclError:
            self._ontop_tick = None

    def _start_keep_on_top(self) -> None:
        if self._ontop_tick is None:
            self._keep_on_top()

    def _stop_keep_on_top(self) -> None:
        if self._ontop_tick is not None:
            try:
                self.root.after_cancel(self._ontop_tick)
            except Exception:
                pass
            self._ontop_tick = None

    def _repaint_popup(self) -> None:
        """Force the whole frame to redraw where it now is.

        Moving or resizing a mapped overrideredirect window lets Windows blit the
        old pixels into the new position — the half-drawn, wrong-content pill.
        Refuses hwnd 0: RedrawWindow(NULL, …) repaints the DESKTOP."""
        h = self._top_hwnd()
        if not h:
            return
        try:
            RDW_INVALIDATE, RDW_ERASE = 0x0001, 0x0004
            RDW_ALLCHILDREN, RDW_UPDATENOW = 0x0080, 0x0100
            ctypes.windll.user32.RedrawWindow(
                h, None, None,
                RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW)
        except Exception:
            pass

    def _set_no_activate(self, enabled: bool) -> None:
        """Enable or disable WS_EX_NOACTIVATE on the popup window."""
        try:
            GWL_EXSTYLE      = -20
            WS_EX_NOACTIVATE = 0x08000000
            u32 = ctypes.windll.user32
            style = u32.GetWindowLongW(self._popup_hwnd, GWL_EXSTYLE)
            if enabled:
                u32.SetWindowLongW(self._popup_hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
            else:
                u32.SetWindowLongW(self._popup_hwnd, GWL_EXSTYLE, style & ~WS_EX_NOACTIVATE)
        except Exception:
            pass

    def _show_no_activate(self) -> None:
        """
        Show the popup window WITHOUT stealing keyboard focus from the active app.

        tkinter's deiconify() calls ShowWindow(SW_SHOW=5) which ACTIVATES the
        window and steals focus — even when WS_EX_NOACTIVATE is set (that flag
        only prevents activation on mouse click, not on ShowWindow).

        Strategy:
          1. Remember who currently has focus.
          2. Call deiconify() + lift() as normal (lets tkinter track internal state).
          3. Immediately give focus back to whoever had it before.

        This keeps tkinter's internal window-state consistent while ensuring the
        foreground app (e.g. Chrome with ChatGPT open) never loses keyboard focus.
        """
        u32 = ctypes.windll.user32
        prev_fg = u32.GetForegroundWindow()
        self.root.deiconify()
        self.root.lift()
        # update_idletasks() ensures tkinter finishes the ShowWindow call so our
        # process is registered as foreground before we hand focus back.
        self.root.update_idletasks()
        if prev_fg and prev_fg != self._popup_hwnd:
            try:
                # AllowSetForegroundWindow(-1) clears the foreground lock —
                # without it SetForegroundWindow can silently fail even when
                # we are the current foreground process.
                u32.AllowSetForegroundWindow(-1)
                u32.SetForegroundWindow(prev_fg)
            except Exception:
                pass
        # AFTER handing focus back, not before: activating another window raises
        # it, and the taskbar shares our band. Raise ONCE so the pill appears on
        # top — but do NOT re-assert on a timer: the continuous keep-on-top loop
        # (removed here) is what kept the pill fighting the taskbar back to the
        # front every 500ms, so switching apps and clicking the taskbar buried
        # under the pill. It stays -topmost (above ordinary windows, so you can
        # see you're recording) and simply yields when the taskbar or another
        # topmost window is raised — the pre-v1.6.52 behaviour, plus the position
        # nudge below the taskbar so there is nothing to overlap in the first place.
        self._assert_topmost()
        self._repaint_popup()

    def _on_popup_configure(self, event) -> None:
        pass  # corners handled once at initialize via DWM

    # ── Status frame (recording / transcribing pill) ───────────────────────────

    def _build_status_frame(self) -> None:
        # The padding is the gutter the position arrows live in: it holds the
        # content (timer, waveform, label) well inside the box so the arrows can
        # sit hard against the border, clear of everything. See _STATUS_PAD_*.
        f = tk.Frame(self.root, bg=CP["bg"],
                     padx=_STATUS_PAD_X, pady=_STATUS_PAD_Y)
        self._status_frame = f

        # Top row: timer | waveform | status label — packed left-to-right.
        # The live-caption bar (below) stacks underneath this row.
        row = tk.Frame(f, bg=CP["bg"])
        self._status_row = row
        row.pack(side="top", fill="x")

        # Timer label  e.g. "01:16.2"
        self._timer_var = tk.StringVar(value="")
        self._timer_lbl = tk.Label(
            row,
            textvariable=self._timer_var,
            fg=CP["text"],
            bg=CP["bg"],
            font=("Consolas", 13, "bold"),
        )
        # NOT packed here — packed on demand in _enter_status_mode

        # Waveform canvas — bars animated by microphone level
        self._wave_canvas = tk.Canvas(
            row,
            width=CANVAS_W,
            height=CANVAS_H,
            bg=CP["bg"],
            highlightthickness=0,
        )
        # NOT packed here — packed on demand in _enter_status_mode
        self._bar_ids: list[int] = []
        self._draw_bars_initial()

        # Status text label  "Recording…" / "Transcribing…"
        self._status_label = tk.Label(
            row,
            text="",
            fg=CP["subtext"],
            bg=CP["bg"],
            font=("Segoe UI", 11, "bold"),
        )
        # Packed at build time — always visible in the status row
        self._status_label.pack(side="left")

        # ── Live-caption bar ────────────────────────────────────────────────
        # When live captions are on, the waveform stays on top and this bar is
        # shown beneath it. It grows horizontally with the text until it hits
        # the max width, then wraps and grows vertically up to CAPTION_MAX_LINES,
        # then scrolls (tailing the latest words). Not packed here — packed on
        # demand in _enter_status_mode.
        self._captions_enabled = False
        self._caption_wrap = tk.Frame(f, bg=CP["bg"])
        self._caption_box = _RoundedField(
            self._caption_wrap, fill=CP["bg_light"], radius=6, pad=4
        )
        self._caption_text = tk.Text(
            self._caption_box,
            fg=CP["text"],
            bg=CP["bg_light"],
            font=("Segoe UI", 11),
            wrap="word",
            relief="flat",
            bd=0,
            highlightthickness=0,
            width=CAPTION_MAX_CHARS,   # fixed paragraph width from the first word
            height=1,
            padx=10,
            pady=6,
            state="disabled",
            cursor="arrow",
        )
        self._caption_scroll = tk.Scrollbar(
            self._caption_wrap,
            orient="vertical",
            command=self._caption_text.yview,
            bg="#3a3a3a",
            troughcolor=CP["bg"],
            activebackground="#505050",
            relief="flat",
            borderwidth=0,
            elementborderwidth=0,
            highlightthickness=0,
            bd=0,
            width=10,
        )
        self._caption_text.configure(yscrollcommand=self._caption_scroll.set)
        self._caption_box.host(self._caption_text)
        self._caption_box.pack(side="left", fill="both", expand=True)
        self._caption_lines = 0  # last rendered visible-line count (reposition debounce)
        # Manual scrollback: Windows routes wheel input to the hovered window
        # even though the popup never activates (WS_EX_NOACTIVATE), so a wheel
        # binding is enough. A manual scroll pauses auto-tailing briefly so the
        # view doesn't snap back to the end while the user is reading.
        self._caption_user_scroll_ts = 0.0
        self._caption_text.bind("<MouseWheel>", self._on_caption_wheel)
        self._caption_scroll.bind(
            "<ButtonPress-1>",
            lambda _e: setattr(self, "_caption_user_scroll_ts", time.time()),
            add="+",
        )

        # ── Position nudge arrows ───────────────────────────────────────────
        # Four small triangles drawn on tiny canvases, pinned FLUSH to the four
        # edges and sitting in the 18px gutters — so they never touch the timer,
        # waveform or label. The rule: arrows only ever live on the edges. ▲ top
        # / ▼ bottom move the pill up / down, ◀ / ▶ at the far sides move it left
        # / right. Canvas (not a Label) gives an exact small size — a Label's
        # font line-height made the glyph big enough to crowd the waveform. Each
        # nudge is saved so it sticks; they ride the status frame (placed), so
        # they appear and vanish with the pill. WS_EX_NOACTIVATE lets the pill
        # take the click without stealing focus, so they work mid-dictation.
        def _tri(w_, h_, pts):
            c = tk.Canvas(f, width=w_, height=h_, bg=CP["bg"],
                          highlightthickness=0, bd=0, cursor="hand2")
            c.create_polygon(pts, fill=CP["subtext"], outline="", tags="tri")
            return c
        # Each triangle's tip reaches 1px from the canvas edge, and every canvas
        # is pinned flush to its pill edge, so the arrows hug the very edges with
        # only a hair of gap — and the wide gutters keep them off the content.
        self._pos_up    = _tri(16, 6, (3, 5, 13, 5, 8, 1))
        self._pos_down  = _tri(16, 6, (3, 1, 13, 1, 8, 5))
        self._pos_left  = _tri(6, 16, (5, 3, 5, 13, 1, 8))
        self._pos_right = _tri(6, 16, (1, 3, 1, 13, 5, 8))
        # Negative offsets cancel the frame padding so each arrow lands on the
        # real box border (tip ~1px off the edge), NOT the padded content edge.
        # Specs are kept so the show_pill_arrows toggle can re-place them
        # exactly after a hide (place_forget drops the geometry).
        self._arrow_place_specs = (
            (self._pos_up,    dict(relx=0.5, y=-_STATUS_PAD_Y, anchor="n")),
            (self._pos_down,  dict(relx=0.5, rely=1.0, y=_STATUS_PAD_Y,
                                   anchor="s")),
            (self._pos_left,  dict(x=-_STATUS_PAD_X, rely=0.5, anchor="w")),
            (self._pos_right, dict(relx=1.0, x=_STATUS_PAD_X, rely=0.5,
                                   anchor="e")),
        )
        self._apply_arrow_visibility()
        for _c, _fn in ((self._pos_up,    lambda: self._nudge_position(+1)),
                        (self._pos_down,  lambda: self._nudge_position(-1)),
                        (self._pos_left,  lambda: self._nudge_h_position(-1)),
                        (self._pos_right, lambda: self._nudge_h_position(+1))):
            _c.bind("<Button-1>", lambda _e, fn=_fn: fn())
            _c.bind("<Enter>", lambda _e, c=_c: c.itemconfigure("tri", fill=CP["text"]))
            _c.bind("<Leave>", lambda _e, c=_c: c.itemconfigure("tri", fill=CP["subtext"]))

        # Recording start time (for timer)
        self._rec_start: Optional[float] = None

    def _nudge_position(self, direction: int):
        """Move the fixed popup up (+1) or down (-1) by one step and remember it.

        Down no longer stops at the tier baseline: offset 0 puts the pill just
        above the taskbar, and that was a floor users hit while still wanting it
        lower. Below 0 the pill moves down into the taskbar strip, clamped by
        _reposition against the monitor's full rect so it stays on screen.
        Repositions live and persists via the settings saver."""
        new = max(_OFFSET_MIN,
                  min(self._popup_offset + direction * _OFFSET_STEP, _OFFSET_MAX))
        if new != self._popup_offset:
            self._popup_offset = new
            self._commit_position("popup_offset", new)
        return "break"

    def _nudge_h_position(self, direction: int):
        """Move the fixed popup left (-1) or right (+1) one place through
        left/centre/right and remember it. Each end is a hard stop."""
        try:
            i = _ALIGN_ORDER.index(self._popup_align)
        except ValueError:
            i = 1
        j = max(0, min(i + direction, len(_ALIGN_ORDER) - 1))
        if j != i:
            self._popup_align = _ALIGN_ORDER[j]
            self._commit_position("popup_align", _ALIGN_ORDER[j])
        return "break"

    def _commit_position(self, key: str, value) -> None:
        """Reposition the pill live and persist the new placement to config."""
        try:
            self._reposition(self._status_cx, self._status_cy)
        except Exception:
            pass
        if self._settings_saver:
            try:
                self._settings_saver(key, value)
            except Exception:
                pass

    def _draw_bars_initial(self) -> None:
        self._wave_canvas.delete("all")
        self._bar_ids = []
        self._bars_active = False
        mid = CANVAS_H // 2
        for i in range(NUM_BARS):
            cx, half = _bar_geom(i, BAR_MIN_H)
            bid = self._wave_canvas.create_line(
                cx,
                mid - half,
                cx,
                mid + half,
                fill=CP["bar_idle"],
                width=BAR_W,
                capstyle="round",
            )
            self._bar_ids.append(bid)

    def _animate_waveform(self) -> None:
        """Called every 40 ms while recording — updates bar heights.

        IMPORTANT: the try/except around the body is intentional and must stay.
        In the PyInstaller frozen build (console=False) any unhandled exception
        inside a tkinter after() callback is silently swallowed, which breaks
        the after(40, ...) chain and freezes the bars permanently. Wrapping the
        body ensures we always reschedule even if a single frame fails.
        """
        if not self._waveform_running:
            return

        try:
            # Colour is a one-off, not a per-frame job: the bars are orange for
            # the whole recording. Re-sending the same fill for every bar at
            # 25fps was ~500 no-op Tcl round-trips a second on the UI thread.
            if not getattr(self, "_bars_active", False):
                for bid in self._bar_ids:
                    self._wave_canvas.itemconfigure(bid, fill=CP["bar_active"])
                self._bars_active = True
            level = self._mic_level
            t     = time.time()
            self._last_activity = t
            mid   = CANVAS_H // 2

            # Idle ceiling: bars oscillate up to 30 % of full height even in silence.
            # Voice ceiling: bars can reach 100 % when speaking.
            idle_max = BAR_MIN_H + (BAR_MAX_H - BAR_MIN_H) * 0.30

            for i, bid in enumerate(self._bar_ids):
                phase = self._bar_phases[i]

                # Gentle idle wave — always visible even with no microphone input
                idle_osc = math.sin(t * 4.0 + phase) * 0.5 + 0.5        # 0 → 1
                h_idle   = BAR_MIN_H + (idle_max - BAR_MIN_H) * idle_osc

                # Voice spike — grows with mic level, faster oscillation per bar
                voice_osc = math.sin(t * 10.0 + phase * 1.6) * 0.4 + 0.6  # 0.2 → 1.0
                h_voice   = (BAR_MAX_H - idle_max) * level * voice_osc

                h = max(BAR_MIN_H, min(BAR_MAX_H, h_idle + h_voice))

                cx, half = _bar_geom(i, h)
                self._wave_canvas.coords(bid, cx, mid - half, cx, mid + half)

            # Update timer
            if self._rec_start is not None:
                elapsed = time.time() - self._rec_start
                mins = int(elapsed) // 60
                secs = elapsed % 60
                self._timer_var.set(f"{mins:02d}:{secs:04.1f}")

        except Exception:
            pass  # never let a single-frame error kill the animation loop

        self.root.after(40, self._animate_waveform)

    # ── Icon frame ─────────────────────────────────────────────────────────────

    def _build_icon_frame(self) -> None:
        # About 10% smaller than v1.8.2's (Ryan, 2026-10-06).
        self._icon_frame = tk.Frame(self.root, bg=CP["bg"], padx=7, pady=5)

        from logo_cache import get_badge_photo

        # The chain and Echo: the product's own mark on the thing that pops up.
        self._icon_photo = get_badge_photo(self.root, CP["bg"], height=25)

        if self._icon_photo:
            lbl = tk.Label(
                self._icon_frame, image=self._icon_photo, bg=CP["bg"], cursor="hand2"
            )
        else:
            lbl = tk.Label(
                self._icon_frame,
                text=brand.PRODUCT_SHORT_NAME,
                fg=CP["accent"],
                bg=CP["bg"],
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
            )
        lbl.pack(side="left", padx=(0, 2))

        tk.Frame(self._icon_frame, bg=CP["divider"], width=1).pack(
            side="left", fill="y", padx=(2, 4)
        )

        close = tk.Label(
            self._icon_frame,
            text="✕",
            fg=CP["subtext"],
            bg=CP["bg"],
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            padx=3,
        )
        close.pack(side="left")

        def _close_click(_e):
            self.root.after(0, self._do_hide)
            return "break"

        close.bind("<Button-1>", _close_click)
        close.bind("<Enter>", lambda _e: close.configure(fg=CP["accent"]))
        close.bind("<Leave>", lambda _e: close.configure(fg=CP["subtext"]))

        for w in (self._icon_frame, lbl):
            w.bind("<Button-1>", lambda _e: self.root.after(0, self._expand_to_panel))
            w.bind("<Enter>", lambda _e: self._icon_frame.configure(bg=CP["btn_bg"]))
            w.bind("<Leave>", lambda _e: self._icon_frame.configure(bg=CP["bg"]))

        self._dismiss_hooks = []
        self._fg_watch_tick = None

    # ── Refinement frame ───────────────────────────────────────────────────────

    def _build_refinement_frame(self) -> None:
        from app_window import RoundedButton
        f = tk.Frame(self.root, bg=CP["bg"], padx=16, pady=14)
        self._refine_frame = f

        # ── Row 1: status badge + Insert + AI preset buttons + close ──────────
        top = tk.Frame(f, bg=CP["bg"])
        top.pack(fill="x", pady=(0, 6))

        self._inserted_badge = tk.Label(
            top,
            text="  ✓ Inserted  ",
            fg=CP["bg"],
            bg=CP["accent"],
            font=("Segoe UI", 9, "bold"),
            padx=4,
            pady=3,
        )
        self._inserted_badge.pack(side="left", padx=(0, 6))

        # Insert button — manual fallback if auto-inject missed
        insert_btn = RoundedButton(
            top, text="↓ Insert", command=self._do_insert,
            fg=CP["text"], fill=CP["btn_bg"],
            font=("Segoe UI", 9, "bold"), padx=10, pady=4, radius=3,
        )
        insert_btn.pack(side="left", padx=(0, 10))
        insert_btn.bind("<Enter>", lambda _e: insert_btn.configure(bg=CP["accent"], fg=CP["bg"]))
        insert_btn.bind("<Leave>", lambda _e: insert_btn.configure(bg=CP["btn_bg"], fg=CP["text"]))

        for label, mode in [
            ("✉ Email", "email"),
            ("🎩 Formal", "formal"),
            ("💬 Casual", "casual"),
            ("✨ Fix All", "punctuation"),
            ("✂ Short", "concise"),
            ("⚡ Optimise", "prompt_optimiser"),
        ]:
            self._btn(top, label, lambda m=mode: self._run_ai(m)).pack(
                side="left", padx=(0, 4)
            )

        close = tk.Label(
            top, text="✕", fg=CP["subtext"], bg=CP["bg"],
            font=("Segoe UI", 13), cursor="hand2", padx=8,
        )
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self._do_hide())
        close.bind("<Enter>", lambda _e: close.configure(fg=CP["accent"]))
        close.bind("<Leave>", lambda _e: close.configure(fg=CP["subtext"]))

        # ── Row 2: Ask AI custom instruction input ────────────────────────────
        ask_row = tk.Frame(f, bg=CP["bg"])
        ask_row.pack(fill="x", pady=(0, 6))

        # Multi-line, word-wrapping instruction box: starts one line high and
        # grows downward (up to ASK_MAX_LINES) as the text wraps past the right
        # edge — Text, not Entry, because Entry is single-line and scrolls
        # horizontally instead of expanding.
        self._ask_lines = 1
        self._ask_showing_placeholder = True
        # Radius bumped (and pad raised to match, so the square-cornered child
        # never pokes past the wider curve) to sit closer to the rest of the
        # estate's rounded input fields (FTC Contacts et al.).
        self._ask_box = _RoundedField(ask_row, fill=CP["btn_bg"], radius=14, pad=8,
                                      on_resize=lambda: self._autosize_ask())
        self._ask_entry = tk.Text(
            self._ask_box,
            height=1,
            wrap="word",
            bg=CP["btn_bg"],
            fg=CP["subtext"],
            insertbackground=CP["text"],
            relief="flat",
            font=("Segoe UI", 10),
            bd=0,
            padx=6,
            pady=4,
            highlightthickness=0,
        )
        # Round icon button INSIDE the bar, on its right edge — the shape every
        # chat bar in the estate uses. Parented to the field (not the row) so it
        # rides the rounded background, and given a lighter fill so the circle
        # still reads against it.
        self._mic_btn = _CircleButton(
            self._ask_box,
            text="🎙",
            diameter=30,
            bg=CP["btn_bg"],
            fill=CP["mic_bg"],
            fg=CP["subtext"],
            font=("Segoe UI", 11),
            command=self._on_mic_click,
        )
        self._mic_btn.bind("<Enter>", lambda _e: self._mic_btn.configure(fg=CP["text"], bg=CP["mic_hover"]) if not self._mic_recording else None)
        self._mic_btn.bind("<Leave>", lambda _e: self._mic_btn.configure(fg=CP["subtext"], bg=CP["mic_bg"]) if not self._mic_recording else None)

        self._ask_box.host(self._ask_entry, stretch=True, trailing=self._mic_btn)
        self._ask_box.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._ask_entry.insert("1.0", ASK_PLACEHOLDER)

        def _clear_placeholder(_e=None):
            if self._ask_showing_placeholder:
                self._ask_entry.delete("1.0", "end")
                self._ask_entry.configure(fg=CP["text"])
                self._ask_showing_placeholder = False
                self._autosize_ask()

        def _restore_placeholder(_e=None):
            if not self._ask_entry.get("1.0", "end-1c").strip():
                self._ask_entry.delete("1.0", "end")
                self._ask_entry.insert("1.0", ASK_PLACEHOLDER)
                self._ask_entry.configure(fg=CP["subtext"])
                self._ask_showing_placeholder = True
                self._autosize_ask()

        def _on_return(_e):
            self._run_ai_custom()
            return "break"  # submit on Enter — don't insert a newline

        self._ask_entry.bind("<FocusIn>", _clear_placeholder)
        self._ask_entry.bind("<FocusOut>", _restore_placeholder)
        self._ask_entry.bind("<Return>", _on_return)
        self._ask_entry.bind("<Shift-Return>", lambda _e: self._autosize_ask())
        self._ask_entry.bind(
            "<KeyRelease>",
            lambda _e: (self._touch_panel_activity(), self._autosize_ask()))

        ask_btn = RoundedButton(
            ask_row, text="✦ Ask", command=self._run_ai_custom,
            fg=CP["bg"], fill=CP["accent"],
            font=("Segoe UI", 10, "bold"), padx=12, pady=6, radius=3,
        )
        ask_btn.pack(side="left")
        ask_btn.bind("<Enter>", lambda _e: ask_btn.configure(bg=CP["accent_hover"]))
        ask_btn.bind("<Leave>", lambda _e: ask_btn.configure(bg=CP["accent"]))

        # ── Status / spinner ──────────────────────────────────────────────────
        self._ai_status = tk.Label(
            f, text="", fg=CP["accent"], bg=CP["bg"],
            font=("Segoe UI", 10, "italic"),
        )
        # Not packed initially — shown only when there is content to display

        # ── Result area ───────────────────────────────────────────────────────
        self._result_frame = tk.Frame(f, bg=CP["bg"])

        tk.Frame(self._result_frame, bg=CP["divider"], height=1).pack(
            fill="x", pady=(4, 8)
        )

        # Scrollable text area — shows full result no matter how long,
        # capped at 8 lines tall then scrolls.
        txt_frame = tk.Frame(self._result_frame, bg=CP["bg"])
        txt_frame.pack(fill="x", anchor="w")

        self._result_text = tk.Text(
            txt_frame,
            fg=CP["subtext"],
            bg=CP["bg"],
            font=("Segoe UI", 12),
            wrap="word",
            relief="flat",
            bd=0,
            highlightthickness=0,
            width=52,
            height=4,       # initial height — grows up to 8 lines
            state="disabled",
            cursor="arrow",
        )
        self._result_scrollbar = tk.Scrollbar(
            txt_frame, orient="vertical",
            command=self._result_text.yview,
            bg="#3a3a3a", troughcolor=CP["bg"],
            activebackground="#505050",
            relief="flat", borderwidth=0,
            elementborderwidth=0,
            highlightthickness=0, bd=0, width=10,
        )
        self._result_text.configure(yscrollcommand=self._result_scrollbar.set)
        # The popup is its own topmost window, so the dashboard's global wheel
        # bind never reaches it — a long refine result could only be scrolled by
        # dragging the scrollbar. Give the result its own wheel binding.
        self._result_text.bind("<MouseWheel>", self._on_result_wheel)
        self._result_text.pack(side="left", fill="x", expand=True)

        btn_row = tk.Frame(self._result_frame, bg=CP["bg"])
        btn_row.pack(fill="x", pady=(8, 0))

        replace = RoundedButton(
            btn_row, text="↩  Replace & Close", command=self._do_replace,
            fg=CP["bg"], fill=CP["accent"],
            font=("Segoe UI", 10, "bold"), padx=12, pady=6,
        )
        replace.pack(side="left")
        replace.bind("<Enter>", lambda _e: replace.configure(bg=CP["accent_hover"]))
        replace.bind("<Leave>", lambda _e: replace.configure(bg=CP["accent"]))

        insert_result_btn = RoundedButton(
            btn_row, text="↓ Insert Result", command=self._do_insert_result,
            fg=CP["text"], fill=CP["btn_bg"],
            font=("Segoe UI", 10, "bold"), padx=12, pady=6,
        )
        insert_result_btn.pack(side="left", padx=(8, 0))
        insert_result_btn.bind("<Enter>", lambda _e: insert_result_btn.configure(bg=CP["accent"], fg=CP["bg"]))
        insert_result_btn.bind("<Leave>", lambda _e: insert_result_btn.configure(bg=CP["btn_bg"], fg=CP["text"]))

        self.root.bind("<Escape>", lambda _e: self._do_hide())

    def _btn(self, parent: tk.Frame, text: str, command: Callable) -> "RoundedButton":
        from app_window import RoundedButton
        b = RoundedButton(
            parent, text=text, command=command,
            fg=CP["subtext"], fill=CP["btn_bg"],
            font=("Segoe UI", 10), padx=11, pady=5, radius=3,
        )
        b.bind("<Enter>", lambda _e: b.configure(fg=CP["accent"], bg=CP["btn_hover"]))
        b.bind("<Leave>", lambda _e: b.configure(fg=CP["subtext"], bg=CP["btn_bg"]))
        return b

    # ── Mode transitions ───────────────────────────────────────────────────────

    def _hide_all_frames(self) -> None:
        # The pill's frame is placed, not packed (see _content_size).
        self._status_frame.place_forget()
        for frame in (self._icon_frame, self._refine_frame):
            frame.pack_forget()

    def _enter_status_mode(self, text: str, recording: bool = False) -> None:
        self._use_window("pill")
        self._set_no_activate(True)
        self._status_entered = time.time()
        self._last_activity = time.time()
        self._last_shown = time.time()
        self._stop_waveform()
        self._hide_all_frames()

        with self._pill_edit():
            # Always remove timer/canvas/caption from pack order first so we control placement
            self._timer_lbl.pack_forget()
            self._wave_canvas.pack_forget()
            self._caption_wrap.pack_forget()

            if recording and self._captions_enabled:
                # Live-caption mode: waveform centred at the top (timer at the far
                # left), caption paragraph beneath — text starts at the left edge
                # and reads naturally rightward, wrapping down to CAPTION_MAX_LINES
                # before scrolling.
                self._draw_bars_initial()  # fresh bars every session
                self._timer_var.set("00:00.0")
                self._rec_start = time.time()
                self._timer_lbl.pack(side="left", before=self._status_label, padx=(0, 12))
                # expand=True centres the waveform in the remaining row width so it
                # sits top-middle above the caption text.
                self._wave_canvas.pack(side="left", before=self._status_label,
                                       expand=True)
                self._status_label.configure(text="")
                self._reset_caption_widget("Listening…")
                self._caption_wrap.pack(side="top", anchor="w", pady=(10, 0))
                # The waveform loop drives the timer and keeps _last_activity fresh.
                self._start_waveform()
            elif recording:
                # Correct order: timer | waveform | label
                self._draw_bars_initial()  # fresh bars every session
                self._timer_var.set("00:00.0")
                self._rec_start = time.time()
                self._timer_lbl.pack(side="left", before=self._status_label, padx=(0, 12))
                self._wave_canvas.pack(side="left", before=self._status_label, padx=(0, 12))
                self._status_label.configure(text=text)
                self._start_waveform()
            else:
                # Transcribing — just the label, no timer or waveform
                self._rec_start = None
                self._status_label.configure(text=text)

            # Placed at the corner, never packed: a packed frame is re-laid
            # out by Tk when Windows reports the pill's new size, and that
            # report is handled from the event loop outside real pixels, so
            # Windows rescaled the frame (the black patches). A placed frame
            # already sits where the report would put it, so nothing moves.
            self._status_frame.place(x=0, y=0)
            # Key-dismiss belongs to the post-insert badge ALONE. Starting a new
            # dictation while the previous badge is still up left its hook live,
            # so a space typed mid-recording hid the pill (and the badge's own
            # auto-dismiss timer bails on a mode change, so nothing ever took it
            # down). Every entry into status mode clears it. Now that ANY key
            # dismisses, an orphaned hook would kill the recording pill on the
            # first character the user typed — so this matters more, not less.
            self._unregister_key_dismiss()
            self._stop_foreground_watch()
            self._mode = "status"
            self.root.update_idletasks()  # force canvas render before animation
            # Always position on the monitor where the cursor is
            self._reposition(self._status_cx, self._status_cy)
            self._show_no_activate()

    def _reset_caption_widget(self, text: str = "") -> None:
        """Reset the caption bar to a single-line-tall paragraph block (start of a
        recording). Width stays fixed at CAPTION_MAX_CHARS — only height resets."""
        self._caption_lines = 0
        self._caption_user_scroll_ts = 0.0
        self._caption_scroll.pack_forget()
        self._caption_text.configure(state="normal")
        self._caption_text.delete("1.0", "end")
        self._caption_text.insert("1.0", text)
        self._caption_text.configure(
            state="disabled", width=CAPTION_MAX_CHARS, height=1
        )
        self._caption_box.sync()

    def _update_caption_widget(self, text: str) -> None:
        """Render live caption text into the bar: fixed paragraph width, growing
        vertically up to CAPTION_MAX_LINES, then scroll (tailing the latest words).
        Runs on the UI thread via root.after()."""
        if self._mode != "status" or not self._captions_enabled:
            return
        with self._pill_edit():
            self._update_caption_now(text)

    def _update_caption_now(self, text: str) -> None:
        try:
            self._caption_text.configure(state="normal")
            self._caption_text.delete("1.0", "end")
            self._caption_text.insert("1.0", text)

            # Width is fixed for the whole recording (set in
            # _reset_caption_widget) — the bar never widens or slides sideways
            # as text arrives, it wraps and grows downward. Re-applying the same
            # width here forced a Tk rewrap on every tick, right before the
            # displaylines measurement below had to wait for it.

            # Height: measure wrapped display lines at this width.
            lines = _display_lines(self._caption_text)
            shown = min(lines, CAPTION_MAX_LINES)
            self._caption_text.configure(height=shown, state="disabled")
            self._caption_box.sync()

            if lines > shown:
                self._caption_scroll.pack(side="right", fill="y")
            else:
                self._caption_scroll.pack_forget()

            # ALWAYS tail the newest words (not just once the bar is full):
            # if the height measurement ever lags a tick, the words being
            # spoken right now would otherwise sit clipped below the visible
            # area — the "text disappears at the end of the first line" bug.
            # Suspended briefly after a manual scroll so read-back doesn't snap.
            if time.time() - self._caption_user_scroll_ts > CAPTION_SCROLL_HOLDOFF:
                self._caption_text.see("end")

            # Keep the pill bottom-anchored as it grows: reposition only when the
            # visible line count changes (avoids per-tick geometry flicker).
            if shown != self._caption_lines:
                self._caption_lines = shown
                self._reposition(self._status_cx, self._status_cy)
        except Exception:
            pass

    def _on_result_wheel(self, event) -> str:
        """Wheel over the refine result — scroll a long result in place."""
        try:
            step = -(int(event.delta) // 120) * 2 or (-2 if event.delta > 0 else 2)
            self._result_text.yview_scroll(step, "units")
        except Exception:
            pass
        return "break"

    def _on_caption_wheel(self, event) -> str:
        """Wheel over the caption bar — scroll back through the transcript."""
        try:
            step = -(int(event.delta) // 120) * 2 or (-2 if event.delta > 0 else 2)
            self._caption_text.yview_scroll(step, "units")
            # Scrolling back pauses auto-tailing; returning to the bottom
            # (or wheeling past it) resumes it immediately.
            if self._caption_text.yview()[1] >= 0.999:
                self._caption_user_scroll_ts = 0.0
            else:
                self._caption_user_scroll_ts = time.time()
        except Exception:
            pass
        return "break"

    def _start_waveform(self) -> None:
        self._waveform_running = True
        # Small delay so canvas is fully rendered before first animation tick
        self.root.after(30, self._animate_waveform)

    def _stop_waveform(self) -> None:
        self._waveform_running = False
        self._mic_level = 0.0
        self._bars_active = False   # next run re-applies the active colour once
        # Reset bars to idle height
        if self._bar_ids:
            mid = CANVAS_H // 2
            for i, bid in enumerate(self._bar_ids):
                cx, half = _bar_geom(i, BAR_MIN_H)
                self._wave_canvas.coords(bid, cx, mid - half, cx, mid + half)
                self._wave_canvas.itemconfigure(bid, fill=CP["bar_idle"])

    def _enter_icon_mode(self) -> None:
        self._use_window("main")
        self._set_no_activate(True)
        self._stop_waveform()
        self._hide_all_frames()
        self._result_frame.pack_forget()
        self._ai_status.configure(text="")
        self._ai_status.pack_forget()
        self._icon_frame.pack()
        self._mode = "icon"
        self._icon_entered = time.time()
        self._last_shown = time.time()
        self._reposition(self._status_cx, self._status_cy)
        self._show_no_activate()
        if self._inserted_ok:
            if self._dismiss_on_key:
                self._register_key_dismiss()
            else:
                self._unregister_key_dismiss()
            # Only the success badge follows the user away: a "⚠ Not inserted"
            # badge is the one thing they DO need to read after switching apps.
            self._start_foreground_watch()
        else:
            self._unregister_key_dismiss()
            self._stop_foreground_watch()
        # Auto-dismiss the badge after a while so it never lingers on screen.
        # Stamp-guarded so a newer popup isn't killed by an old timer.
        self.root.after(
            int(ICON_AUTO_DISMISS_SECS * 1000),
            lambda s=self._icon_entered: self._auto_dismiss_icon(s),
        )

    def _auto_dismiss_icon(self, stamp: float) -> None:
        if self._mode == "icon":
            if self._icon_entered == stamp:
                self._do_hide()
            return          # a NEWER badge owns the hook — never unhook that one
        # The badge this timer belonged to is gone (a new dictation started, or
        # the panel opened). Its keyboard hook must go with it: returning here
        # without unhooking is what let a key-dismiss outlive its badge and
        # then hide a live recording.
        self._unregister_key_dismiss()

    def _touch_panel_activity(self) -> None:
        self._panel_activity = time.time()

    def _idle_check_panel(self, stamp: float) -> None:
        if self._mode != "refinement" or getattr(self, "_panel_entered", 0) != stamp:
            return
        active = self._ai_busy or self._mic_recording or self._upgrading
        if not active:
            try:
                px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
                rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
                active = (rx <= px <= rx + self.root.winfo_width()
                          and ry <= py <= ry + self.root.winfo_height())
            except tk.TclError:
                pass
        if active:
            self._touch_panel_activity()
        remaining = PANEL_IDLE_DISMISS_SECS - (time.time() - self._panel_activity)
        if remaining <= 0:
            self._do_hide()
            return
        self.root.after(int(max(0.5, remaining) * 1000),
                        lambda s=stamp: self._idle_check_panel(s))

    def _expand_to_panel(self) -> None:
        # Keys dismiss the small badge, but NOT the full refinement panel where
        # the user is typing into the Ask AI field. The foreground watch goes
        # too: the panel deliberately TAKES focus, so a watch keyed to the
        # target window would hide the panel the moment it opened.
        self._unregister_key_dismiss()
        self._stop_foreground_watch()
        self._use_window("main")
        # Remove WS_EX_NOACTIVATE so the Entry widget can receive keyboard focus
        self._set_no_activate(False)
        # Pack the panel FIRST (and refresh its status after), so a failure in
        # _refresh_insert_status can never strand a hidden-frames empty window.
        self._hide_all_frames()
        self._result_frame.pack_forget()
        self._refine_frame.pack()
        self._mode = "refinement"
        if self._refine_started_at is None:
            self._refine_started_at = time.monotonic()
        self._last_shown = time.time()
        # Idle auto-dismiss, stamp-guarded like the icon badge so a stale
        # timer from an earlier panel session can never kill a newer one.
        self._panel_entered = self._last_shown
        self._panel_activity = self._last_shown
        self.root.after(int(PANEL_IDLE_DISMISS_SECS * 1000),
                        lambda s=self._panel_entered: self._idle_check_panel(s))
        try:
            self._refresh_insert_status()
        except Exception as e:
            print(f"[Popup] _refresh_insert_status failed: {e}")

        # Show upgrade state if accurate model is still running or already done
        if self._upgrade_result:
            self._ai_status.configure(text="")
            self._show_ai_result(self._upgrade_result)
        elif self._upgrading:
            self._ai_status.configure(text="✦  Improving accuracy…")
            self._ai_status.pack(anchor="w")
        else:
            self._ai_status.configure(text="")

        self._reposition(self._status_cx, self._status_cy)
        # Activate the window so keyboard input works
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        # The panel has to stay on top for the same reason the pill does; the
        # re-assert never touches focus (SWP_NOACTIVATE), so the Ask box keeps it.
        self._assert_topmost()
        self._repaint_popup()
        self._start_keep_on_top()

    def _refresh_insert_status(self) -> None:
        if self._inserted_ok:
            self._inserted_badge.configure(
                text="  ✓ Inserted  ", fg=CP["bg"], bg=CP["accent"]
            )
        else:
            self._inserted_badge.configure(
                text="  ⚠ Not inserted  ", fg=CP["text"], bg=CP["error"]
            )

    def _register_key_dismiss(self) -> None:
        """In the post-insert icon badge, ANY key dismisses it once the grace
        window has passed — the user has moved on, so the badge should get out
        of the way without them having to aim at it.

        A single global `keyboard.hook` rather than one per key: the previous
        version bound Space and Enter only, which left the badge sitting there
        through any other kind of typing. suppress=False so every keystroke
        still reaches the app underneath — this only ever observes.

        NOT active in the refinement panel, where the user is typing into the
        Ask box and Enter submits it (_expand_to_panel unhooks first)."""
        try:
            import keyboard as kb

            self._unregister_key_dismiss()
            armed_at = self._icon_entered

            # Keys already down when the badge appeared. The hotkey that just
            # ended the dictation is still physically held at this moment, and
            # Windows auto-repeats a held key — every repeat arriving as another
            # key DOWN. Seeding from what is pressed RIGHT NOW is what lets the
            # grace window be a quarter of a second instead of well over a
            # second: a repeat of a key the user was already holding is not them
            # pressing anything, so it is ignored however long they hold it.
            held: set = set()
            try:
                held = {e.scan_code for e in kb._pressed_events.values()}
            except Exception:
                pass

            def _on_dismiss_key(event):
                etype = getattr(event, "event_type", None)
                code = getattr(event, "scan_code", None)
                if etype == "up":
                    held.discard(code)
                    return
                # Key DOWN only. The key-up of the hotkey that just stopped the
                # dictation arrives after the badge appears; dismissing on it
                # would make the badge vanish the instant it was drawn.
                if etype != "down":
                    return
                if code in held:
                    return          # auto-repeat of a key the user already held
                held.add(code)
                if not _key_dismisses_badge(getattr(event, "name", ""),
                                            _windows_key_held()):
                    return          # modifier, screenshot key or Win+ shortcut
                if time.time() - armed_at < KEY_DISMISS_GRACE_SECS:
                    return
                self._unregister_key_dismiss()
                if self.root:
                    self.root.after(0, self._do_hide)

            self._dismiss_hooks = [kb.hook(_on_dismiss_key, suppress=False)]
        except Exception:
            pass

    def _unregister_key_dismiss(self) -> None:
        if self._dismiss_hooks:
            try:
                import keyboard as kb

                for hook in self._dismiss_hooks:
                    if hook is not None:
                        kb.unhook(hook)
            except Exception:
                pass
            self._dismiss_hooks = []

    # ── Dismiss when the user switches away ─────────────────────────────────

    def _foreground_is_target(self) -> bool:
        """True while the foreground window is still the app the text was
        injected into (or the popup itself).

        Fails OPEN — a Win32 hiccup, or a target we never captured, must never
        yank the badge away while the user is still looking at it. winfo_id()
        is a CHILD window on Windows, so both handles go in the 'ours' set."""
        if not self._target_hwnd:
            return True
        try:
            fg = ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return True
        if not fg:
            return True
        if fg in (self._target_hwnd, self._popup_hwnd, self._top_hwnd()):
            return True
        # A screenshot tool in front is the user capturing the badge, not
        # leaving the app it belongs to.
        return _foreground_is_capture_tool()

    def _watch_target_foreground(self) -> None:
        """Hide the badge once the user clicks into a different app. The badge
        annotates one specific dictation in one specific window; carried over
        to whatever the user switched to, it is just clutter pinned on top."""
        self._fg_watch_tick = None
        if not self.root or self._mode != "icon":
            return
        if not self._foreground_is_target():
            self._do_hide()
            return
        try:
            self._fg_watch_tick = self.root.after(
                _FG_WATCH_INTERVAL_MS, self._watch_target_foreground)
        except tk.TclError:
            self._fg_watch_tick = None

    def _start_foreground_watch(self) -> None:
        """Armed only after the grace window: _show_no_activate hands focus back
        to the previous foreground window as the badge appears, so polling
        before that settles can read a transient value and self-dismiss."""
        self._stop_foreground_watch()
        if not self.root:
            return
        try:
            self._fg_watch_tick = self.root.after(
                int(KEY_DISMISS_GRACE_SECS * 1000), self._watch_target_foreground)
        except tk.TclError:
            self._fg_watch_tick = None

    def _stop_foreground_watch(self) -> None:
        if getattr(self, "_fg_watch_tick", None) is not None:
            try:
                self.root.after_cancel(self._fg_watch_tick)
            except Exception:
                pass
            self._fg_watch_tick = None

    def _do_hide(self) -> None:
        self._set_no_activate(True)
        self._stop_waveform()
        self._unregister_key_dismiss()
        self._stop_foreground_watch()
        self._stop_keep_on_top()
        self._mode = None
        self._ai_busy = False
        # Stop an in-flight voice-prompt recording — closing the panel must not
        # leave the mic stream open with a late transcription going nowhere.
        self._stop_voice_capture()
        self._upgrading = False
        self._upgrade_result = None
        self._ai_status.configure(text="")
        self._ai_status.pack_forget()
        self._result_frame.pack_forget()
        self._hide_all_frames()
        self.root.withdraw()
        for win, _hwnd in (getattr(self, "_windows", None) or {}).values():
            if win is not self.root:
                try:
                    win.withdraw()
                except tk.TclError:
                    pass

    def clear_upgrading(self, session: int = 0) -> None:
        """Upgrade finished with nothing better to offer — stop showing
        'Improving accuracy…' (it previously stayed forever in that case)."""
        if session and session != getattr(self, "_session_token", 0):
            return
        if self.root:
            def _clear():
                if session and session != getattr(self, "_session_token", 0):
                    return
                self._upgrading = False
                if self._mode == "refinement" and not self._ai_busy and self._current_result is None:
                    self._ai_status.configure(text="")
                    self._ai_status.pack_forget()
            self.root.after(0, _clear)

    def set_upgrade_result(self, accurate_text: str, session: int = 0) -> None:
        """Called from background thread when the accurate model finishes.
        session must match the token passed to show_cursor_icon — stale results
        from an earlier dictation are dropped."""
        if session and session != getattr(self, "_session_token", 0):
            print(f"[Popup] Discarding stale upgrade result (session {session})")
            return
        if self.root:
            self.root.after(0, lambda: self._on_upgrade_ready(accurate_text, session))

    def _on_upgrade_ready(self, accurate_text: str, session: int = 0) -> None:
        # Re-check on the UI thread — a new dictation may have arrived between
        # the after() call and now.
        if session and session != getattr(self, "_session_token", 0):
            return
        self._upgrading = False
        self._upgrade_result = accurate_text
        if self._mode == "refinement":
            if self._ai_busy:
                # A user-triggered refine is in flight — don't overwrite it.
                # The result is stored in _upgrade_result and shown when the
                # panel is next opened.
                return
            self._ai_status.configure(text="")
            self._ai_status.pack_forget()
            self._show_ai_result(accurate_text)
        # In icon mode: result is stored and shown automatically when user expands

    # ── Actions ────────────────────────────────────────────────────────────────

    def refine_stats(self) -> Optional[dict]:
        """Measurements for the refine that is being applied right now, or None
        if no refinement ran this session. Read by app.py at the moment the
        result is actually inserted/replaced — a refine the user looked at and
        discarded saved them nothing and must not be counted."""
        if self._refine_started_at is None:
            return None
        return {
            "elapsed_seconds": max(0.0, time.monotonic() - self._refine_started_at),
            "prompt_words": int(self._refine_prompt_words),
            "prompt_spoken": bool(self._refine_prompt_spoken),
            "result_chars": len(self._current_result or ""),
            "source_words": len((self._original_text or "").split()),
        }

    def _do_insert(self) -> None:
        """Manual insert — re-injects the original transcribed text at cursor."""
        if self._on_insert:
            cb = self._on_insert
            self._do_hide()
            threading.Thread(target=cb, daemon=True).start()

    def _do_insert_result(self) -> None:
        """Insert the AI result at the caret WITHOUT undoing anything — for when
        the original injection failed or the user wants the result appended.
        (Replace & Close is the undo-and-swap action.)"""
        if self._current_result and self._on_insert_result:
            result = self._current_result
            self._do_hide()
            threading.Thread(target=self._on_insert_result, args=(result,), daemon=True).start()
        # No fallback to _on_replace here: Replace UNDOES the original
        # injection first, which is the opposite of this button's contract
        # ("insert WITHOUT undoing anything").

    def _do_replace(self) -> None:
        """Undo original injection and insert AI result instead."""
        if self._current_result and self._on_replace:
            result = self._current_result
            self._do_hide()
            threading.Thread(
                target=self._on_replace, args=(result,), daemon=True
            ).start()

    # ── Voice prompt ────────────────────────────────────────────────────────────

    def _on_mic_click(self) -> None:
        if self._mic_recording:
            # User clicked stop — recording loop will exit on next iteration
            self._mic_recording = False
            return

        if not self._voice_prompt_fn:
            self._ai_status.configure(text="⚠  Voice prompt not configured")
            self._ai_status.pack(anchor="w")
            return

        self._mic_recording = True
        # Fresh dictation: forget the previous one's base/word bookkeeping. The
        # token invalidates any write still in flight from an earlier capture.
        self._voice_token += 1
        token = self._voice_token
        self._voice_base = ""
        self._voice_drop = 0
        self._voice_written_words = 0
        self._voice_last = None
        self._mic_btn.configure(text="⏹", fg=CP["bg"], bg=CP["accent"])
        self._ai_status.configure(text="🔴  Recording…  click ⏹ to stop")
        self._ai_status.pack(anchor="w")
        self._start_mic_pulse()

        def _run():
            if not self._voice_capture_start:
                self.root.after(0, lambda: self._ai_status.configure(
                    text="⚠  Voice capture not configured"))
                self.root.after(2000, self._finish_mic)
                return
            try:
                if not self._voice_capture_start():
                    self.root.after(0, lambda: self._ai_status.configure(
                        text="⚠  Mic unavailable"))
                    self.root.after(2000, self._finish_mic)
                    return
                start = time.time()
                last_preview = 0.0
                while self._mic_recording and (time.time() - start) < 120.0:
                    time.sleep(0.15)
                    if time.time() - last_preview >= 1.6:
                        last_preview = time.time()
                        snap, rate = self._voice_capture_read()
                        if snap is not None and len(snap) > rate // 2:
                            # non-blocking: skip if the model is busy from last preview
                            preview = self._voice_prompt_fn(snap, rate, blocking=False)
                            if preview and preview.strip():
                                p = preview.strip()
                                self.root.after(
                                    0,
                                    lambda p=p: self._apply_voice_text(p, token))
            except Exception as exc:
                err = str(exc)
                try:
                    self._voice_capture_stop()
                except Exception:
                    pass
                self.root.after(0, lambda: self._ai_status.configure(text=f"⚠  Mic error: {err}"))
                self.root.after(2000, self._finish_mic)
                return

            audio, rate = self._voice_capture_stop()
            if audio is None or len(audio) < rate // 4:
                self.root.after(0, lambda: self._ai_status.configure(text="⚠  No speech detected"))
                self.root.after(2000, self._finish_mic)
                return

            # Final blocking pass on the full buffer — gives the cleanest result
            self.root.after(0, lambda: self._ai_status.configure(text="✦  Finalising…"))
            try:
                text = self._voice_prompt_fn(audio, rate, blocking=True)
            except Exception as exc:
                err = str(exc)
                self.root.after(0, lambda: self._ai_status.configure(text=f"⚠  Transcription error: {err}"))
                self.root.after(2000, self._finish_mic)
                return

            if text and text.strip():
                t = text.strip()
                # The instruction was SPOKEN, not typed — doing this by hand in
                # a chat window would have meant typing it (see stats).
                self._refine_prompt_spoken = True
                self.root.after(0, lambda t=t: self._apply_voice_text(t, token))
            else:
                self.root.after(0, lambda: self._ai_status.configure(text="⚠  No speech detected"))
                self.root.after(2000, self._finish_mic)
                return

            self.root.after(0, self._finish_mic)

        threading.Thread(target=_run, daemon=True).start()

    def _start_mic_pulse(self) -> None:
        self._mic_pulse_on = True
        self._mic_pulse_tick()

    def _mic_pulse_tick(self) -> None:
        if not self._mic_recording:
            return
        if self._mic_pulse_on:
            self._mic_btn.configure(fg=CP["bg"], bg=CP["accent"])
        else:
            self._mic_btn.configure(fg=CP["accent"], bg=CP["mic_bg"])
        self._mic_pulse_on = not self._mic_pulse_on
        self.root.after(500, self._mic_pulse_tick)

    def _apply_voice_text(self, text: str, token: int = 0) -> None:
        """Write a voice-prompt transcription into the Ask box WITHOUT undoing
        the user's own edits.

        The mic re-transcribes the whole buffer on every ~1.6s preview, so
        writing that result straight in (what the raw _set_ask_entry call did)
        restored every word the user had just deleted the moment they spoke
        again. Anything in the box that we did not put there becomes the base
        the dictation appends to, and the words spoken before that edit are
        dropped — so a mid-sentence delete stays deleted and hand-typed text
        survives. A stale token means the capture was cancelled (instruction
        submitted, panel closed): the write is dropped rather than refilling a
        box the user has already sent."""
        if token and token != self._voice_token:
            return
        live = "" if self._ask_showing_placeholder else \
            self._ask_entry.get("1.0", "end-1c")
        if self._voice_last is None or live != self._voice_last:
            # The field changed under us — a hand edit, or the first write of
            # this capture. Adopt what is there now; everything dictated before
            # that point belongs to the text the user has already dealt with.
            self._voice_base = live.strip()
            self._voice_drop = self._voice_written_words
        words = text.split()
        # Word-indexed, never a byte prefix: each pass re-transcribes the same
        # audio and may re-word or re-punctuate what it produced last time.
        spoken = " ".join(words[self._voice_drop:])
        base = self._voice_base
        out = f"{base} {spoken}".strip() if (base and spoken) else (spoken or base)
        self._voice_written_words = len(words)
        self._voice_last = out
        self._set_ask_entry(out)

    def _set_ask_entry(self, text: str) -> None:
        self._ask_entry.delete("1.0", "end")
        self._ask_entry.insert("1.0", text)
        self._ask_entry.configure(fg=CP["text"])
        self._ask_showing_placeholder = False
        self._autosize_ask()

    def _autosize_ask(self) -> None:
        """Grow/shrink the Ask box to fit its wrapped text (1..ASK_MAX_LINES lines).

        Uses displaylines so word-wrapped text counts each visual row, not just
        newline-delimited lines. Repositions the panel when the height changes so
        it stays anchored to the bottom of the screen as it grows upward.
        """
        n = min(_display_lines(self._ask_entry), ASK_MAX_LINES)
        if n == self._ask_lines:
            return
        self._ask_lines = n
        self._ask_entry.configure(height=n)
        self._ask_box.sync()
        # Panel is anchored bottom-centre (y = bottom - height - 60), so a taller
        # box must be re-placed or it would grow down into the taskbar.
        if self._mode == "refinement":
            try:
                self._reposition(self._status_cx, self._status_cy)
            except Exception:
                pass

    def _finish_mic(self) -> None:
        self._mic_recording = False
        self._mic_btn.configure(text="🎙", fg=CP["subtext"], bg=CP["mic_bg"])
        self._ai_status.configure(text="")
        self._ai_status.pack_forget()

    def _reset_mic_btn(self) -> None:
        self._mic_recording = False
        self._mic_btn.configure(text="🎙", fg=CP["subtext"], bg=CP["mic_bg"])

    def _stop_voice_capture(self) -> None:
        """Turn the voice-prompt mic off and disown anything still in flight.

        Submitting the instruction (Enter or ✦ Ask) ends the dictation: a mic
        left listening would keep rewriting the Ask box after the instruction
        had already gone to the model. Bumping the token drops the capture's
        final transcription too, so a sent box never refills itself."""
        if not self._mic_recording:
            return
        self._mic_recording = False   # the capture loop exits on its next pass
        self._voice_token += 1
        self._voice_last = None
        self._reset_mic_btn()

    # ── AI refinement ──────────────────────────────────────────────────────────

    def _run_ai(self, mode: str) -> None:
        if not (self._original_text or "").strip():
            # No source text (e.g. the selection capture came back empty). Never
            # call the model with nothing — it replies "please provide the text".
            self._ai_status.configure(text="⚠  No text to refine. Select text, then press your refine hotkey")
            self._ai_status.pack(anchor="w")
            return
        if not self._ai_refiner or not self._ai_refiner.is_available:
            self._ai_status.configure(text="⚠  Set anthropic_api_key in config to enable AI")
            self._ai_status.pack(anchor="w")
            return
        if self._ai_busy:
            return
        if self._refine_started_at is None:
            self._refine_started_at = time.monotonic()
        self._ai_busy = True
        self._ai_status.configure(text=f"✦  Refining ({mode})…")
        self._ai_status.pack(anchor="w")
        self._result_frame.pack_forget()
        text = self._original_text

        token = self._session_token

        def _worker():
            result = self._ai_refiner.refine(text, mode, sender_name=self._sender_name)
            self.root.after(0, self._show_ai_result, result, token)

        threading.Thread(target=_worker, daemon=True).start()

    def _run_ai_custom(self) -> None:
        """Run AI refinement with a custom instruction typed by the user."""
        instruction = "" if self._ask_showing_placeholder else self._ask_entry.get("1.0", "end-1c").strip()
        if not instruction:
            self._ai_status.configure(text="⚠  Type an instruction first")
            self._ai_status.pack(anchor="w")
            return
        if not (self._original_text or "").strip():
            # No source text captured — refining nothing makes the model reply
            # "please provide the text". Tell the user to select text instead.
            self._ai_status.configure(text="⚠  No text to refine. Select text, then press your refine hotkey")
            self._ai_status.pack(anchor="w")
            return
        if not self._ai_refiner or not self._ai_refiner.is_available:
            self._ai_status.configure(text="⚠  Set anthropic_api_key in config to enable AI")
            self._ai_status.pack(anchor="w")
            return
        if self._ai_busy:
            return
        # Sending the instruction ends the dictation — the mic must not keep
        # listening (and keep rewriting the box) after the ask has gone.
        self._stop_voice_capture()
        if self._refine_started_at is None:
            self._refine_started_at = time.monotonic()
        self._refine_prompt_words = len(instruction.split())
        self._ai_busy = True
        self._ai_status.configure(text=f"✦  Asking AI…")
        self._ai_status.pack(anchor="w")
        self._result_frame.pack_forget()
        text = self._original_text
        custom_prompt = (
            f"{instruction}. "
            "Return only the rewritten text, nothing else."
        )

        token = self._session_token

        def _worker():
            result = self._ai_refiner.refine(text, custom_prompt=custom_prompt)
            self.root.after(0, self._show_ai_result, result, token)

        threading.Thread(target=_worker, daemon=True).start()

    def _show_ai_result(self, text: str, session: int = 0) -> None:
        self._ai_busy = False
        # Restart the idle countdown so the user gets the full window to read
        # the result even if the AI call took a while.
        self._touch_panel_activity()
        if self._mode is None:
            # Popup was closed while the worker was running; discard silently.
            return
        if session and session != self._session_token:
            # Result belongs to an EARLIER dictation — a new popup session
            # started while the worker ran. Displaying it would let "Replace"
            # inject the old dictation's text over the new one.
            return
        self._current_result = text
        self._ai_status.configure(text="")
        self._ai_status.pack_forget()  # hide spinner row — no blank gap

        # Write full text into the scrollable widget
        self._result_text.configure(state="normal")
        self._result_text.delete("1.0", "end")
        self._result_text.insert("1.0", text)
        self._result_text.configure(state="disabled")

        # Auto-size height: count DISPLAY lines (wrapped), not logical newlines —
        # a single-paragraph result (the normal case) wraps to many display
        # lines but has line_count == 1, which clamped the box to 2 rows.
        line_count = _display_lines(self._result_text)
        self._result_text.configure(height=min(max(line_count, 2), 8))

        # Show scrollbar only when text exceeds visible area
        if line_count > 8:
            self._result_scrollbar.pack(side="right", fill="y")
        else:
            self._result_scrollbar.pack_forget()

        self._result_frame.pack(fill="x")
        self._reposition(self._status_cx, self._status_cy)

    # ── Positioning ────────────────────────────────────────────────────────────

    @staticmethod
    def _get_cursor_pos() -> tuple[int, int]:
        try:
            pt = _POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return pt.x, pt.y
        except Exception:
            return 0, 0

    def _get_monitor_workarea(
        self, x: int = 0, y: int = 0
    ) -> tuple[int, int, int, int]:
        """Work area of the monitor the popup belongs on, in REAL pixels (the
        space Tk places this borderless window in; see OverlayMonitor). The
        monitor is picked in the app's scaled space, where the anchor lives."""
        self._last_overlay = None
        try:
            MONITOR_DEFAULTTONEAREST = 2
            # PRIVATE typed instance — never the shared ctypes.windll.user32,
            # whose GetMonitorInfoW app_window used to pin to its own struct
            # class, making this exact call raise and fall back to the primary
            # monitor on every placement (the wrong-screen saga's root cause).
            u32 = _monitor_user32()
            # Prefer the explicit anchor coords the app computed — the centre
            # of the window being dictated into, with the cursor only as its
            # fallback (see app._popup_anchor). Fall back to the target hwnd
            # only when no anchor coords were given.
            if x or y:
                pt = _POINT()
                pt.x, pt.y = x, y
                hmon = u32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
            elif self._target_hwnd:
                hmon = u32.MonitorFromWindow(
                    self._target_hwnd, MONITOR_DEFAULTTONEAREST
                )
            else:
                # Last resort: monitor containing the current cursor
                pt = _POINT()
                u32.GetCursorPos(ctypes.byref(pt))
                hmon = u32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
            mon = _overlay_monitor_from_handle(hmon)
            if mon is not None:
                self._last_overlay = mon
                self._last_monitor_bottom = mon.real[3]
                return mon.work
        except Exception:
            pass
        self._last_monitor_bottom = None
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _monitor_bottom(self, x: int = 0, y: int = 0) -> int:
        """Physical bottom edge of the monitor the popup is being placed on —
        the FULL rect, taskbar included, not the work area.

        Only used for a deliberately negative popup_offset (the user pressing ▾
        past the baseline to sit the pill in the taskbar strip). Read from the
        same GetMonitorInfoW call the work-area lookup already makes, so it
        cannot disagree with it about which monitor is in play. Raises when
        unavailable, and the caller falls back to the work area — being clamped
        a little high is a lot better than a pill placed off-screen."""
        bottom = getattr(self, "_last_monitor_bottom", None)
        if bottom is None:
            self._get_monitor_workarea(x, y)
            bottom = getattr(self, "_last_monitor_bottom", None)
        if bottom is None:
            raise RuntimeError("monitor rect unavailable")
        return bottom

    def _dpi_scale(self) -> tuple[float, float]:
        """
        Scale factors (sx, sy) from Win32 physical pixels → tkinter logical pixels.

        Win32 GetMonitorInfoW / GetCursorPos return physical pixels for DPI-aware
        processes and logical pixels for non-DPI-aware ones.  tkinter geometry()
        always uses logical pixels.  Comparing SM_CXSCREEN (Win32 physical) with
        winfo_screenwidth() (tkinter logical) gives the scale factor; if the
        process is non-DPI-aware the two match and (1.0, 1.0) is returned.
        """
        try:
            phys_w = ctypes.windll.user32.GetSystemMetrics(0)  # SM_CXSCREEN physical
            phys_h = ctypes.windll.user32.GetSystemMetrics(1)  # SM_CYSCREEN physical
            tk_w   = self.root.winfo_screenwidth()
            tk_h   = self.root.winfo_screenheight()
            if phys_w > 0 and phys_h > 0:
                return tk_w / phys_w, tk_h / phys_h
        except Exception:
            pass
        return 1.0, 1.0

    def _is_real_pixel_window(self) -> bool:
        """True when the popup is the per-monitor DPI window initialize()
        creates: placed and sized in real pixels, never rescaled by Windows.
        False on Windows builds without per-thread DPI contexts (and for test
        doubles), where _reposition falls back to measuring where it landed."""
        try:
            top = (ctypes.windll.user32.GetAncestor(self._popup_hwnd, 2)
                   or self._popup_hwnd)
            if not top:
                return False
            u32 = _monitor_user32()
            ctx = u32.GetWindowDpiAwarenessContext(top)
            return bool(ctx) and u32.GetAwarenessFromDpiAwarenessContext(ctx) == 2
        except Exception:
            return False

    def _place_xy(self, w: int, h: int, bounds: tuple, cx: int, cy: int,
                  near_cursor: bool, sx: float, sy: float) -> tuple:
        """Top-left for a w x h popup inside `bounds` (left, top, right,
        bottom of the work area) by the placement settings."""
        left, top, right, bottom = bounds
        mon = getattr(self, "_last_overlay", None)
        if near_cursor and cx > 0 and cy > 0:
            gap = 28
            # The anchor is in the app's scaled space; the window goes in
            # real pixels.
            rcx, rcy = mon.real_point(cx, cy) if mon is not None else (cx, cy)
            x   = round(rcx * sx) - w // 2
            y_b = round(rcy * sy) + gap
            y   = y_b if y_b + h <= bottom else round(rcy * sy) - h - gap
        else:
            # Fixed placement on whichever monitor the cursor is on. Horizontal
            # placement follows popup_align (◂ ▸ arrows); vertical follows the
            # popup_height preference, so it can sit out of the way of a chatbot's
            # input box (low, default) or up above the chat window (high).
            if self._popup_align == "left":
                x = left + 8
            elif self._popup_align == "right":
                x = right - w - 8
            else:
                x = left + (right - left - w) // 2
            if self._popup_height == "high":
                y = top + 90
            elif self._popup_height == "medium":
                y = top + (bottom - top - h) // 2
            else:  # "low" (default) — hug the taskbar, clear of chat inputs
                y = bottom - h - 6
            # Fine-nudge saved from the pill's ▴▾ arrows — lifts the popup clear
            # of the taskbar (a couple mm by default) and sticks wherever the
            # user parks it. The first-order guard below re-clamps into the
            # work-area, so a large nudge can never push it off the top edge.
            y -= self._popup_offset

        # First-order guard: keep the whole popup inside the work-area, so a
        # stale width or an odd monitor origin can never push the fixed popup
        # off an edge (the cut-off refine panel).
        #
        # A NEGATIVE popup_offset is the user deliberately pushing the pill down
        # into the taskbar strip with the ▾ arrow, so the bottom clamp for that
        # case is the monitor's full rect, not its work area — clamping to the
        # work area would silently undo every press past 0 and the arrow would
        # look broken. The screen edge is still a hard stop.
        bottom_limit = bottom
        if not near_cursor and self._popup_offset < 0:
            try:
                mb_p = self._monitor_bottom(cx, cy)
                bottom_limit = max(bottom, round(mb_p * sy))
            except Exception:
                bottom_limit = bottom
        x = max(left, min(x, right - w))
        y = max(top, min(y, bottom_limit - h))
        return x, y

    def _reposition(self, cx: int = 0, cy: int = 0, near_cursor: bool = False) -> None:
        # The pill's layout runs in real pixels (see _pill_edit; a no-op for
        # the badge and refine panel window), but the placement maths reads
        # monitors and the cursor in the app's own context, so that part is
        # put back in it.
        with self._pill_edit():
            app_ctx = (getattr(self, "_pill_app_ctx", None)
                       if getattr(self, "_pill_depth", 0) else None)
            with _ThreadDpi(app_ctx):
                self._reposition_now(cx, cy, near_cursor)

    def _reposition_now(self, cx: int, cy: int, near_cursor: bool) -> None:
        real_px = self._is_real_pixel_window()
        if real_px:
            # Every geometry flush for this window runs in real pixels, or Tk
            # reapplies its last position in scaled numbers.
            with _RealPixels():
                self.root.update_idletasks()
        else:
            self.root.update_idletasks()
        w, h = self._content_size()

        # Pick the monitor (multi-monitor aware — follows the anchor) and take
        # its work area in REAL pixels, the space this borderless window lives
        # in (see OverlayMonitor). Keep the raw bounds too: the second-order
        # guard below re-checks the real landing spot against them.
        try:
            left_p, top_p, right_p, bottom_p = self._get_monitor_workarea(cx, cy)
            sx, sy = self._dpi_scale()
            left   = round(left_p   * sx)
            top    = round(top_p    * sy)
            right  = round(right_p  * sx)
            bottom = round(bottom_p * sy)
        except Exception:
            left_p, top_p = 0, 0
            right_p  = self.root.winfo_screenwidth()
            bottom_p = self.root.winfo_screenheight()
            left, top, sx, sy = 0, 0, 1.0, 1.0
            right, bottom = right_p, bottom_p

        mon = getattr(self, "_last_overlay", None)
        x, y = self._place_xy(w, h, (left, top, right, bottom), cx, cy,
                              near_cursor, sx, sy)

        pos_log(f"place mode={self._mode} in=({cx},{cy}) "
                f"hwnd={self._target_hwnd:#x} "
                f"wa=({left_p},{top_p},{right_p},{bottom_p}) xy=({x},{y}) "
                f"wh=({w},{h}) real_px={real_px} "
                f"mon={(mon.scaled, mon.real) if mon is not None else None}")

        # Size counts as a move: the caption bar grows downward while the pill is
        # bottom-anchored, so a taller pill at the same y is still a blit.
        moved = f"{w}x{h}+{x}+{y}" != self._last_geometry
        self._last_geometry = f"{w}x{h}+{x}+{y}"
        self._repos_args = (cx, cy, near_cursor)
        if real_px:
            # Size pinned along with the position. Left to itself Tk resizes
            # the window from its idle loop whenever the content changes, and
            # that resize reapplies the position in scaled numbers: on a 150%
            # monitor the pill jumped half a screen away. _watch_pinned_size
            # re-places it instead when the content changes size.
            with _RealPixels():
                self.root.geometry(f"{w}x{h}+{x}+{y}")
                # Flush BEFORE the caller deiconifies it, so it never maps at
                # the old/0,0 spot for a frame (top-left black-box flash).
                self.root.update_idletasks()
            self._pinned_size = (w, h)
            self._pinned_root = self.root
            self._start_size_watch()
        else:
            self.root.geometry(f"+{x}+{y}")
            # Flush the position to the window BEFORE the caller deiconifies it, so it
            # never maps at the old/0,0 spot for a frame (top-left black-box flash).
            self.root.update_idletasks()

        # Second-order guard: measure where the window REALLY landed and, if it
        # spills past the target monitor's work area, nudge it back by the
        # measured overflow. Empirical, so it corrects any coordinate-space
        # mismatch without having to model the DPI topology.
        #
        # It also covers a window Windows DPI-scales after all (the fallback
        # when initialize() could not make it a per-monitor DPI window): Tk's
        # numbers are then scaled ones and its size is scaled too, so the
        # target is recomputed from the measured size and converted back.
        try:
            GA_ROOT = 2
            u32 = ctypes.windll.user32
            top_hwnd = u32.GetAncestor(self._popup_hwnd, GA_ROOT) or self._popup_hwnd
            pr = real_window_rect(top_hwnd)
            scaled_tk = False
            if (not real_px and pr is not None and mon is not None
                    and (pr[0], pr[1]) != (x, y)):
                ex, ey = mon.real_point(x, y)
                if abs(pr[0] - ex) <= 2 and abs(pr[1] - ey) <= 2:
                    scaled_tk = True
                    rx, ry = self._place_xy(pr[2] - pr[0], pr[3] - pr[1],
                                            (left_p, top_p, right_p, bottom_p),
                                            cx, cy, near_cursor, 1.0, 1.0)
                    tx, ty = mon.scaled_point(rx, ry)
                    self.root.geometry(f"+{tx}+{ty}")
                    self.root.update_idletasks()
                    pos_log(f"place scaled-window mode={self._mode} "
                            f"asked=({x},{y}) landed=({pr[0]},{pr[1]}) "
                            f"re-placed=({tx},{ty})")
                    moved = True
                    self._last_geometry = ""
                    pr = real_window_rect(top_hwnd)
            if pr is not None:
                pw, ph = pr[2] - pr[0], pr[3] - pr[1]
                nx = max(left_p, min(pr[0], right_p - pw))
                ny = max(top_p, min(pr[1], bottom_p - ph))
                ddx, ddy = nx - pr[0], ny - pr[1]
                if ddx or ddy:
                    if real_px:
                        with _RealPixels():
                            self.root.geometry(f"{w}x{h}+{x + ddx}+{y + ddy}")
                            self.root.update_idletasks()
                    else:
                        if scaled_tk:
                            gx, gy = mon.scaled_point(nx, ny)
                        else:
                            gx, gy = x + round(ddx * sx), y + round(ddy * sy)
                        self.root.geometry(f"+{gx}+{gy}")
                        self.root.update_idletasks()
                    self._log_pos_anomaly(near_cursor, w, h, x, y,
                                          (left_p, top_p, right_p, bottom_p),
                                          (pr[0], pr[1]), (ddx, ddy))
                    moved = True
                    self._last_geometry = ""
        except Exception:
            pass

        # Moving or resizing a MAPPED overrideredirect window lets Windows blit
        # the old pixels into the new spot, which is the ghosted/half-drawn pill.
        # RDW_UPDATENOW only validates Tk's update region — Tk turns WM_PAINT into
        # a queued Expose and paints on a later mainloop spin — so the after(0)
        # twin is the one that actually drains the queue.
        if moved:
            try:
                mapped = bool(self.root.winfo_ismapped())
            except Exception:
                mapped = False
            if mapped:
                self._repaint_popup()
                try:
                    self.root.after(0, self._repaint_popup)
                except tk.TclError:
                    pass

    def _start_size_watch(self) -> None:
        if getattr(self, "_size_watch_on", False):
            return
        self._size_watch_on = True
        try:
            self.root.after(_SIZE_WATCH_MS, self._watch_pinned_size)
        except tk.TclError:
            self._size_watch_on = False

    def _watch_pinned_size(self) -> None:
        """The popup's size is pinned (see _reposition), so content that grows
        or shrinks without a reposition (a status label changing, a result
        arriving) would be clipped or padded. Re-place it when the content's
        size drifts from the pinned size. Runs while the popup is up."""
        try:
            if (not self.root or not self._mode
                    or getattr(self, "_pinned_root", None) is not self.root):
                self._size_watch_on = False
                return
            want = self._content_size()
            if want != getattr(self, "_pinned_size", want):
                cx, cy, near = getattr(self, "_repos_args", (0, 0, False))
                self._reposition(cx, cy, near_cursor=near)
            self._heal_pill_layout()
            self.root.after(_SIZE_WATCH_MS, self._watch_pinned_size)
        except tk.TclError:
            self._size_watch_on = False

    def _log_pos_anomaly(self, near_cursor, w, h, x, y, wa_phys, landed, delta):
        """Record only the anomalous placements — the ones the physical guard had
        to nudge back on-screen. Rare by construction, so this stays silent on
        healthy single-DPI setups and pinpoints a real coordinate mismatch (send
        me %TEMP%\\ftc_pos_debug.log if a popup ever still lands wrong)."""
        try:
            import os as _os, time as _t
            _dbg = _os.path.join(_os.environ.get("TEMP", "."), "ftc_pos_debug.log")
            with open(_dbg, "a", encoding="utf-8") as _f:
                _f.write(f"{_t.strftime('%H:%M:%S')} CORRECTED mode={self._mode} "
                         f"near={near_cursor} wh=({w},{h}) asked=({x},{y}) "
                         f"wa_phys={wa_phys} landed={landed} nudge={delta} "
                         f"screen=({self.root.winfo_screenwidth()},"
                         f"{self.root.winfo_screenheight()})\n")
        except Exception:
            pass
