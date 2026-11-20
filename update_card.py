"""The Echo updated card and its contained confetti, drawn with PIL and maths."""
from __future__ import annotations

import math
import os
import random

# Brightlink CONFETTI_COLOURS: orange first, then bright accents, never dark.
CONFETTI_COLOURS = ("#f39200", "#fbbf24", "#22c55e", "#06b6d4", "#8b5cf6", "#ffffff")

CARD_W = 300
RADIUS = 16
_SS = 4  # supersample: draw at 4x, shrink once, so every edge is smooth

SURFACE = "#1a1a1a"
BORDER = "#2d2d2d"
PANEL = "#212121"
TEXT = "#ffffff"
SUBTEXT = "#9a9a9a"
ACCENT = "#f39200"
ACCENT_HOVER = "#e08200"
SUCCESS = "#22c55e"

# Layout at 1x (px).
def _s(px: float) -> int:
    return round(px * CARD_W / 340)


_PAD = _s(24)
_ICON = _s(56)
_ROW_H = _s(38)
_BTN_H = _s(44)

_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def _font(weight: str, px: int):
    from PIL import ImageFont
    names = {"regular": ("segoeui.ttf",),
             "semibold": ("seguisb.ttf", "segoeuib.ttf", "segoeui.ttf"),
             "bold": ("segoeuib.ttf", "seguisb.ttf", "segoeui.ttf")}[weight]
    for n in names:
        try:
            return ImageFont.truetype(os.path.join(_FONT_DIR, n), px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(px)
    except TypeError:
        return ImageFont.load_default()


def card_rows(prev_version: str, new_version: str) -> list[tuple[str, str]]:
    rows = [("Version", f"v{new_version}")]
    if prev_version:
        rows.append(("Previously", f"v{prev_version}"))
    rows.append(("Updates", "Automatic"))
    return rows


def card_height(n_rows: int) -> int:
    return (_PAD + _s(8) + _ICON + _s(16) + _s(26) + _s(8)
            + _s(20) + _s(18) + n_rows * _ROW_H + _s(18)
            + _BTN_H + _PAD)


def button_box(n_rows: int) -> tuple[int, int, int, int]:
    """The button's (x0, y0, x1, y1) on the card at 1x, for clicks and hover."""
    h = card_height(n_rows)
    return (_PAD, h - _PAD - _BTN_H, CARD_W - _PAD, h - _PAD)


def _mix(a: str, b: str, t: float) -> tuple[int, int, int]:
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return tuple(round(x + (y - x) * t) for x, y in zip(pa, pb))


def render_card(prev_version: str, new_version: str, product_name: str,
                hover: bool = False, key_colour: str | None = None):
    """The whole card as one RGBA image at 1x.

    `key_colour`: the window's see-through colour. Pixels outside the card are
    painted that colour with a hard edge (no blending), so no dark fringe shows
    round the corners on a light desktop.
    """
    from PIL import Image, ImageDraw, ImageChops

    rows = card_rows(prev_version, new_version)
    w, h = CARD_W, card_height(len(rows))
    S = _SS
    W, H = w * S, h * S
    img = Image.new("RGBA", (W, H), SURFACE)

    # Brand warmth: soft orange light from the top-left corner (radial, ~22%).
    glow = Image.radial_gradient("L").resize((int(W * 2.4), int(H * 1.4)))
    glow = ImageChops.invert(glow)
    glow = glow.point(lambda v: int(max(0, v - 90) * 0.22 * 255 / 165))
    layer = Image.new("L", (W, H), 0)
    layer.paste(glow, (-glow.width // 2, -glow.height // 2))
    img = Image.composite(Image.new("RGBA", (W, H), ACCENT), img, layer)
    d = ImageDraw.Draw(img)

    y = (_PAD + _s(8)) * S
    # App icon with the green tick badge, bottom right.
    ix = (w - _ICON) // 2 * S
    try:
        from logo_cache import app_icon_image
        icon = app_icon_image(_ICON * S)
    except Exception:
        icon = None
    if icon is not None:
        mask = Image.new("L", icon.size, 0)
        ImageDraw.Draw(mask).ellipse([0, 0, icon.width - 1, icon.height - 1], fill=255)
        icon_alpha = ImageChops.multiply(icon.getchannel("A"), mask)
        img.paste(icon, (ix, y), icon_alpha)
    else:
        d.ellipse([ix, y, ix + _ICON * S, y + _ICON * S], fill="#0d0d0d")
    b = _s(24) * S
    bx, by = ix + _ICON * S - b + _s(4) * S, y + _ICON * S - b + _s(4) * S
    ring = _s(2) * S
    d.ellipse([bx - ring, by - ring, bx + b + ring, by + b + ring], fill=SURFACE)
    d.ellipse([bx, by, bx + b, by + b], fill=SUCCESS)
    cx, cy = bx + b / 2, by + b / 2
    u = b / 24
    d.line([(cx - 5.5 * u, cy + 0.2 * u), (cx - 1.8 * u, cy + 4 * u),
            (cx + 5.8 * u, cy - 4.2 * u)], fill="#ffffff", width=int(3 * u),
           joint="curve")
    for px_, py_ in ((cx - 5.5 * u, cy + 0.2 * u), (cx + 5.8 * u, cy - 4.2 * u)):
        r = 1.5 * u
        d.ellipse([px_ - r, py_ - r, px_ + r, py_ + r], fill="#ffffff")
    y += (_ICON + _s(16)) * S

    # Title and one plain line.
    title = _font("semibold", _s(20) * S)
    import brand
    d.text((W / 2, y + _s(13) * S), f"{brand.PRODUCT_SHORT_NAME} updated to v{new_version}",
           font=title,
           fill=TEXT, anchor="mm")
    y += (_s(26) + _s(8)) * S
    body = _font("regular", _s(13) * S)
    d.text((W / 2, y + _s(10) * S), "Up to date. Your settings are kept.",
           font=body, fill=SUBTEXT, anchor="mm")
    y += (_s(20) + _s(18)) * S

    # Label / value panel.
    px0, px1 = _PAD * S, (w - _PAD) * S
    ph = len(rows) * _ROW_H * S
    d.rounded_rectangle([px0, y, px1, y + ph], radius=_s(12) * S,
                        fill=_mix(SURFACE, PANEL, 1.0), outline=BORDER, width=S)
    label = _font("regular", _s(13) * S)
    value = _font("semibold", _s(13) * S)
    for i, (k, v) in enumerate(rows):
        ry = y + i * _ROW_H * S
        if i:
            d.line([(px0 + S, ry), (px1 - S, ry)], fill=BORDER, width=S)
        mid = ry + _ROW_H * S / 2
        d.text((px0 + _s(16) * S, mid), k, font=label, fill=SUBTEXT, anchor="lm")
        d.text((px1 - _s(16) * S, mid), v, font=value, fill=TEXT, anchor="rm")
    y += ph + _s(18) * S

    # Full-width orange button: "Got it" and an arrow.
    bx0, by0, bx1, by1 = [c * S for c in button_box(len(rows))]
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=_s(10) * S,
                        fill=ACCENT_HOVER if hover else ACCENT)
    btn = _font("semibold", _s(14) * S)
    label_txt = "Got it"
    tw = d.textlength(label_txt, font=btn)
    gap, aw = _s(8) * S, _s(12) * S
    tx = (W - (tw + gap + aw)) / 2
    my = (by0 + by1) / 2
    d.text((tx, my), label_txt, font=btn, fill="#ffffff", anchor="lm")
    ax = tx + tw + gap
    lw = int(_s(2) * S)
    d.line([(ax, my), (ax + aw, my)], fill="#ffffff", width=lw)
    d.line([(ax + aw - 5 * S, my - 5 * S), (ax + aw, my), (ax + aw - 5 * S, my + 5 * S)],
           fill="#ffffff", width=lw, joint="curve")

    # Card edge: hairline border, then the rounded shape.
    shape = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shape).rounded_rectangle([0, 0, W - 1, H - 1], radius=RADIUS * S, fill=255)
    edge = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle([0, 0, W - 1, H - 1], radius=RADIUS * S,
                                           outline=BORDER, width=S)
    img.alpha_composite(edge)
    img.putalpha(shape)
    img = img.resize((w, h), Image.LANCZOS)

    if key_colour:
        # Hard edge against the see-through colour: blend the soft rim onto the
        # border colour instead, so the corners stay smooth with no dark fringe.
        a = img.getchannel("A")
        solid = Image.new("RGBA", (w, h), BORDER)
        solid.alpha_composite(img)
        hard = a.point(lambda v: 255 if v >= 60 else 0)
        out = Image.new("RGBA", (w, h), key_colour)
        out.paste(solid, (0, 0), hard)
        return out
    return img


class Confetti:
    """Timed side cannons, centre burst and rain in card-local pixels."""

    LIFE = 320
    RAIN_END = 2.8
    RAIN_INTERVAL = 0.09
    GRAVITY = 1000.0

    def __init__(self, size: tuple[int, int], seed: int | None = None):
        self.width, self.height = size
        self.rng = random.Random(seed)
        self.pieces: list[dict] = []
        self.emitted = {"left": 0, "right": 0, "centre": 0, "rain": 0}
        self.elapsed = 0.0
        self._centre_fired = False
        self._next_rain = self.RAIN_INTERVAL
        self._next_id = 0
        self._emit("left", 16, 16, self.height - 16, 60, 75, 1550)
        self._emit("right", 16, self.width - 16, self.height - 16, 120, 75, 1550)
        self.pieces = [p for p in self.pieces if self._inside(p)]

    def _emit(self, source: str, count: int, x: float, y: float,
              angle: float, spread: float, speed: float) -> None:
        rng = self.rng
        for _ in range(count):
            a = math.radians(angle + rng.uniform(-spread / 2, spread / 2))
            v = speed * rng.uniform(0.75, 1.15)
            self._next_id += 1
            self.pieces.append({
                "id": self._next_id, "source": source,
                "x": x, "y": y, "vx": math.cos(a) * v,
                "vy": -math.sin(a) * v,
                "w": rng.uniform(5, 8), "h": rng.uniform(5, 8),
                "phase": rng.uniform(0, math.tau),
                "spin": rng.uniform(5, 11) * rng.choice((-1, 1)),
                "drift": rng.uniform(8, 22), "age": 0.0,
                "colour": rng.choice(CONFETTI_COLOURS),
                "round": rng.random() < 0.22,
            })
            self.emitted[source] += 1

    @staticmethod
    def shape(p: dict) -> tuple[float, ...]:
        """Oval bounds or four polygon vertices for the current paper tilt."""
        x, y = p["x"], p["y"]
        width = max(1.0, abs(math.cos(p["phase"])) * p["w"])
        if p["round"]:
            r = width / 2
            return (x - r, y - r, x + r, y + r)
        tilt = math.sin(p["phase"] * 0.7) * 2
        hw, hh = width / 2, p["h"] / 2
        return (x - hw + tilt, y - hh, x + hw + tilt, y - hh,
                x + hw - tilt, y + hh, x - hw - tilt, y + hh)

    def _inside(self, p: dict) -> bool:
        coords = self.shape(p)
        points = ((coords[0], coords[1]), (coords[2], coords[1]),
                  (coords[2], coords[3]), (coords[0], coords[3])) if p["round"] else zip(coords[::2], coords[1::2])
        radius = RADIUS + 1
        for x, y in points:
            if not (0 <= x <= self.width and 0 <= y <= self.height):
                return False
            cx = min(max(x, radius), self.width - radius)
            cy = min(max(y, radius), self.height - radius)
            if (x - cx) ** 2 + (y - cy) ** 2 > (radius - 1) ** 2:
                return False
        return True

    def step(self, dt: float) -> bool:
        """Advance by elapsed seconds; return false after all emissions and pieces end."""
        dt = max(0.0, dt)
        self.elapsed += dt
        if not self._centre_fired and self.elapsed >= 0.28:
            self._centre_fired = True
            self._emit("centre", 18, self.width * 0.5, self.height * 0.4,
                       90, 120, 480)
        while self._next_rain <= min(self.elapsed, self.RAIN_END):
            self._emit("rain", self.rng.choice((1, 1, 2)),
                       self.rng.uniform(8, self.width - 8), 6,
                       270, 50, 25)
            self._next_rain += self.RAIN_INTERVAL
        decay = 0.9 ** (dt * 60)
        for p in self.pieces:
            p["vx"] *= decay
            p["vy"] = p["vy"] * decay + self.GRAVITY * dt
            p["x"] += (p["vx"] + math.sin(p["phase"]) * p["drift"]) * dt
            p["y"] += p["vy"] * dt
            p["phase"] += p["spin"] * dt
            p["age"] += dt * 60
        self.pieces = [p for p in self.pieces if p["age"] < self.LIFE and self._inside(p)]
        return self.elapsed < self.RAIN_END or bool(self.pieces)

    @classmethod
    def opacity(cls, p: dict) -> float:
        return min(1.0, max(0.0, (cls.LIFE - p["age"]) / (cls.LIFE * 0.25)))
