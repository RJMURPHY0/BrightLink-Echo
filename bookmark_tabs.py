"""
BrightLink's connected tab strip, drawn for tkinter.

A port of the CRM's page tabs (Brightlink `src/components/BookmarkTabs.tsx`,
the `connected` variant) so the products share one tab design. Every shape,
glow and colour number below is the CRM's own, converted from rem at `REM` px
per rem, so the strip keeps the mockup's proportions at this window's scale.

Each state (current tab x hovered tab x width) is ONE image, rendered with
numpy + PIL at `SS` times the size and downscaled. tk.Canvas has no
anti-aliasing and nearly every surface here is a gradient: the current tab's
orange glow, the rims fading down the sides, the shade one card casts on the
next. Labels stay native canvas text, so they are ClearType like the rest of
the app. Renders are cached per state, so hovering and switching are an image
swap after the first time.
"""

from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont

REM = 15.0                      # px per CRM rem at this window's scale
SS = 4                          # supersample factor

# The current tab's height from its top edge to the line it stands on
# (2.75rem). Every vertical measure of the shape is a fraction of it.
TAB_H = 41
GLOW_ROOM = 2                   # px under the line for the underline's glow
HEIGHT = TAB_H + 1 + GLOW_ROOM  # the strip: tab, line, glow room

SLANT = 0.244                   # horizontal run per unit of rise (13.7deg)
TOP_R = TAB_H * 0.186           # top corner radius
FOOT_R = TAB_H * 0.203          # the concave flare into the baseline
DROP = TAB_H * 0.034            # inactive tabs stand this much lower
OVERLAP = TAB_H * 0.152         # neighbouring boxes overlap by this much

STRIP_PAD = 1.0 * REM           # px-4: room for the end tabs' feet
ICON = 17                       # 1.15rem
ICON_GAP = 0.6 * REM
LABEL_PX = 13                   # text-sm (0.875rem)

# Side padding of a tab. The CRM's page-switcher row uses 1.35rem; this window
# is narrower than any CRM page, so a tab may give up padding down to MIN_PAD
# (still clear of the neighbour's slanted side where it crosses the label)
# before it gives up its icon. Spare room grows the padding back to MAX_PAD,
# and past that the strip simply ends, left-aligned, as the CRM's does.
MAX_PAD = 1.35 * REM
MIN_PAD = 0.8 * REM

# ── Palette (the CRM's dark values) ──────────────────────────────────────────
ORANGE = (243, 146, 0)          # --orange-500
ORANGE_400 = (255, 173, 51)     # --orange-400
ACT_RIM = (255, 214, 170)       # --bt-act-rim
ACT_FILL = (0x21, 0x1E, 0x1A)   # --bt-act
IN_TOP = (0x28, 0x28, 0x28)     # --bt-in-top
IN_BOT = (0x1B, 0x1B, 0x1B)     # --bt-in-bot
FOREGROUND = (0xEB, 0xEB, 0xEB)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

INK_ACTIVE = "#ffffff"
INK_IDLE = "#a9a9a9"            # foreground at 0.67 over the tab fill
INK_HOVER = "#ebebeb"
ICON_ACTIVE = "#ffad33"         # orange-400
ICON_IDLE = "#a3a3a3"           # foreground at 0.64 over the tab fill
ICON_HOVER = "#ebebeb"

# The current tab's glow, fitted to the mockup: an ellipse centred just outside
# the top-left corner, a faint pool on the baseline, a flat tint.
GLOW = {
    "cx": -0.278 * REM, "cy": TAB_H * 0.0675, "rx": 7.22 * REM, "ry": TAB_H * 1.182,
    "stops": ((0, 0.79), (0.1, 0.79), (0.22, 0.6), (0.38, 0.33), (0.58, 0.14),
              (0.8, 0.045), (1, 0)),
    "tint": 0.038,
    "pool": {"cx": 3.06 * REM, "rx": 5.56 * REM, "ry": TAB_H * 0.337,
             "stops": ((0, 0.13), (0.5, 0.05), (1, 0))},
    "rim_reach": TAB_H * 0.532,
}

# The outline and the lit line under the current tab: an orange rim strongest
# along the top and fading down the sides, and an underline that peaks a third
# of the way across and dies out just past each foot. Hovering an unselected
# tab previews both, below selection strength.
EDGE = {
    "rim": ((0, 0.65), (0.12, 0.6), (0.6, 0.35), (0.85, 0.2), (1, 0.15)),
    "underline": ((0, 0.13), (0.16, 0.33), (0.33, 0.62), (0.5, 0.46),
                  (0.66, 0.25), (0.83, 0.1), (1, 0.12)),
    "spill": 0.6 * REM,
    "bloom": 1.2,
    "hover_rim": ((0, 0.88), (0.5, 0.8), (1, 0.74)),
    "hover_underline": 0.55,
}

# The shade a tab casts on the one it overlaps: a tab stacks over the tab to
# its right, so that tab's left edge darkens; the current tab also darkens its
# left neighbour's right edge, more lightly.
SHADE = {
    "right": (1.25 * REM, ((0, 0.26), (0.27, 0.2), (0.45, 0.14), (0.62, 0.086),
                           (0.75, 0.057), (1, 0))),
    "left": (0.56 * REM, ((0, 0.12), (0.7, 0.08), (1, 0))),
}

_CACHE_MAX = 48


# ── Geometry ─────────────────────────────────────────────────────────────────

_ANGLE = math.atan(SLANT)
_SIN, _COS = math.sin(_ANGLE), math.cos(_ANGLE)
# Tangent length of a fillet for the turn between a side and the horizontal.
_TURN = math.tan((math.pi / 2 - _ANGLE) / 2)


def _arc(a, b, c, steps: int = 14):
    """Points from a to b round centre c, the short way (every fillet here is
    under a half turn)."""
    a0 = math.atan2(a[1] - c[1], a[0] - c[0])
    a1 = math.atan2(b[1] - c[1], b[0] - c[0])
    d = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    r = math.hypot(a[0] - c[0], a[1] - c[1])
    return [(c[0] + r * math.cos(a0 + d * i / steps),
             c[1] + r * math.sin(a0 + d * i / steps)) for i in range(steps + 1)]


class TabGeom:
    """One tab's outline. `x0`/`w` are its box, which spans the slanted sides
    at half height; the sides and feet reach past it."""

    def __init__(self, x0: float, w: float, active: bool):
        self.x0, self.w, self.active = x0, w, active
        self.y_top = 0.0 if active else DROP
        self.y_base = float(TAB_H)
        self.y_mid = (DROP + self.y_base) / 2
        rt, rf = TOP_R, FOOT_R
        tt, tf = rt * _TURN, rf * _TURN
        yt, yb = self.y_top, self.y_base
        xl, xr = self.x_left, self.x_right
        rim = []
        rim += _arc((xl(yb) - tf, yb), (xl(yb) + tf * _SIN, yb - tf * _COS),
                    (xl(yb) - tf, yb - rf))
        rim += _arc((xl(yt) - tt * _SIN, yt + tt * _COS), (xl(yt) + tt, yt),
                    (xl(yt) + tt, yt + rt))
        rim += _arc((xr(yt) - tt, yt), (xr(yt) + tt * _SIN, yt + tt * _COS),
                    (xr(yt) - tt, yt + rt))
        rim += _arc((xr(yb) - tf * _SIN, yb - tf * _COS), (xr(yb) + tf, yb),
                    (xr(yb) + tf, yb - rf))
        self.rim = rim
        self.feet = (xl(yb) - tf, xr(yb) + tf)
        # The current tab also covers the line it stands on, opening into the
        # content below it; the others stop exactly on the line.
        bottom = yb + 1 if active else yb
        self.shape = rim + [(self.feet[1], bottom), (self.feet[0], bottom)]

    def x_left(self, y: float) -> float:
        return self.x0 - (y - self.y_mid) * SLANT

    def x_right(self, y: float) -> float:
        return self.x0 + self.w + (y - self.y_mid) * SLANT

    def contains(self, x: float, y: float) -> bool:
        if not (self.y_top <= y <= self.y_base + 1):
            return False
        return self.x_left(y) <= x <= self.x_right(y)


def layout(content_widths, content_widths_bare, avail: float):
    """Box widths and whether icons show, for tabs whose content (icon + gap +
    label) measures `content_widths` (or `content_widths_bare` without the
    icon) in `avail` px of strip. Padding is equal on every tab, as in the
    CRM's page-switcher row, so a longer label makes a wider tab."""
    n = len(content_widths)
    for widths, icons in ((content_widths, True), (content_widths_bare, False)):
        pad = (avail + (n - 1) * OVERLAP - sum(widths)) / (2 * n)
        if pad >= MIN_PAD or not icons:
            pad = max(min(pad, MAX_PAD), 0.4 * REM)
            return [cw + 2 * pad for cw in widths], icons, pad
    raise AssertionError("unreachable")


# ── Rendering ────────────────────────────────────────────────────────────────

def _hex(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


class _Painter:
    """Composites tab layers onto a float RGB array.

    Only the shape masks are supersampled: PIL rasterises them at SS times the
    size and box-filters them down, which is where the anti-aliasing comes
    from. Every gradient is smooth, so it is computed at 1x. Doing the layer
    maths at 4x as well cost ~200ms a render; at 1x it is a few ms.
    """

    def __init__(self, w: int, bg, line):
        import numpy as np
        self.np = np
        self.w, self.h = w, HEIGHT
        self.img = np.empty((self.h, self.w, 3), dtype=np.float32)
        self.img[:] = bg
        self.img[TAB_H, :] = line               # the line every tab stands on
        self.ys = np.arange(self.h, dtype=np.float32) + 0.5
        self.region(0, self.w)

    def region(self, c0: int, c1: int) -> None:
        """Confine every layer to columns c0..c1: a tab touches only its own
        stretch of the strip."""
        c0, c1 = max(0, int(c0)), min(self.w, int(c1))
        self.c0, self.c1 = c0, c1
        self.xs = self.np.arange(c0, c1, dtype=self.np.float32) + 0.5
        self.view = self.img[:, c0:c1]

    # ── masks (supersampled) ─────────────────────────────────────────────────
    def _ss_image(self):
        from PIL import Image, ImageDraw
        m = Image.new("L", ((self.c1 - self.c0) * SS, self.h * SS), 0)
        return m, ImageDraw.Draw(m)

    def _scaled(self, pts):
        # The -0.5 puts an edge at y=41 exactly between pixel rows, so a tab
        # stops ON the line rather than a fraction of a pixel into it.
        return [((x - self.c0) * SS - 0.5, y * SS - 0.5) for x, y in pts]

    def _down(self, m):
        from PIL import Image
        small = m.resize((self.c1 - self.c0, self.h), Image.BOX)
        return self.np.asarray(small, dtype=self.np.float32) / 255.0

    def masks(self, g: TabGeom):
        """(shape, rim) coverage. The rim is a 2px stroke centred on the
        outline and clipped to the shape, i.e. the 1px inside the edge, as the
        CRM's clip-path draws it. The clip happens at SS, before the
        downscale, or the edge pixels would be counted twice."""
        from PIL import ImageChops
        shape, d = self._ss_image()
        d.polygon(self._scaled(g.shape), fill=255)
        stroke, d = self._ss_image()
        d.line(self._scaled(g.rim), fill=255, width=2 * SS, joint="curve")
        rim = ImageChops.multiply(stroke, shape)
        return self._down(shape), self._down(rim)

    # ── layers ───────────────────────────────────────────────────────────────
    def over(self, colour, alpha):
        """Source-over one layer onto the current region (float32 throughout:
        np.interp hands back float64, which doubles the cost of every op)."""
        np = self.np
        a = np.clip(np.asarray(alpha, dtype=np.float32), 0.0, 1.0)
        a = np.broadcast_to(a, self.view.shape[:2])[..., None]
        col = np.asarray(colour, dtype=np.float32)
        self.view *= (1.0 - a)
        self.view += col * a

    def stops(self, t, stops):
        return self.np.interp(t, [s[0] for s in stops],
                              [s[1] for s in stops]).astype(self.np.float32)

    def vgrad(self, y0: float, y1: float):
        """0 at y0 to 1 at y1, per row, broadcast across the width."""
        t = (self.ys - y0) / max(y1 - y0, 1e-6)
        return self.np.clip(t, 0.0, 1.0)[:, None]

    def ellipse_t(self, cx, cy, rx, ry):
        dx = (self.xs[None, :] - cx) / rx
        dy = (self.ys[:, None] - cy) / ry
        return self.np.sqrt(dx * dx + dy * dy)

    def linear_t(self, x0, y0, dx, dy, length):
        """Distance along (dx, dy) from (x0, y0), as a fraction of length."""
        t = ((self.xs[None, :] - x0) * dx + (self.ys[:, None] - y0) * dy) / length
        return self.np.clip(t, 0.0, 1.0)

    def underline(self, g: TabGeom, scale: float):
        """The lit line under a tab, and its glow underneath."""
        from PIL import Image, ImageFilter
        np = self.np
        feet_l, feet_r = g.feet
        spill = EDGE["spill"]
        line_x = feet_l - spill
        line_w = feet_r - feet_l + 2 * spill
        stops = [(0.0, 0.0)] + [
            ((spill + rel * (feet_r - feet_l)) / line_w, a * scale)
            for rel, a in EDGE["underline"]] + [(1.0, 0.0)]
        row = self.stops(np.clip((self.xs - line_x) / line_w, 0.0, 1.0), stops)
        row[(self.xs < line_x) | (self.xs > line_x + line_w)] = 0.0
        # The glow is the line half a px taller each way, blurred, and shown
        # under the line only, so the tab's fill above it stays clean.
        band = np.zeros(self.view.shape[:2], dtype=np.float32)
        band[TAB_H - 1] = row * 0.5
        band[TAB_H] = row
        band[TAB_H + 1] = row * 0.5
        blurred = Image.fromarray((band * 255 + 0.5).astype(np.uint8), "L").filter(
            ImageFilter.GaussianBlur(EDGE["bloom"]))
        glow = np.asarray(blurred, dtype=np.float32) / 255.0
        glow[:TAB_H] = 0.0
        self.over(ORANGE, glow)
        crisp = np.zeros(self.view.shape[:2], dtype=np.float32)
        crisp[TAB_H] = row
        self.over(ORANGE, crisp)

    def icon(self, glyph: str, colour: str, x: float, y: float):
        """A glyph from ui_render, drawn the way every other icon in the app is
        (supersampled, LANCZOS down) and set on whole pixels so it stays crisp."""
        from PIL import Image, ImageDraw
        import ui_render
        np = self.np
        im = Image.new("RGBA", (ICON * SS, ICON * SS), (0, 0, 0, 0))
        try:
            ui_render._glyph_paint(ImageDraw.Draw(im), SS, glyph, ICON, colour)
        except ValueError:
            return
        a = np.asarray(im.resize((ICON, ICON), Image.LANCZOS),
                       dtype=np.float32)[..., 3] / 255.0
        px, py = int(round(x)) - self.c0, int(round(y))
        full = np.zeros(self.view.shape[:2], dtype=np.float32)
        y0, x0 = max(py, 0), max(px, 0)
        y1, x1 = min(py + ICON, full.shape[0]), min(px + ICON, full.shape[1])
        if y1 <= y0 or x1 <= x0:
            return
        full[y0:y1, x0:x1] = a[y0 - py:y1 - py, x0 - px:x1 - px]
        self.over(_hex(colour), full)

    def tab(self, g: TabGeom, *, hovered: bool, under_left: bool,
            right_active: bool):
        reach = EDGE["spill"] + 3 * EDGE["bloom"] + 2
        self.region(math.floor(g.feet[0] - reach), math.ceil(g.feet[1] + reach))
        shape, rim = self.masks(g)
        if g.active:
            self.over(ACT_FILL, shape)
            self.over(ORANGE, shape * GLOW["tint"])
            self.over(ORANGE, shape * self.stops(self.ellipse_t(
                g.x0 + GLOW["cx"], GLOW["cy"], GLOW["rx"], GLOW["ry"]),
                GLOW["stops"]))
            pool = GLOW["pool"]
            self.over(ORANGE, shape * self.stops(self.ellipse_t(
                g.x0 + pool["cx"], g.y_base, pool["rx"], pool["ry"]),
                pool["stops"]))
            # Rim light: fading down the sides, a sheen towards the far top
            # corner, and brightest round the lit corner.
            self.over(ORANGE, rim * self.stops(
                self.vgrad(g.y_top, g.y_base), EDGE["rim"]))
            self.over(ACT_RIM, rim * self.stops(self.ellipse_t(
                g.x0 + g.w - 3 * REM, g.y_top, 3.5 * REM, 0.9 * REM),
                ((0, 0.12), (1, 0))))
            self.over(ORANGE_400, rim * self.stops(self.ellipse_t(
                g.x_left(g.y_top), g.y_top, 1.25 * REM, GLOW["rim_reach"]),
                ((0, 0.95), (0.3, 0.7), (0.6, 0.35), (1, 0))))
            self.underline(g, 1.0)
            return
        np = self.np
        t = self.vgrad(DROP, g.y_base)[..., None]
        fill = (np.asarray(IN_TOP, dtype=np.float32) * (1 - t)
                + np.asarray(IN_BOT, dtype=np.float32) * t)
        self.over(fill, shape)
        if hovered:
            self.over(FOREGROUND, shape * 0.05)
        if under_left:
            length, stops = SHADE["right"]
            self.over(BLACK, shape * self.stops(self.linear_t(
                g.x0 + OVERLAP, g.y_mid, _COS, -_SIN, length), stops))
        if right_active:
            length, stops = SHADE["left"]
            self.over(BLACK, shape * self.stops(self.linear_t(
                g.x0 + g.w - OVERLAP, g.y_mid, -_COS, -_SIN, length), stops))
        span = max(g.y_base - DROP, 1e-6)
        self.over(WHITE, rim * self.stops(self.vgrad(DROP, g.y_base), (
            (0, 0.09), (min(0.3, TOP_R * 1.2 / span), 0.07), (0.35, 0.025),
            (1, 0.01))))
        if hovered:
            self.over(ORANGE, rim * self.stops(
                self.vgrad(g.y_top, g.y_base), EDGE["hover_rim"]))
            self.underline(g, EDGE["hover_underline"])

    def image(self):
        from PIL import Image
        arr = self.np.clip(self.img + 0.5, 0, 255).astype(self.np.uint8)
        return Image.fromarray(arr, "RGB")


# ── Widget ───────────────────────────────────────────────────────────────────

class BookmarkTabs(tk.Canvas):
    """The strip. `tabs` is a sequence of (id, label, glyph); `on_select(id)`
    fires on a click. `set_active(id)` lights a tab, and None lights none (a
    page with no tab of its own, e.g. Settings)."""

    def __init__(self, parent, tabs, on_select, bg: str = "#0d0d0d",
                 line: str = "#2d2d2d"):
        super().__init__(parent, height=HEIGHT, bg=bg, highlightthickness=0,
                         bd=0, takefocus=0)
        self._tabs = list(tabs)
        self._ids = [t[0] for t in self._tabs]
        self._glyphs = {t[0]: t[2] for t in self._tabs}
        self._on_select = on_select
        self._bg, self._line = _hex(bg), _hex(line)
        self._active = None
        self._hovered = None
        self._width = 0
        self._boxes: dict = {}          # id -> (x0, w)
        self._geoms: dict = {}          # id -> TabGeom for the current state
        self._icons_on = True
        self._icon_x: dict = {}
        self._label_x: dict = {}
        self._cache: dict = {}
        self._photo = None              # the image on screen, held here too
        self._warm_job = None
        self._font_on = tkfont.Font(root=self, family="Segoe UI Semibold",
                                    size=-LABEL_PX)
        self._font_off = tkfont.Font(root=self, family="Segoe UI",
                                     size=-LABEL_PX)
        self._img_item = self.create_image(0, 0, anchor="nw")
        self._text_items = {
            tid: self.create_text(0, 0, text=label, anchor="w",
                                  font=self._font_off, fill=INK_IDLE)
            for tid, label, _g in self._tabs}
        self.bind("<Configure>", self._on_configure)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    # ── Public ───────────────────────────────────────────────────────────────
    @property
    def active(self):
        return self._active

    def set_active(self, tab_id) -> None:
        if tab_id not in self._text_items:
            tab_id = None
        if tab_id == self._active:
            return
        self._active = tab_id
        self._geoms = self._geoms_for(tab_id)
        self._redraw()

    # ── Layout ───────────────────────────────────────────────────────────────
    def _relayout(self) -> None:
        if self._width <= 1:
            return
        label_w = [max(self._font_on.measure(label), self._font_off.measure(label))
                   for _t, label, _g in self._tabs]
        with_icon = [ICON + ICON_GAP + lw for lw in label_w]
        widths, icons, _pad = layout(with_icon, label_w,
                                     self._width - 2 * STRIP_PAD)
        self._icons_on = icons
        self._boxes.clear()
        x = STRIP_PAD
        for tid, bw, lw in zip(self._ids, widths, label_w):
            self._boxes[tid] = (x, bw)
            content = (ICON + ICON_GAP + lw) if icons else lw
            left = x + (bw - content) / 2       # icon + label, centred
            self._icon_x[tid] = left
            self._label_x[tid] = left + (ICON + ICON_GAP if icons else 0)
            x += bw - OVERLAP
        self._geoms = self._geoms_for(self._active)

    def _geoms_for(self, active):
        return {tid: TabGeom(x0, w, tid == active)
                for tid, (x0, w) in self._boxes.items()}

    def _z_order(self, active, hovered):
        """Paint order, lowest first: each tab stacks over the one to its
        right, a hovered tab lifts over its neighbours, and the current tab
        sits over everything."""
        def z(item):
            i, tid = item
            if tid == active:
                return 1000
            if tid == hovered:
                return 900
            return 100 - i
        return [tid for _i, tid in sorted(enumerate(self._ids), key=z)]

    # ── Drawing ──────────────────────────────────────────────────────────────
    def _render(self, active, hovered):
        p = _Painter(self._width, self._bg, self._line)
        geoms = self._geoms_for(active)
        icon_y = (TAB_H + 1) / 2 - ICON / 2
        for tid in self._z_order(active, hovered):
            i = self._ids.index(tid)
            is_active = tid == active
            is_hovered = tid == hovered and not is_active
            p.tab(geoms[tid], hovered=is_hovered,
                  under_left=i > 0 and not is_active,
                  right_active=i + 1 < len(self._ids)
                  and self._ids[i + 1] == active)
            if self._icons_on:
                colour = (ICON_ACTIVE if is_active
                          else ICON_HOVER if is_hovered else ICON_IDLE)
                p.icon(self._glyphs[tid], colour, self._icon_x[tid], icon_y)
        return p.image()

    def _photo_for(self, active, hovered):
        if hovered == active:
            hovered = None              # hovering the current tab changes nothing
        key = (self._width, active, hovered, self._icons_on)
        photo = self._cache.get(key)
        if photo is None:
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(self._render(active, hovered),
                                           master=self)
            except Exception as exc:          # never take the dashboard down
                print(f"[Tabs] render failed (non-fatal): {exc}")
                return None
            if len(self._cache) >= _CACHE_MAX:
                self._cache.clear()           # the one on screen stays in _photo
            self._cache[key] = photo
        return photo

    def _redraw(self) -> None:
        if self._width <= 1 or not self._boxes:
            return
        photo = self._photo_for(self._active, self._hovered)
        try:
            if photo is not None:
                self._photo = photo
                self.itemconfigure(self._img_item, image=photo)
            y = (TAB_H + 1) / 2
            for tid, item in self._text_items.items():
                is_active = tid == self._active
                ink = INK_ACTIVE if is_active else (
                    INK_HOVER if tid == self._hovered else INK_IDLE)
                self.coords(item, self._label_x.get(tid, 0), y)
                self.itemconfigure(item, fill=ink, font=(
                    self._font_on if is_active else self._font_off))
        except tk.TclError:
            return
        self._schedule_warm()

    def _schedule_warm(self) -> None:
        """Render the hover states for the current tab while the app is idle,
        one per idle slot, so the first hover over each tab is an image swap
        rather than a render."""
        if self._warm_job is None:
            try:
                self._warm_job = self.after(120, self._warm)
            except tk.TclError:
                pass

    def _warm(self) -> None:
        self._warm_job = None
        for tid in [None] + self._ids:
            key = (self._width, self._active, None if tid == self._active else tid,
                   self._icons_on)
            if key not in self._cache:
                if self._photo_for(self._active, tid) is not None:
                    self._schedule_warm()
                return

    # ── Events ───────────────────────────────────────────────────────────────
    def _hit(self, x: float, y: float):
        for tid in reversed(self._z_order(self._active, self._hovered)):
            g = self._geoms.get(tid)
            if g is not None and g.contains(x, y):
                return tid
        return None

    def _on_configure(self, event) -> None:
        if event.width == self._width:
            return
        self._width = event.width
        self._relayout()
        self._redraw()

    def _on_motion(self, event) -> None:
        tid = self._hit(event.x, event.y)
        try:
            self.configure(cursor="hand2" if tid else "")
        except tk.TclError:
            pass
        if tid != self._hovered:
            self._hovered = tid
            self._redraw()

    def _on_leave(self, _event=None) -> None:
        if self._hovered is not None:
            self._hovered = None
            self._redraw()

    def _on_click(self, event) -> None:
        tid = self._hit(event.x, event.y)
        if tid is not None and self._on_select is not None:
            self._on_select(tid)
