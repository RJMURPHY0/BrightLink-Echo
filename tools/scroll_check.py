"""Prove scrolling a dashboard page never shows a half-drawn frame.

The scroll glitch (cards torn, blank or doubled for a moment while the page
moves) only exists in the pixels, so no unit test can see it. This runs the
real AppWindow with a fake signed-in account, BEHIND every other window (it
covers nobody's work), and on each page that scrolls:

  1. builds a reference picture of the whole page by stepping through it
     slowly and reading the settled window at every stop;
  2. scrolls it the way people do: fast wheel flicks, single notches, a long
     spin to the bottom and back, touchpad deltas and a scrollbar drag;
  3. checks every frame the screen showed is an exact slice of the
     reference. A frame that matches no scroll position is a glitch.

While a page scrolls the screen shows the scroll cover (see
AppWindow._scroll_step), so every picture put on it is kept and checked, and
a scroll step that ran with no cover over the window fails the run.

Run it before releasing any change to scrolling, ScrollPane, snapshot_cover,
app_window.py page layout or ui_render.py:

    venv\\Scripts\\python.exe tools\\scroll_check.py [out_dir]

--surface also records the window's own surface under the cover, for
information (the recorder slows the app, so step times read high then).
--screen records the screen itself with the window on top instead, and judges
that (about a minute; leave the PC alone while it runs).

Exit 0 = every frame shown was a clean slice of its page. Exit 1 = a glitch
(the report names the page and phase and keeps the worst frames, with a diff,
in out_dir). Exit 2 = the run itself failed.
"""

import os
import subprocess
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
os.chdir(REPO)

SCREEN = "--screen" in sys.argv
_ONLY = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--only=")]
SURFACE = "--surface" in sys.argv
_ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = os.path.abspath(_ARGS[0]) if _ARGS else tempfile.mkdtemp(
    prefix="echo_scroll_check_", dir=os.path.join(REPO, os.pardir))
os.makedirs(OUT, exist_ok=True)
# page_change_check reads its own out_dir from argv when imported.
sys.argv = sys.argv[:1] + [OUT]

import page_change_check as pcc  # noqa: E402  (its throwaway window runs first)
import brand  # noqa: E402
import config as config_mod  # noqa: E402
import app_window as aw  # noqa: E402
# Every page that scrolls a ScrollPane of real widgets (History is one
# double-buffered canvas and never uses the cover). The library pages get
# seeded rows (below) so they are long enough to scroll.
PAGES = ("settings", "hotkey", "learning", "vocabulary", "snippets", "phrases")
LIBRARY_PAGES = ("vocabulary", "snippets", "phrases")
# --only=snippets,phrases re-checks some pages (e.g. after another Echo test
# window was over this one: a --screen run sees whatever is on top).
if _ONLY:
    PAGES = tuple(p for p in PAGES if p in _ONLY[0].split(","))


def _seed_rows(kind):
    """Fake entries for a library page: enough rows to scroll well past
    one screen, with real-looking text so a doubled row shows."""
    rows = []
    for i in range(40):
        if kind == "vocabulary":
            rows.append({"id": f"v{i}", "term": f"BrightLink term {i}",
                         "sounds_like": [f"bright link {i}", f"brite link {i}"],
                         "updated_at": f"2026-11-04T10:{i:02d}:00Z"})
        elif kind == "snippets":
            rows.append({"id": f"s{i}", "name": f"Sign-off {i}",
                         "trigger": f"sign off {i}",
                         "body": f"Kind regards, snippet body number {i} "
                                 "with enough words to wrap onto two lines.",
                         "updated_at": f"2026-11-04T10:{i:02d}:00Z"})
        else:
            rows.append({"phrase": f"a phrase you say often number {i}",
                         "count": 40 - i})
    return rows
# A pixel differs if its grey level is off by more than this (anti-aliased
# edges at a fractional offset stay well inside it)...
_PIXEL_TOL = 24
# ...and a frame is a glitch when more than this share of pixels differ from
# the best-matching slice of its page (a blinking caret is ~0.005%).
_FRAME_TOL = 0.002

log = []          # (page, phase, perf_counter, detail)
refs = {}         # page -> [(top, grey array)] read from the settled window
steps = []        # (page, ms) for every scroll step the app ran
shown = []        # (page, perf_counter, (w, h, BGRA), pane box) put on a cover
uncovered = []    # (page, perf_counter) scroll steps with nothing covering


class _Wheel:
    def __init__(self, delta):
        self.delta = delta


def main() -> int:
    cfg = config_mod.Config()
    cfg.save = lambda *a, **k: None
    cfg.save_async = lambda *a, **k: None
    auth = pcc._FakeAuth()
    aw._input_idle_ms = lambda: 10 ** 6
    aw.AppWindow._lib_entries = lambda self, kind: _seed_rows(kind)
    aw.AppWindow._phrase_rows = lambda self: _seed_rows("phrases")
    orig_step = aw.AppWindow._scroll_step
    current = {"page": None}

    orig_refresh = aw.snapshot_cover.SnapshotCover.refresh
    kept = {"ms": 0.0}

    def _kept_refresh(cover, top_hwnd, region=None):
        ok = orig_refresh(cover, top_hwnd, region)
        t = time.perf_counter()
        pic = cover.picture() if ok else None
        page = current["page"]
        if pic is not None and page:
            pane = pane_of(page)
            r = win._root
            box = (pane.winfo_rootx() - r.winfo_rootx(),
                   pane.winfo_rooty() - r.winfo_rooty(),
                   pane.winfo_width(), pane.winfo_height())
            shown.append((page, t, pic, box))
        kept["ms"] += (time.perf_counter() - t) * 1000
        return ok
    aw.snapshot_cover.SnapshotCover.refresh = _kept_refresh

    def _timed_step(self, cv, move):
        t = time.perf_counter()
        kept["ms"] = 0.0
        orig_step(self, cv, move)
        steps.append((current["page"],
                      (time.perf_counter() - t) * 1000 - kept["ms"]))
        held = getattr(self, "_held_cover", None)
        if (isinstance(cv, aw.ScrollPane) and self._scroll_cover is None
                and not (held is not None and not held["done"])):
            uncovered.append((current["page"], t))
    aw.AppWindow._scroll_step = _timed_step
    win = aw.AppWindow(auth=auth, on_authenticated=lambda *_a: None,
                       on_sign_out=lambda: None, on_open_config=lambda: None,
                       on_quit=lambda: None, on_hotkey_change=lambda *a: None,
                       config=cfg, db=None, stats=None, hotkey=cfg.hotkey,
                       refine_hotkey=cfg.refine_hotkey, version="check")
    failed = []
    result = {}

    def on_ui(fn):
        """Run fn on the Tk thread and wait for its result."""
        box, done = {}, threading.Event()

        def run():
            try:
                box["v"] = fn()
            except Exception as exc:
                box["e"] = exc
            done.set()
        win._ui_after(0, run)
        if not done.wait(10):
            raise RuntimeError("UI thread did not answer")
        if "e" in box:
            raise box["e"]
        return box.get("v")

    def pane_of(page):
        if page in LIBRARY_PAGES:
            return win._lib_state(page)["pane"]
        return {"settings": win._settings_cv, "hotkey": win._hk_cv,
                "learning": win._learning_cv}[page]

    def pane_now(page):
        """The pane as the window holds it now, grey, from its own surface."""
        import numpy as np
        from PIL import Image
        r, pane = win._root, pane_of(page)
        shot = aw.snapshot_cover._client_pixels(win._top_hwnd())
        (_x, _y, w, h), raw = shot
        x0 = pane.winfo_rootx() - r.winfo_rootx()
        y0 = pane.winfo_rooty() - r.winfo_rooty()
        im = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1)
        return np.asarray(im.crop((x0, y0, x0 + pane.winfo_width(),
                                   y0 + pane.winfo_height())).convert("L"),
                          dtype=np.int16)

    def mark(page, phase, detail=None):
        log.append((page, phase, time.perf_counter(), detail))

    def wheel(pane, delta, gap_s):
        on_ui(lambda: win._wheel_scroll(pane, _Wheel(delta)))
        time.sleep(gap_s)

    def record_page(page):
        current["page"] = page
        on_ui(lambda: win._switch_dash_tab(page))
        time.sleep(1.5)
        pane = pane_of(page)

        def geom():
            return (pane.winfo_height(), pane._max_top(), pane.winfo_id(),
                    win._top_hwnd())
        th, max_top, pane_hwnd, hwnd = on_ui(geom)
        print(f"  {page}: scrolls {max_top:.0f}px")
        if max_top < 50:
            print(f"  {page}: too short to scroll ({max_top:.0f}px), skipped")
            return
        sub = os.path.join(OUT, page)
        os.makedirs(sub, exist_ok=True)
        cap = None
        if SCREEN or SURFACE:
            with open(os.path.join(sub, "pane.txt"), "w") as fh:
                fh.write(f"{pane_hwnd},{hwnd},{int(SCREEN)}")
            cap = subprocess.Popen(
                [sys.executable, os.path.join(REPO, "tools", "_frame_capture.py"),
                 sub, brand.WINDOW_TITLE])
            time.sleep(0.3)
            open(os.path.join(sub, "go.txt"), "w").close()
            time.sleep(0.5)
        # 1. Reference: slow stops a third of a viewport apart.
        stops = list(range(0, int(max_top), max(th // 3, 40))) + [int(max_top)]
        for top in stops:
            on_ui(lambda t=top: (win._cancel_smooth_scroll(pane),
                                 pane.yview_moveto(t / pane._content_h())))
            time.sleep(0.45)
            refs.setdefault(page, []).append(on_ui(
                lambda: (int(round(pane._top)), pane_now(page))))
        on_ui(lambda: pane.yview_moveto(0.0))
        time.sleep(0.5)
        # 2. Scroll like a person.
        mark(page, "flicks")
        for _ in range(4):
            for _ in range(5):
                wheel(pane, -120, 0.016)
            time.sleep(0.35)
        mark(page, "notches")
        for _ in range(6):
            wheel(pane, 120, 0.15)
        time.sleep(0.3)
        mark(page, "spin")
        for _ in range(40):
            wheel(pane, -120, 0.008)
        time.sleep(0.6)
        for _ in range(40):
            wheel(pane, 120, 0.008)
        time.sleep(0.6)
        mark(page, "touchpad")
        for _ in range(60):
            wheel(pane, -15, 0.008)
        time.sleep(0.5)
        mark(page, "drag")
        for i in range(41):
            on_ui(lambda f=i / 40: win._scrollbar_command(pane, "moveto", f * 0.8))
            time.sleep(0.016)
        time.sleep(0.5)
        mark(page, "end")
        if cap is not None:
            open(os.path.join(sub, "stop.txt"), "w").close()
            try:
                code = cap.wait(120)
            except subprocess.TimeoutExpired:
                cap.kill()
                failed.append(f"{page}: recorder did not finish")
                return
            if code != 0:
                failed.append(f"{page}: recorder failed (exit {code})")
                return
        result[page] = (sub, max_top, th)

    def driver():
        try:
            if not win.first_paint.wait(60):
                failed.append("window never painted")
                return
            time.sleep(1.0)
            auth.sign_in_now()
            win._ui_after(0, win._login_ui._on_success, auth)
            time.sleep(2.0)

            if SCREEN:
                on_ui(lambda: (win._root.attributes("-topmost", True),
                               win._root.lift()))
            else:
                # Behind every other window: DWM keeps drawing it (the
                # recorder reads the window's own surface), nobody's work
                # is covered.
                on_ui(win._root.lower)
            time.sleep(10.0)          # every page warms (one at a time)
            for page in PAGES:
                record_page(page)
        except Exception as exc:
            failed.append(f"driver: {exc!r}")
        finally:
            win._ui_after(300, win._root.quit)

    threading.Thread(target=driver, daemon=True).start()
    win.run()
    if failed:
        print("RUN FAILED:", "; ".join(failed))
        return 2
    if not result:
        print("RUN FAILED: no page was recorded")
        return 2
    return _report(result)


def _frames(sub):
    import numpy as np
    from PIL import Image
    out = []
    for f in sorted(os.listdir(sub)):
        if f.startswith("f") and f.endswith(".png"):
            out.append((float(f[7:-4]), f,
                        np.asarray(Image.open(os.path.join(sub, f)),
                                   dtype=np.int16)))
    return out


def _match(ref, prof, a):
    """(share of pixels off, offset) of the slice of `ref` that `a` matches
    best. Row averages pick the candidates, full pixels decide."""
    import numpy as np
    h = a.shape[0]
    fp = a.mean(axis=1)
    ssd = np.array([np.square(prof[y:y + h] - fp).sum()
                    for y in range(len(prof) - h + 1)])
    best, best_y = 1.0, 0
    for y in np.argsort(ssd)[:8]:
        frac = float((np.abs(ref[y:y + h] - a) > _PIXEL_TOL).mean())
        if frac < best:
            best, best_y = frac, int(y)
    return best, best_y


def _shown_frames(page):
    """The pictures the scroll cover showed on `page`, as (t, name, grey)."""
    import numpy as np
    from PIL import Image
    out = []
    for i, (p, t, (w, h, raw), (x, y, pw, ph)) in enumerate(shown):
        if p != page:
            continue
        im = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1)
        out.append((t, f"cover{i:05d}.png", np.asarray(
            im.crop((x, y, x + pw, y + ph)).convert("L"), dtype=np.int16)))
    return out


def _judge(page, label, frames, ref, prof, phases, sub) -> int:
    """Print one line per phase; returns how many phases showed a glitch."""
    import numpy as np
    from PIL import Image
    bad = 0
    for i, (ph, t0) in enumerate(phases[:-1]):
        t1 = phases[i + 1][1]
        inside = [(tt, f, a) for tt, f, a in frames if t0 <= tt < t1]
        glitches = []
        for _tt, f, a in inside:
            frac, y = _match(ref, prof, a)
            if frac > _FRAME_TOL:
                glitches.append((frac, f, y, a))
        worst = max((g[0] for g in glitches), default=0.0)
        # Every phase scrolls, so no frame at all means nothing was checked.
        verdict = ("NO FRAMES" if not inside
                   else "ok" if not glitches else "GLITCH")
        print(f"  {page:9s} {label:7s} {ph:9s} {len(inside):4d} frames  "
              f"{len(glitches):3d} torn  worst {worst * 100:.2f}%  {verdict}")
        if not inside:
            bad += 1
        for k, (frac, f, y, a) in enumerate(sorted(glitches, reverse=True)[:3]):
            h = a.shape[0]
            diff = (np.abs(ref[y:y + h] - a) > _PIXEL_TOL).astype(np.uint8) * 255
            pair = np.hstack([a.clip(0, 255).astype(np.uint8),
                              ref[y:y + h].astype(np.uint8), diff])
            Image.fromarray(pair).save(
                os.path.join(sub, f"glitch_{label}_{ph}_{k}_{f}"))
        if glitches:
            bad += 1
    return bad


def _report(result) -> int:
    import numpy as np
    bad = 0
    print(f"frames kept in {OUT}")
    for page, (sub, max_top, h) in result.items():
        stops = refs.get(page, [])
        if not stops:
            print(f"  {page}: RUN FAILED, no reference")
            bad += 1
            continue
        h, w = stops[0][1].shape
        ref = np.full((int(max_top) + h, w), -1, dtype=np.int16)
        noise = 0.0
        for top, img in stops:
            region = ref[top:top + h]
            seen = region >= 0
            if seen.any():
                noise = max(noise, float(
                    (np.abs(region[seen] - img[seen]) > _PIXEL_TOL).mean()))
            ref[top:top + h] = img
        if (ref < 0).any():
            print(f"  {page}: RUN FAILED, reference has gaps")
            bad += 1
            continue
        prof = ref.mean(axis=1)
        phases = [(ph, t) for p, ph, t, _d in log if p == page]
        if SCREEN:      # the screen itself is the verdict
            bad += _judge(page, "screen", _frames(sub), ref, prof, phases, sub)
        else:
            # What the screen showed: the cover's pictures...
            bad += _judge(page, "shown", _shown_frames(page), ref, prof,
                          phases, sub)
            # ...and no step may run with the window uncovered.
            n = sum(1 for p, _t in uncovered if p == page)
            print(f"  {page:9s} {n} scroll step(s) ran uncovered  "
                  f"{'ok' if not n else 'GLITCH'}")
            bad += 1 if n else 0
            if SURFACE:     # for information: the surface under the cover
                surf = _frames(sub)
                torn = sum(1 for _t, _f, a in surf if a.shape == (h, w)
                           and _match(ref, prof, a)[0] > _FRAME_TOL)
                print(f"  {page:9s} (under the cover: {torn} of {len(surf)} "
                      f"surface frames half-drawn, never shown)")
        print(f"  {page:9s} reference noise {noise * 100:.3f}%")
        ms = sorted(m for p, m in steps if p == page)
        if ms:
            print(f"  {page:9s} {len(ms)} scroll steps: median "
                  f"{ms[len(ms) // 2]:.1f}ms, 95th {ms[int(len(ms) * .95)]:.1f}ms, "
                  f"slowest {ms[-1]:.1f}ms")
    print("PASS: every scroll frame shown was a clean slice of its page"
          if not bad else f"FAIL: {bad} check(s) showed a half-drawn frame")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
