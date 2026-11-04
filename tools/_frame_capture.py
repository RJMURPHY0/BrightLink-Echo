"""Frame recorder for tools/page_change_check.py (runs as its own process).

Waits for <out>/go.txt, then records the Echo window's client area straight
from the screen (BitBlt with CAPTUREBLT, so the layered SnapshotCover is in
the picture exactly as a person sees it) until <out>/stop.txt appears. Only
frames that differ from the previous one are kept, as half-size greyscale
PNGs named f<index>_<perf_counter>.png. perf_counter is system-wide on
Windows, so the timestamps line up with the checker's action log.

If <out>/pane.txt exists (tools/scroll_check.py writes it: the handles of
one pane and of its window, since the installed Echo has the same title, then
1 to read the screen or 0), only that pane is recorded, at full size. With 0
it is read from the window's own drawing surface: what DWM puts on screen,
read even while the window sits behind others, so the check covers nobody's
work and sees every half-drawn state. With 1 it is read from the screen,
cover windows included, as a person sees it.

usage: _frame_capture.py <out_dir> <window title>
"""

import ctypes
import os
import sys
import time
from ctypes import wintypes as W

out, title = os.path.abspath(sys.argv[1]), sys.argv[2]
pane = os.path.join(out, "pane.txt")
if os.path.exists(pane):
    with open(pane) as fh:
        pane_hwnd, hwnd, on_screen = (int(v) for v in fh.read().split(","))
else:
    pane_hwnd, on_screen = 0, 1
if on_screen:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # physical pixels
# A pane read from the window's own surface is in the same (unaware) pixels
# Echo's Tk draws in, so its frames line up one to one with Tk's scroll
# offsets. A pane read from the SCREEN is read in physical pixels (the screen
# holds Echo stretched by the display scale: reading the logical box there
# took the wrong place at 150%, 4 Nov 2026) and scaled back to Tk's pixels.
u32 = ctypes.WinDLL("user32")
g32 = ctypes.WinDLL("gdi32")
u32.FindWindowW.restype = W.HWND
u32.GetDC.restype = W.HDC
u32.GetDC.argtypes = [W.HWND]
u32.ReleaseDC.argtypes = [W.HWND, W.HDC]
u32.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
u32.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
g32.CreateCompatibleDC.restype = W.HDC
g32.CreateCompatibleDC.argtypes = [W.HDC]
g32.CreateDIBSection.restype = W.HBITMAP
g32.CreateDIBSection.argtypes = [W.HDC, ctypes.c_void_p, W.UINT,
                                 ctypes.POINTER(ctypes.c_void_p), W.HANDLE,
                                 W.DWORD]
g32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
g32.BitBlt.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.c_int, W.HDC, ctypes.c_int, ctypes.c_int,
                       W.DWORD]


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", W.WORD),
                ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("a", ctypes.c_long),
                ("b", ctypes.c_long), ("c", W.DWORD), ("d", W.DWORD)]


go, stop = os.path.join(out, "go.txt"), os.path.join(out, "stop.txt")
deadline = time.time() + 120
while not os.path.exists(go):
    if time.time() > deadline:
        sys.exit(2)
    time.sleep(0.01)
if pane_hwnd:
    pass
elif os.path.exists(os.path.join(out, "hwnd.txt")):
    # page_change_check names its window: the installed Echo has the same
    # title, and FindWindow may return that one instead.
    with open(os.path.join(out, "hwnd.txt")) as fh:
        hwnd = int(fh.read().strip())
else:
    hwnd = u32.FindWindowW(None, title)
if not hwnd:
    print("[capture] window not found", flush=True)
    sys.exit(3)
rc = W.RECT()
u32.GetClientRect(hwnd, ctypes.byref(rc))
origin = W.POINT(0, 0)
u32.ClientToScreen(hwnd, ctypes.byref(origin))
logical = None      # (w, h) to scale a screen read back to Tk's pixels
if pane_hwnd:
    u32.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
    pr = W.RECT()
    u32.GetWindowRect(pane_hwnd, ctypes.byref(pr))
    w, h = pr.right - pr.left, pr.bottom - pr.top
    if on_screen:
        # Physical rect (we are DPI aware); the pane's own size in Tk's
        # pixels comes from the window's DPI context.
        u32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
        u32.GetWindowDpiAwarenessContext.argtypes = [W.HWND]
        u32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        ctx = u32.GetWindowDpiAwarenessContext(W.HWND(hwnd))
        dpi = u32.GetAwarenessFromDpiAwarenessContext(ctx)
        scale = 1.0
        if dpi == 0:        # DPI_AWARENESS_UNAWARE: drawn at 96, stretched
            u32.MonitorFromWindow.restype = W.HMONITOR
            mon = u32.MonitorFromWindow(W.HWND(hwnd), 2)
            mx, my = ctypes.c_uint(), ctypes.c_uint()
            ctypes.windll.shcore.GetDpiForMonitor(mon, 0, ctypes.byref(mx),
                                                  ctypes.byref(my))
            scale = mx.value / 96.0
        if abs(scale - 1.0) > 0.01:
            logical = (round(w / scale), round(h / scale))
            with open(os.path.join(out, "scaled.txt"), "w") as fh:
                fh.write(f"{scale:.4f}")
    if on_screen:
        x0, y0 = pr.left, pr.top
        sdc = u32.GetDC(None)
    else:       # window DC coordinates are client coordinates
        x0, y0 = pr.left - origin.x, pr.top - origin.y
        sdc = u32.GetDC(hwnd)
    with open(os.path.join(out, "box.txt"), "w") as fh:
        fh.write(f"{x0},{y0},{w},{h}")
    full = True
else:
    # Inset past the window edge: the only pixels a cover may differ by.
    INSET = 4
    x0, y0 = origin.x + INSET, origin.y + INSET
    w, h = rc.right - 2 * INSET, rc.bottom - 2 * INSET
    with open(os.path.join(out, "box.txt"), "w") as fh:
        fh.write(f"{x0},{y0},{w},{h}")
    sdc, full = u32.GetDC(None), False
mdc = g32.CreateCompatibleDC(sdc)
bits = ctypes.c_void_p()
bih = _BIH(ctypes.sizeof(_BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
bmp = g32.CreateDIBSection(mdc, ctypes.byref(bih), 0, ctypes.byref(bits),
                           None, 0)
g32.SelectObject(mdc, bmp)
n = w * h * 4
frames, prev = [], None
while not os.path.exists(stop) and time.time() < deadline + 120:
    g32.BitBlt(mdc, 0, 0, w, h, sdc, x0, y0, 0x00CC0020 | 0x40000000)
    t = time.perf_counter()
    raw = ctypes.string_at(bits, n)
    if raw != prev:
        frames.append((t, raw))
        prev = raw
from PIL import Image  # noqa: E402  (after the hot loop on purpose)
for i, (t, raw) in enumerate(frames):
    im = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1).convert("L")
    if logical:
        im = im.resize(logical, Image.BOX)
    elif not full:
        im = im.resize((w // 2, h // 2))
    im.save(os.path.join(out, f"f{i:05d}_{t:.4f}.png"))
print(f"[capture] {len(frames)} distinct frames", flush=True)
