"""A still picture of a window's client area, held over it while it repaints.

Tk child windows keep no pixels of their own: when a page is swapped, every
widget redraws from scratch over several passes of the event loop, and Windows
shows each pass as it lands (the half-drawn dashboard at sign-in). The
top-level window, on the other hand, is composited off screen by DWM, so if
something covers it while Tk repaints, removing the cover shows the finished
page in one frame.

The cover is a layered, click-through, never-activating popup owned by the
window, filled once with PrintWindow's copy of the client area via
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

_api = None


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", W.WORD),
                ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", W.DWORD),
                ("biClrImportant", W.DWORD)]


class _Blend(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


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
    _api = (u32, g32)
    return _api


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
    screen_dc = u32.GetDC(None)
    mem_dc = g32.CreateCompatibleDC(screen_dc)
    bmp, bits = _dib(g32, mem_dc, w, h)
    old = g32.SelectObject(mem_dc, bmp) if bmp else None
    try:
        if not bmp or not bits.value:
            return None
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
        u32, g32 = _load()
        shot = _client_pixels(top_hwnd)
        if shot is None:
            return None
        (x, y, w, h), pixels = shot
        pixels = bytearray(pixels)
        pixels[3::4] = bytes([255]) * (w * h)        # opaque
        screen_dc = u32.GetDC(None)
        mem_dc = g32.CreateCompatibleDC(screen_dc)
        bmp, bits = _dib(g32, mem_dc, w, h)
        old = g32.SelectObject(mem_dc, bmp) if bmp else None
        hwnd = None
        try:
            if not bmp or not bits.value:
                return None
            ctypes.memmove(bits.value, bytes(pixels), len(pixels))
            hwnd = u32.CreateWindowExW(
                _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW
                | _WS_EX_NOACTIVATE,
                "STATIC", None, _WS_POPUP, x, y, w, h,
                top_hwnd, None, None, None)
            if not hwnd:
                return None
            origin = W.POINT(x, y)
            blend = _Blend(0, 0, 255, 1)              # AC_SRC_OVER, AC_SRC_ALPHA
            if not u32.UpdateLayeredWindow(
                    hwnd, screen_dc, ctypes.byref(origin),
                    ctypes.byref(W.SIZE(w, h)), mem_dc,
                    ctypes.byref(W.POINT(0, 0)), 0, ctypes.byref(blend),
                    _ULW_ALPHA):
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
            cover = cls(hwnd)
            hwnd = None
            return cover
        finally:
            if hwnd:
                u32.DestroyWindow(hwnd)
            if old:
                g32.SelectObject(mem_dc, old)
            if bmp:
                g32.DeleteObject(bmp)
            g32.DeleteDC(mem_dc)
            u32.ReleaseDC(None, screen_dc)

    def close(self) -> None:
        hwnd, self._hwnd = self._hwnd, None
        if hwnd:
            try:
                _load()[0].DestroyWindow(hwnd)
            except Exception as exc:
                print(f"[SnapshotCover] Close failed (non-fatal): {exc}")
