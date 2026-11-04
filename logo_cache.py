"""
Brand artwork for every window: the BrightLink | Echo lockup (Echo's icon in
place of the wordmark's chain), the chain + Echo badge on the dictation
pop-up (kept as it is), and the window / exe icon (Echo's icon).

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
ECHO_ICON = "echo-icon.png"                   # Echo's own mark: link, bars, waves

# Where the sound waves start in echo-icon.png (first clear column after the
# white link). Frames too small to show the waves as more than a smudge drop
# them, so the link and bars fill the space.
_ECHO_ICON_WAVES_X = 1305

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
    wm = _wordmark_with_echo_icon(wm)
    s1 = height / _WORDMARK_SIZE[1]
    cap = _WORDMARK_CAP * s1
    baseline = _WORDMARK_BASELINE * s1
    wm = wm.resize((max(1, round(wm.width * s1)), height), Image.LANCZOS)
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


# The wordmark's chain ends at this column; "BrightLink" starts after it.
_WORDMARK_CHAIN_W = 334
_WORDMARK_TEXT_PAD = 31      # clear columns at the start of the text crop
# Echo icon in the lockup, in wordmark units (cap height 100): about the
# height of "BrightLink" with its descender, and a clear half-cap gap before
# the "B" so the waves never crowd it (Ryan, 2026-11-04: at 0.8 and a 31
# gap the icon looked oversized and jammed against the text).
_LOCKUP_ICON_H = 0.7         # share of the wordmark's 250 height
_LOCKUP_ICON_GAP = 48        # waves to "B"


def _lockup_text_x(icon_w: int) -> int:
    """Where the text crop (which starts _WORDMARK_TEXT_PAD clear columns
    before the "B") goes, beside an icon `icon_w` wide."""
    return icon_w + _LOCKUP_ICON_GAP - _WORDMARK_TEXT_PAD


def _lockup_icon_size():
    icon = _asset(ECHO_ICON)
    if icon is None:
        return None
    ih = round(_WORDMARK_SIZE[1] * _LOCKUP_ICON_H)
    return round(icon.width * ih / icon.height), ih


def _wordmark_with_echo_icon(wm):
    """The BrightLink wordmark with its chain swapped for Echo's own icon
    (Ryan, 2026-11-04). The box keeps its height, so the baseline and cap
    height the lockup measures still hold. The plain wordmark when the icon
    is missing."""
    from PIL import Image
    size = _lockup_icon_size()
    if size is None or wm.size != _WORDMARK_SIZE:
        return wm
    iw, ih = size
    icon = _asset(ECHO_ICON).resize((iw, ih), Image.LANCZOS)
    text = wm.crop((_WORDMARK_CHAIN_W, 0, wm.width, wm.height))
    x_text = _lockup_text_x(iw)
    out = Image.new("RGBA", (x_text + text.width, wm.height), (0, 0, 0, 0))
    # Centred on the capitals (rows 73..172), not the box, so it sits level
    # with the word rather than a touch low.
    cap_mid = _WORDMARK_BASELINE - _WORDMARK_CAP / 2
    out.paste(icon, (0, round(cap_mid - ih / 2)), icon)
    out.paste(text, (x_text, 0), text)
    return out


# The badge's "Echo" fades from white into the brand orange, left to right
# (Ryan, 2026-10-06): it picks up the chain's white link and ends on its
# orange one.
ECHO_FADE_FROM = (255, 255, 255)
ECHO_FADE_TO = (243, 146, 0)          # brand orange #f39200


def _faded_badge(src):
    """The badge with its "Echo" recoloured as a white-to-orange fade. The
    word starts after the first fully clear column that follows the chain;
    its own alpha (the letter shapes and their soft edges) is kept."""
    from PIL import Image
    alpha = src.getchannel("A")
    w, h = src.size
    seen_ink, split = False, None
    for x in range(w):
        ink = alpha.crop((x, 0, x + 1, h)).getbbox() is not None
        if ink:
            seen_ink = True
        elif seen_ink:
            split = x
            break
    if split is None:
        return src
    word = src.crop((split, 0, w, h))
    box = word.getchannel("A").getbbox()
    if box is None:
        return src
    x0, x1 = box[0], box[2]
    ramp = Image.linear_gradient("L").rotate(90, expand=True)  # black left
    # Full orange from about two-thirds along, so the "o" reads as brand
    # orange at badge size rather than a pale peach.
    mask = ramp.resize((max(1, x1 - x0), h)).point(
        lambda v: min(255, round(v * 1.5)))
    full = Image.new("L", word.size, 0)
    full.paste(mask, (x0, 0))
    full.paste(255, (x1, 0, word.width, h))
    fade = Image.composite(Image.new("RGB", word.size, ECHO_FADE_TO),
                           Image.new("RGB", word.size, ECHO_FADE_FROM), full)
    fade.putalpha(word.getchannel("A"))
    out = src.copy()
    out.paste(fade, (split, 0))
    return out


def badge_image(height: int = 28, fade: bool = True):
    """The chain and Echo, for the small badge that pops up after dictation.
    `fade` gives "Echo" its white-to-orange fade."""
    from PIL import Image
    src = _asset(BADGE)
    if src is None:
        return None
    if fade:
        try:
            src = _faded_badge(src)
        except Exception as e:
            print(f"[logo_cache] Echo fade skipped: {e}")
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

# The app icon (exe, taskbar, title bar, Start menu, notifications, tray):
# Echo's own mark, the link with sound bars and waves (Ryan's artwork,
# 2026-11-04), on the dark rounded tile the taskbar has always shown. It
# replaces the chain over "Echo" text. Below WAVES_MIN_PX the waves are a
# smudge, so those frames (title bar, tray) carry the link and bars alone.
# ICON_REV names the rendered notification icon: bump it with any redesign so
# installs render the new one instead of keeping the old picture.
ICON_REV = "2026-11-04"
ICON_TILE = (13, 13, 13, 255)
ICON_RADIUS = 0.2
WAVES_MIN_PX = 32
_ICON_SS = 8


def app_icon_image(size: int, simple: bool = False):
    """One square frame of the app icon, `size` px, RGBA. `simple` drops the
    sound waves at any size (the tray wants the boldest form)."""
    from PIL import Image, ImageDraw
    art = _asset(ECHO_ICON)
    if art is None:
        art = _asset(MARK)
        if art is None:
            return None
        art = art.crop(art.getchannel("A").getbbox())
    elif simple or size < WAVES_MIN_PX:
        art = art.crop((0, 0, _ECHO_ICON_WAVES_X, art.height))
        art = art.crop(art.getchannel("A").getbbox())
    big = size * _ICON_SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        [0, 0, big - 1, big - 1], radius=int(big * ICON_RADIUS), fill=ICON_TILE)
    inner = big * (0.9 if size < WAVES_MIN_PX else 0.84)
    ar = art.width / art.height
    w, h = (inner, inner / ar) if ar >= 1 else (inner * ar, inner)
    part = art.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
    img.paste(part, (int((big - w) / 2), int((big - h) / 2)), part)
    return img.resize((size, size), Image.LANCZOS)


def icon_frames():
    """The app icon at every size a Windows .ico should carry."""
    frames = [app_icon_image(s) for s in ICON_SIZES]
    return [f for f in frames if f is not None]


def write_icon(path: str) -> bool:
    """Write the app icon as a multi-size .ico. True on success."""
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
