"""Frame recorder for tools/page_change_check.py (runs as its own process).

Waits for <out>/go.txt, then records the Echo window's client area straight
from the screen (BitBlt with CAPTUREBLT, so the layered SnapshotCover is in
the picture exactly as a person sees it) until <out>/stop.txt appears. Only
frames that differ from the previous one are kept, as half-size greyscale
PNGs named f<index>_<perf_counter>.png. perf_counter is system-wide on
Windows, so the timestamps line up with the checker's action log.

usage: _frame_capture.py <out_dir> <window title>
"""

import ctypes
import os
import sys
import time
from ctypes import wintypes as W

ctypes.windll.shcore.SetProcessDpiAwareness(2)   # physical pixels
out, title = os.path.abspath(sys.argv[1]), sys.argv[2]
u32 = ctypes.WinDLL("user32")
g32 = ctypes.WinDLL("gdi32")
u32.FindWindowW.restype = W.HWND
u32.GetDC.restype = W.HDC
u32.GetDC.argtypes = [W.HWND]
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
hwnd = u32.FindWindowW(None, title)
if not hwnd:
    print("[capture] window not found", flush=True)
    sys.exit(3)
rc = W.RECT()
u32.GetClientRect(hwnd, ctypes.byref(rc))
origin = W.POINT(0, 0)
u32.ClientToScreen(hwnd, ctypes.byref(origin))
# Inset past the window edge: the only pixels a cover may differ by.
INSET = 4
x0, y0 = origin.x + INSET, origin.y + INSET
w, h = rc.right - 2 * INSET, rc.bottom - 2 * INSET
with open(os.path.join(out, "box.txt"), "w") as fh:
    fh.write(f"{x0},{y0},{w},{h}")
sdc = u32.GetDC(None)
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
    Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1).convert(
        "L").resize((w // 2, h // 2)).save(
        os.path.join(out, f"f{i:05d}_{t:.4f}.png"))
print(f"[capture] {len(frames)} distinct frames", flush=True)
