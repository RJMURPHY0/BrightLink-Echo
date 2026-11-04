"""A still picture of a window's client area, held over it while it repaints.

Tk child windows keep no pixels of their own: when a page is swapped, every
widget redraws from scratch over several passes of the event loop, and Windows
shows each pass as it lands (the half-drawn dashboard at sign-in). The
top-level window, on the other hand, is composited off screen by DWM, so if
something covers it while Tk repaints, removing the cover shows the finished
page in one frame.

The cover is a layered, click-through, never-activating popup owned by the
window, filled once with a copy of the client area (BitBlt from the window's
own DC, PrintWindow if that fails) via
UpdateLayeredWindow (so it never paints itself and cannot flash white), and
placed directly above the window in the z-order (so it never jumps in front of
another app that overlaps the window). Every failure returns None and the
caller swaps without a cover, which is exactly the old behaviour.

All Win32 calls go through PRIVATE WinDLL instances: argtypes set on the shared
ctypes.windll objects leak into every other module (see popup.py).
"""

import ctypes
from ctypes import wintypes as W
from typing import Optional

_WS_POPUP = 0x80000000
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_GW_HWNDPREV = 3
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SW_SHOWNOACTIVATE = 4
_PW_CLIENTONLY = 0x1
_PW_RENDERFULLCONTENT = 0x2
_ULW_ALPHA = 0x2
_SRCCOPY = 0x00CC0020

_api = None


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", W.WORD),
                ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", W.DWORD),
                ("biClrImportant", W.DWORD)]


class _ULWInfo(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("hdcDst", W.HDC),
                ("pptDst", ctypes.POINTER(W.POINT)),
                ("psize", ctypes.POINTER(W.SIZE)), ("hdcSrc", W.HDC),
                ("pptSrc", ctypes.POINTER(W.POINT)), ("crKey", W.COLORREF),
                ("pblend", ctypes.c_void_p), ("dwFlags", W.DWORD),
                ("prcDirty", ctypes.POINTER(W.RECT))]


class _Blend(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


def _opaque_blend() -> "_Blend":
    """AC_SRC_OVER at constant alpha 255 with NO per-pixel alpha
    (AlphaFormat 0): the picture replaces what is under it, whatever its
    alpha bytes hold. Every UpdateLayeredWindow on the cover uses this one
    mode (see SnapshotCover._refresh for the bug a second mode caused)."""
    return _Blend(0, 0, 255, 0)


def _load():
    global _api
    if _api is not None:
        return _api
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    g32 = ctypes.WinDLL("gdi32")
    u32.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
    u32.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
    u32.GetDC.restype = W.HDC
    u32.GetDC.argtypes = [W.HWND]
    u32.ReleaseDC.argtypes = [W.HWND, W.HDC]
    u32.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
    u32.CreateWindowExW.restype = W.HWND
    u32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, W.HWND, W.HMENU,
                                    W.HINSTANCE, W.LPVOID]
    u32.UpdateLayeredWindow.argtypes = [W.HWND, W.HDC, ctypes.POINTER(W.POINT),
                                        ctypes.POINTER(W.SIZE), W.HDC,
                                        ctypes.POINTER(W.POINT), W.COLORREF,
                                        ctypes.POINTER(_Blend), W.DWORD]
    u32.UpdateLayeredWindowIndirect.argtypes = [W.HWND,
                                                ctypes.POINTER(_ULWInfo)]
    u32.GetWindow.restype = W.HWND
    u32.GetWindow.argtypes = [W.HWND, W.UINT]
    u32.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, W.UINT]
    u32.DestroyWindow.argtypes = [W.HWND]
    u32.ShowWindow.argtypes = [W.HWND, ctypes.c_int]
    u32.IsWindowVisible.argtypes = [W.HWND]
    g32.CreateCompatibleDC.restype = W.HDC
    g32.CreateCompatibleDC.argtypes = [W.HDC]
    g32.CreateDIBSection.restype = W.HBITMAP
    g32.CreateDIBSection.argtypes = [W.HDC, ctypes.c_void_p, W.UINT,
                                     ctypes.POINTER(ctypes.c_void_p),
                                     W.HANDLE, W.DWORD]
    g32.SelectObject.restype = W.HGDIOBJ
    g32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
    g32.DeleteObject.argtypes = [W.HGDIOBJ]
    g32.DeleteDC.argtypes = [W.HDC]
    g32.BitBlt.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, W.HDC, ctypes.c_int, ctypes.c_int,
                           W.DWORD]
    _api = (u32, g32)
    return _api


_dwm = None


def _dwm_flush() -> None:
    """Block until DWM's next present (at most one frame). Best effort: on
    failure the change just runs, as it did before."""
    global _dwm
    try:
        if _dwm is None:
            _dwm = ctypes.WinDLL("dwmapi")
        _dwm.DwmFlush()
    except Exception as exc:
        print(f"[SnapshotCover] DwmFlush failed (non-fatal): {exc}")


def _dib(g32, dc, w: int, h: int):
    bih = _BIH(ctypes.sizeof(_BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bmp = g32.CreateDIBSection(dc, ctypes.byref(bih), 0, ctypes.byref(bits),
                               None, 0)
    return bmp, bits


def _client_pixels(top_hwnd: int):
    """((x, y, w, h), BGRA bytes) of the window's client area as DWM holds
    it (on screen or not), or None. Blank (all zero) counts as None."""
    u32, g32 = _load()
    rc = W.RECT()
    if not u32.GetClientRect(top_hwnd, ctypes.byref(rc)):
        return None
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w <= 0 or h <= 0:
        return None
    origin = W.POINT(0, 0)
    u32.ClientToScreen(top_hwnd, ctypes.byref(origin))
    g32.GdiFlush()      # this thread's batched Tk drawing lands first
    win_dc = u32.GetDC(top_hwnd)
    mem_dc = g32.CreateCompatibleDC(win_dc)
    bmp, bits = _dib(g32, mem_dc, w, h)
    old = g32.SelectObject(mem_dc, bmp) if bmp else None
    try:
        if not bmp or not bits.value:
            return None
        # BitBlt from the window's own DC reads the surface DWM composites
        # from, so a cover or another app over the window is never in it.
        # ~5ms against PrintWindow's 35-100ms (measured 2026-10-28), and the
        # cover's watch reads it every _COVER_POLL_MS on the UI thread: at
        # PrintWindow's cost every page change waited ~300ms on the reads
        # alone. PrintWindow stays as the fallback.
        pixels = None
        if win_dc and g32.BitBlt(mem_dc, 0, 0, w, h, win_dc, 0, 0, _SRCCOPY):
            pixels = ctypes.string_at(bits.value, w * h * 4)
        if not pixels or not pixels.strip(b"\x00"):
            if not u32.PrintWindow(top_hwnd, mem_dc,
                                   _PW_CLIENTONLY | _PW_RENDERFULLCONTENT):
                return None
            pixels = ctypes.string_at(bits.value, w * h * 4)
        if not pixels.strip(b"\x00"):
            return None
        return (origin.x, origin.y, w, h), pixels
    finally:
        if old:
            g32.SelectObject(mem_dc, old)
        if bmp:
            g32.DeleteObject(bmp)
        g32.DeleteDC(mem_dc)
        if win_dc:
            u32.ReleaseDC(top_hwnd, win_dc)


def _push(hwnd: int, shot) -> bool:
    """Put `shot` ((x, y, w, h), BGRA bytes from _client_pixels) on the
    layered window `hwnd`, opaque, at that place and size."""
    u32, g32 = _load()
    (x, y, w, h), pixels = shot
    pixels = bytearray(pixels)
    pixels[3::4] = bytes([255]) * (w * h)        # opaque
    screen_dc = u32.GetDC(None)
    mem_dc = g32.CreateCompatibleDC(screen_dc)
    bmp, bits = _dib(g32, mem_dc, w, h)
    old = g32.SelectObject(mem_dc, bmp) if bmp else None
    try:
        if not bmp or not bits.value:
            return False
        ctypes.memmove(bits.value, bytes(pixels), len(pixels))
        blend = _opaque_blend()       # the same mode refresh() shows in
        return bool(u32.UpdateLayeredWindow(
            hwnd, screen_dc, ctypes.byref(W.POINT(x, y)),
            ctypes.byref(W.SIZE(w, h)), mem_dc,
            ctypes.byref(W.POINT(0, 0)), 0, ctypes.byref(blend), _ULW_ALPHA))
    finally:
        if old:
            g32.SelectObject(mem_dc, old)
        if bmp:
            g32.DeleteObject(bmp)
        g32.DeleteDC(mem_dc)
        u32.ReleaseDC(None, screen_dc)


def window_fingerprint(top_hwnd: int) -> Optional[int]:
    """A hash of what the window's client area currently shows (None if it
    cannot be read). Two equal readings a moment apart mean Tk has finished
    drawing."""
    try:
        shot = _client_pixels(top_hwnd)
    except Exception:
        return None
    return None if shot is None else hash(shot[1])


class SnapshotCover:
    def __init__(self, hwnd: int):
        self._hwnd = hwnd
        self._buf = None    # (mem_dc, bmp, old, bits, w, h) kept for refresh()

    @classmethod
    def over(cls, top_hwnd: int) -> Optional["SnapshotCover"]:
        """Cover `top_hwnd`'s client area with a picture of itself, or None."""
        if not top_hwnd:
            return None
        try:
            return cls._over(top_hwnd)
        except Exception as exc:
            print(f"[SnapshotCover] Not covered (non-fatal): {exc}")
            return None

    @classmethod
    def _over(cls, top_hwnd: int) -> Optional["SnapshotCover"]:
        u32, _g32 = _load()
        shot = _client_pixels(top_hwnd)
        if shot is None:
            return None
        (x, y, w, h), _pixels = shot
        hwnd = None
        try:
            hwnd = u32.CreateWindowExW(
                _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW
                | _WS_EX_NOACTIVATE,
                "STATIC", None, _WS_POPUP, x, y, w, h,
                top_hwnd, None, None, None)
            if not hwnd or not _push(hwnd, shot):
                return None
            # Directly above the window, not above everything: under whatever
            # already sits over it.
            above = u32.GetWindow(top_hwnd, _GW_HWNDPREV) or None
            u32.SetWindowPos(hwnd, above, 0, 0, 0, 0,
                             _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
            u32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
            if not u32.IsWindowVisible(hwnd):
                print(f"[SnapshotCover] Cover did not show "
                      f"(error {ctypes.get_last_error()}); swapping uncovered")
                return None
            # Shown is not yet on screen: DWM puts a new layered window up at
            # its next present, and a change made before then reached the
            # screen first (the recorder caught the search bar's new text a
            # frame ahead of the cover, 2026-10-28). Wait for that present.
            _dwm_flush()
            cover = cls(hwnd)
            hwnd = None
            return cover
        finally:
            if hwnd:
                u32.DestroyWindow(hwnd)

    def refresh(self, top_hwnd: int, region=None) -> bool:
        """Show what `top_hwnd` draws now, in one step: UpdateLayeredWindow
        swaps the whole picture at once, so the screen goes straight from the
        last frame to this one. The caller makes sure the window has finished
        drawing first (a scroll step paints synchronously before this).
        `region` (x, y, w, h in client pixels) limits the copy to the part
        that changed; the first refresh always copies everything.
        False if it could not (the cover still shows the previous frame)."""
        if not self._hwnd:
            return False
        try:
            return self._refresh(top_hwnd, region)
        except Exception as exc:
            print(f"[SnapshotCover] Refresh failed (non-fatal): {exc}")
            return False

    def _refresh(self, top_hwnd: int, region) -> bool:
        # One GDI copy into a bitmap kept for the cover's life, shown opaque:
        # no Python pixel work, ~1ms where the full _push path took ~16ms
        # (measured 2026-11-02), which every scroll step pays.
        u32, g32 = _load()
        rc = W.RECT()
        if not u32.GetClientRect(top_hwnd, ctypes.byref(rc)):
            return False
        w, h = rc.right - rc.left, rc.bottom - rc.top
        if w <= 0 or h <= 0:
            return False
        if self._buf is None or self._buf[4:] != (w, h):
            region = None
            self._free_buf()
            screen_dc = u32.GetDC(None)
            mem_dc = bmp = None
            try:
                mem_dc = g32.CreateCompatibleDC(screen_dc)
                bmp, bits = _dib(g32, mem_dc, w, h)
            finally:
                u32.ReleaseDC(None, screen_dc)
                if mem_dc and not bmp:
                    g32.DeleteDC(mem_dc)
            if not bmp:
                return False
            self._buf = (mem_dc, bmp, g32.SelectObject(mem_dc, bmp), bits, w, h)
        mem_dc = self._buf[0]
        origin = W.POINT(0, 0)
        u32.ClientToScreen(top_hwnd, ctypes.byref(origin))
        g32.GdiFlush()      # this thread's batched Tk drawing lands first
        win_dc = u32.GetDC(top_hwnd)
        if not win_dc:
            return False
        try:
            x, y, cw, ch = region or (0, 0, w, h)
            if not g32.BitBlt(mem_dc, x, y, cw, ch, win_dc, x, y, _SRCCOPY):
                return False
        finally:
            u32.ReleaseDC(top_hwnd, win_dc)
        # Only the copied part goes to DWM (prcDirty); the rest of the
        # cover keeps the pixels it already has.
        # Shown with a CONSTANT alpha of 255 and no per-pixel alpha, never
        # ULW_OPAQUE: the cover was created per-pixel (_push) and DWM kept
        # that mode, so ULW_OPAQUE was ignored and the BitBlt copy's alpha
        # bytes (0) made the cover ADD its pixels onto the page under it:
        # orange turned yellow, greys lightened, every row showed twice
        # while scrolling (Ryan, 2026-11-04; measured (243,146,0) on the
        # screen before refresh, (255,255,0) after). _opaque_blend() ignores
        # the alpha bytes whatever mode the window was in.
        dirty = W.RECT(x, y, x + cw, y + ch)
        blend = _opaque_blend()
        info = _ULWInfo(ctypes.sizeof(_ULWInfo), None, ctypes.pointer(origin),
                        ctypes.pointer(W.SIZE(w, h)), mem_dc,
                        ctypes.pointer(W.POINT(0, 0)), 0,
                        ctypes.cast(ctypes.pointer(blend), ctypes.c_void_p),
                        _ULW_ALPHA, ctypes.pointer(dirty))
        if u32.UpdateLayeredWindowIndirect(self._hwnd, ctypes.byref(info)):
            return True
        return bool(u32.UpdateLayeredWindow(
            self._hwnd, None, ctypes.byref(origin), ctypes.byref(W.SIZE(w, h)),
            mem_dc, ctypes.byref(W.POINT(0, 0)), 0, ctypes.byref(blend),
            _ULW_ALPHA))

    def picture(self):
        """(w, h, BGRA bytes) of what the cover shows since its last
        refresh(), or None before the first. For tools/scroll_check.py."""
        if self._buf is None:
            return None
        _dc, _bmp, _old, bits, w, h = self._buf
        return w, h, ctypes.string_at(bits.value, w * h * 4)

    def _free_buf(self) -> None:
        buf, self._buf = self._buf, None
        if buf is None:
            return
        _u32, g32 = _load()
        mem_dc, bmp, old, _bits, _w, _h = buf
        if old:
            g32.SelectObject(mem_dc, old)
        g32.DeleteObject(bmp)
        g32.DeleteDC(mem_dc)

    def close(self) -> None:
        hwnd, self._hwnd = self._hwnd, None
        try:
            self._free_buf()
        except Exception as exc:
            print(f"[SnapshotCover] Freeing the picture failed (non-fatal): {exc}")
        if hwnd:
            try:
                _load()[0].DestroyWindow(hwnd)
            except Exception as exc:
                print(f"[SnapshotCover] Close failed (non-fatal): {exc}")
