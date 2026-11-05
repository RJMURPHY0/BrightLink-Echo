"""A slider with fixed named stops.

Saves on release, keeps a hollow Default dot and a Before bar on the track (the
value when the page opened), each one click from going back. Click a stop or its
name, drag, or use the arrow keys.
"""

import tkinter as tk
from typing import Callable, List, Optional, Sequence

import ui_render


def stop_positions(width: int, count: int, inset: int = 10) -> List[int]:
    """The x of each stop, end stops inset so the thumb is never cut off."""
    if count <= 1:
        return [width // 2] * count
    span = max(1, width - 2 * inset)
    return [inset + round(span * i / (count - 1)) for i in range(count)]


def nearest_stop(x: float, xs: Sequence[int]) -> int:
    return min(range(len(xs)), key=lambda i: abs(xs[i] - x))


class StopSlider(tk.Canvas):
    TRACK_H = 24
    LABEL_Y = 34
    LEGEND_Y = 52
    HEIGHT = 60

    def __init__(self, master, labels: Sequence[str], value: int, default: int,
                 colours: dict, bg: str,
                 on_preview: Optional[Callable[[int], None]] = None,
                 on_commit: Optional[Callable[[int], None]] = None):
        super().__init__(master, height=self.HEIGHT, width=1, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self._labels, self._default = list(labels), default
        self._value = self._before = self._committed = value
        self._c, self._bg = colours, bg
        self._on_preview, self._on_commit = on_preview, on_commit
        self._img = self._m1 = self._m2 = None
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Left>", lambda _e: self._nudge(-1))
        self.bind("<Right>", lambda _e: self._nudge(1))

    @property
    def value(self) -> int:
        return self._value

    def _xs(self) -> List[int]:
        return stop_positions(self.winfo_width(), len(self._labels))

    def _set(self, value: int) -> None:
        if value == self._value:
            return
        self._value = value
        self._draw()
        if self._on_preview:
            self._on_preview(value)

    def _commit(self) -> None:
        if self._value != self._committed:
            self._committed = self._value
            if self._on_commit:
                self._on_commit(self._value)

    def _press(self, e) -> str:
        self.focus_set()
        self._set(nearest_stop(e.x, self._xs()))
        return "break"

    def _drag(self, e) -> None:
        self._set(nearest_stop(e.x, self._xs()))

    def _release(self, e) -> None:
        self._set(nearest_stop(e.x, self._xs()))
        self._commit()

    def _nudge(self, step: int) -> str:
        self._set(max(0, min(self._value + step, len(self._labels) - 1)))
        self._commit()
        return "break"

    def _draw(self) -> None:
        try:
            w = self.winfo_width()
        except tk.TclError:
            return
        if w <= 1:
            return
        xs = self._xs()
        c = self._c
        self.delete("all")
        self._img = ui_render.stop_slider(
            self, w, self.TRACK_H, xs, self._value, self._default, self._before,
            accent=c["accent"], track=c["border"], thumb=c["text"], bg=self._bg)
        if self._img is not None:
            self.create_image(0, 0, image=self._img, anchor="nw")
        last = len(xs) - 1
        for i, (x, label) in enumerate(zip(xs, self._labels)):
            # The end names line up with the track's ends, so neither is clipped.
            anchor, tx = (("w", 0) if i == 0 else ("e", w) if i == last else ("center", x))
            on = i == self._value
            self.create_text(tx, self.LABEL_Y, text=label, anchor=anchor,
                             fill=c["text"] if on else c["subtext"],
                             font=("Segoe UI", 8, "bold") if on else ("Segoe UI", 8))
        self._draw_legend(w)

    def _draw_legend(self, w: int) -> None:
        x = w
        # Going back to the default is the Default dot: no second mark for it.
        if self._before not in (self._value, self._default):
            x = self._legend_item(x, "before", "Before") - 10
        self._legend_item(x, "default", "Default")

    def _legend_item(self, right: int, kind: str, text: str) -> int:
        c = self._c
        t = self.create_text(right, self.LEGEND_Y, text=text, anchor="e",
                             fill=c["subtext"], font=("Segoe UI", 8))
        left = self.bbox(t)[0]
        photo = ui_render.slider_mark(self, kind, accent=c["accent"], bg=self._bg)
        if kind == "default":
            self._m1 = photo
        else:
            self._m2 = photo
        if photo is not None:
            self.create_image(left - 3, self.LEGEND_Y, image=photo, anchor="e")
        return left - 18
