"""
Brand artwork for every window: the BrightLink | Echo lockup, the chain + Echo
badge, and the window / exe icon.

The sources live in assets/brand and are the BrightLink CRM's own files (the
chain mark is the CRM's favicon, the wordmark its sidebar mark) plus the Echo
wordmark supplied for this product. Each is far larger than anything drawn
here, so every image is a LANCZOS downscale and stays sharp.

Raw PIL images are loaded once and shared; each caller gets its own
PhotoImage bound to its own Tk root, which tkinter requires.
"""

import os
import sys
import threading

_lock = threading.Lock()
_images: dict = {}
# In a frozen PyInstaller exe, data files are extracted to sys._MEIPASS
_BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
_BRAND_DIR = os.path.join(_BASE_DIR, "assets", "brand")

MARK = "brightlink-mark.png"                  # the chain: CRM favicon, 512px
WORDMARK = "brightlink-wordmark-on-dark.png"  # chain + "BrightLink", 1036x250
ECHO = "echo-wordmark.png"                    # "Echo", orange gradient
BADGE = "echo-badge.png"                      # chain + "Echo"

# Measured off the artwork: where the capitals sit, so the two wordmarks can
# share a baseline and a cap height rather than being centred by their boxes
# (which puts Echo's baseline visibly above BrightLink's).
_WORDMARK_SIZE = (1036, 250)
_WORDMARK_CAP = 100          # "B", rows 73..172
_WORDMARK_BASELINE = 172
_ECHO_CAP = 49               # "E", rows 4..52
_ECHO_BASELINE = 52

DIVIDER = "#454545"          # between BrightLink and Echo; #3a3a3a all but vanished


def _asset(name: str):
    """The raw RGBA image, loaded once. None when missing or PIL is absent."""
    with _lock:
        if name not in _images:
            img = None
            try:
                from PIL import Image
                path = os.path.join(_BRAND_DIR, name)
                if os.path.exists(path):
                    img = Image.open(path).convert("RGBA")
            except Exception:
                img = None
            _images[name] = img
        return _images[name]


def lockup_image(height: int = 46, echo_scale: float = 1.1):
    """BrightLink's wordmark, a hairline divider, then Echo: the product
    sitting under the company name. `height` is the wordmark's; Echo's capitals
    are `echo_scale` times BrightLink's and stand on the same baseline."""
    from PIL import Image, ImageDraw
    wm, echo = _asset(WORDMARK), _asset(ECHO)
    if wm is None or echo is None:
        return None
    s1 = height / _WORDMARK_SIZE[1]
    cap = _WORDMARK_CAP * s1
    baseline = _WORDMARK_BASELINE * s1
    wm = wm.resize((round(wm.width * s1), height), Image.LANCZOS)
    s2 = cap * echo_scale / _ECHO_CAP
    echo = echo.resize((max(1, round(echo.width * s2)),
                        max(1, round(echo.height * s2))), Image.LANCZOS)
    gap = round(cap)
    x_div = wm.width + gap
    x_echo = x_div + 1 + gap
    y_echo = round(baseline - _ECHO_BASELINE * s2)
    top = min(0, y_echo)
    h = max(height, y_echo + echo.height) - top
    img = Image.new("RGBA", (x_echo + echo.width, h), (0, 0, 0, 0))
    img.paste(wm, (0, -top), wm)
    div_h = round(cap * 1.7)
    div_y = round(baseline - cap / 2 - div_h / 2) - top
    ImageDraw.Draw(img).rectangle([x_div, div_y, x_div, div_y + div_h - 1],
                                  fill=DIVIDER)
    img.paste(echo, (x_echo, y_echo - top), echo)
    return img


def badge_image(height: int = 28):
    """The chain and Echo, for the small badge that pops up after dictation."""
    from PIL import Image
    src = _asset(BADGE)
    if src is None:
        return None
    return src.resize((max(1, round(src.width * height / src.height)), height),
                      Image.LANCZOS)


def _photo(img, master, bg_color: str):
    if img is None:
        return None
    try:
        from PIL import Image, ImageTk
        flat = Image.new("RGB", img.size, bg_color)
        flat.paste(img, mask=img.getchannel("A"))
        return ImageTk.PhotoImage(flat, master=master)
    except Exception:
        return None


def get_lockup_photo(master, bg_color: str, height: int = 46):
    """PhotoImage of the BrightLink | Echo lockup, or None if unavailable."""
    try:
        return _photo(lockup_image(height), master, bg_color)
    except Exception:
        return None


def get_badge_photo(master, bg_color: str, height: int = 28):
    """PhotoImage of the chain + Echo badge, or None if unavailable."""
    try:
        return _photo(badge_image(height), master, bg_color)
    except Exception:
        return None


def get_logo_photo(master, bg_color: str, max_w: int = 180, max_h: int = 60):
    """The lockup fitted inside (max_w, max_h). Kept for older call sites;
    new ones should ask for a height with get_lockup_photo."""
    try:
        img = lockup_image(max_h)
        if img is None:
            return None
        if img.width > max_w:
            from PIL import Image
            img = img.resize((max_w, max(1, round(img.height * max_w / img.width))),
                             Image.LANCZOS)
        return _photo(img, master, bg_color)
    except Exception:
        return None


# ── Window / exe icon ────────────────────────────────────────────────────────

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

# The app icon: the chain over "Echo" on a dark rounded tile, so the taskbar
# tells Echo apart from the BrightLink CRM's plain chain. Stacked, not side by
# side as the pop-up badge is: in a square, side by side leaves "Echo" about
# 4px tall at taskbar size (a smudge, as "whisper" was on the old FTC tile),
# stacked gives it the full width. Below TEXT_MIN_PX there is no legible
# "Echo" at all, so those frames (the title bar's 16px, beside a title that
# already says Echo) carry the chain alone.
ICON_TILE = (13, 13, 13, 255)
ICON_RADIUS = 0.2
TEXT_MIN_PX = 24
_ICON_SS = 8


def app_icon_image(size: int):
    """One square frame of the app icon, `size` px, RGBA."""
    from PIL import Image, ImageDraw
    mark, echo = _asset(MARK), _asset(ECHO)
    if mark is None:
        return None
    mark = mark.crop(mark.getchannel("A").getbbox())
    big = size * _ICON_SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        [0, 0, big - 1, big - 1], radius=int(big * ICON_RADIUS), fill=ICON_TILE)
    ma = mark.width / mark.height

    def put(src, w, h, x, y):
        part = src.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
        img.paste(part, (int(x), int(y)), part)

    if size < TEXT_MIN_PX or echo is None:
        inner = big * 0.84
        w, h = (inner, inner / ma) if ma >= 1 else (inner * ma, inner)
        put(mark, w, h, (big - w) / 2, (big - h) / 2)
    else:
        echo = echo.crop(echo.getchannel("A").getbbox())
        inner = big * 0.84
        gap = big * 0.04
        ew, eh = inner, inner * echo.height / echo.width
        ch = inner - eh - gap
        cw = ch * ma
        if cw > inner:
            cw, ch = inner, inner / ma
        top = (big - (ch + gap + eh)) / 2
        put(mark, cw, ch, (big - cw) / 2, top)
        put(echo, ew, eh, (big - ew) / 2, top + ch + gap)
    return img.resize((size, size), Image.LANCZOS)


def icon_frames():
    """The app icon at every size a Windows .ico should carry."""
    frames = [app_icon_image(s) for s in ICON_SIZES]
    return [f for f in frames if f is not None]


def write_icon(path: str) -> bool:
    """Write the chain mark as a multi-size .ico. True on success."""
    frames = icon_frames()
    if not frames:
        return False
    big = frames[-1]
    big.save(path, format="ICO", sizes=[(f.width, f.height) for f in frames],
             append_images=frames[:-1])
    return True


def get_icon_path():
    """Absolute path to logo.ico (the window/taskbar icon), or None if missing.
    Works both frozen (sys._MEIPASS) and from source."""
    path = os.path.join(_BASE_DIR, "logo.ico")
    return path if os.path.exists(path) else None
