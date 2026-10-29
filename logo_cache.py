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

# The app icon (Ryan, 2026-10-28): one tilted BrightLink link, orange half and
# white half, with sound bars inside it and two sound waves off its right end,
# on a dark rounded tile. No "Echo" text: the shape says Echo on its own and
# tells it apart from the CRM's plain chain. Drawn here as distance fields, not
# from a bitmap, so every frame is crisp. At SIMPLE_MAX_PX and under the waves
# go (they smudge) and the link grows to fill the tile, with three bars.
# Bump ICON_REV whenever the drawing changes: installs re-render their cached
# notification icon and refresh Windows' icon cache once per revision.
ICON_REV = 2
ICON_TILE = (13, 13, 13, 255)
ICON_RADIUS = 0.2
SIMPLE_MAX_PX = 24
_ORANGE = ((255, 184, 0), (255, 98, 0))     # top-left -> bottom-right
_WHITE = ((246, 246, 246), (196, 196, 200))


def app_icon_image(size: int, simple: bool = None):
    """One square frame of the app icon, `size` px, RGBA. `simple` (no waves,
    three bars, heavier strokes) defaults to the small-size rule; the tray
    asks for it at 64px because Windows shows that frame at 16-24px."""
    import math

    import numpy as np
    from PIL import Image
    if simple is None:
        simple = size <= SIMPLE_MAX_PX
    small = simple  # the simple form is for small sizes: heavier strokes
    ss = 4 if size <= 64 else 2
    n = size * ss
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    x, y = (xs + 0.5) / n, (ys + 0.5) / n
    aa = 1.0 / n

    def cov(d):  # coverage from a signed distance, negative inside
        return np.clip(0.5 - d / aa, 0.0, 1.0)

    def ramp(t, pair):
        a, b = (np.array(c, np.float32) for c in pair)
        t = np.clip(t, 0, 1)[..., None]
        return a * (1 - t) + b * t

    rgb = np.zeros((n, n, 3), np.float32)
    alpha = np.zeros((n, n), np.float32)

    def layer(mask, colour):
        m = mask[..., None]
        rgb[:] = rgb * (1 - m) + colour * m
        alpha[:] = alpha * (1 - mask) + mask

    # Tile
    q = 0.5 - ICON_RADIUS
    qx, qy = np.abs(x - 0.5) - q, np.abs(y - 0.5) - q
    d = (np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2)
         + np.minimum(np.maximum(qx, qy), 0) - ICON_RADIUS)
    layer(cov(d), np.array(ICON_TILE[:3], np.float32))

    # The link: a stadium outline along an axis rising 28 degrees, cut in two
    # by screen-vertical slants, the upper arm right of centre, the lower left.
    cx, cy = (0.5, 0.5) if simple else (0.42, 0.5)
    h, r, w = (0.19, 0.18, 0.085) if simple else (0.16, 0.15, 0.07)
    if small:
        w *= 1.25
    th = math.radians(28)
    ux, uy = math.cos(th), -math.sin(th)
    dx, dy = x - cx, y - cy
    u = dx * ux + dy * uy
    v = -dx * uy + dy * ux
    dist = np.sqrt((u - np.clip(u, -h, h)) ** 2 + v ** 2)
    ring = cov(np.abs(dist - r) - w / 2)
    gap, cut = (0.06 if small else 0.045), 0.05
    # One straight line per cut; the end caps lie wholly on their own side.
    edge = np.where(v < 0, cut, -cut)
    tint = x + y - 0.4
    layer(ring * cov(dx - (edge - gap / 2)), ramp(tint, _ORANGE))
    layer(ring * cov((edge + gap / 2) - dx), ramp(tint, _WHITE))

    # Sound bars: round-ended, centred in the link
    heights = (0.55, 1.0, 0.55) if simple else (0.36, 0.64, 1.0, 0.64, 0.36)
    bw, pitch = (0.07, 0.1) if small else (0.04, 0.06)
    tall = 0.26 if small else 0.25 if simple else 0.21
    bars = np.zeros_like(x)
    for i, k in enumerate(heights):
        bx = cx + (i - (len(heights) - 1) / 2) * pitch
        reach = max(0.0, tall * k / 2 - bw / 2)
        py = np.clip(y - cy, -reach, reach)
        bars = np.maximum(bars, cov(np.sqrt((x - bx) ** 2 + (y - cy - py) ** 2) - bw / 2))
    layer(bars, ramp((y - (cy - tall / 2)) / tall, _ORANGE))

    # Sound waves: two round-capped arcs off the link's right end
    if not simple:
        acx, acy, span, ww = 0.675, 0.545, math.radians(38), 0.036
        ang = np.arctan2(y - acy, x - acx)
        rr = np.sqrt((x - acx) ** 2 + (y - acy) ** 2)
        waves = np.zeros_like(x)
        for R in (0.165, 0.235):
            d = np.where(np.abs(ang) <= span, np.abs(rr - R) - ww / 2, 1.0)
            for s in (-span, span):
                ex, ey = acx + R * math.cos(s), acy + R * math.sin(s)
                d = np.minimum(d, np.sqrt((x - ex) ** 2 + (y - ey) ** 2) - ww / 2)
            waves = np.maximum(waves, cov(d))
        layer(waves, ramp((y - 0.3) / 0.45, _ORANGE))

    px = np.dstack([rgb, alpha[..., None] * 255]).clip(0, 255).astype(np.uint8)
    return Image.fromarray(px, "RGBA").resize((size, size), Image.LANCZOS)


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
