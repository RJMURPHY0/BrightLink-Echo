"""Prove every page change in the dashboard is ONE frame on the real screen.

The tab glitch (old page morphing into the new one) only shows on a real
screen: Tk paints straight to it, so no unit test can see it. This runs the
real AppWindow with a fake signed-in account, clicks through every page
change (each tab twice, the gear, the range picker, an impact breakdown,
sign-out), records the window from the screen while it does, and fails if
any click shows more than one change, or if the background page warm-up
shows anything at all.

Run it before releasing any change to app_window.py, bookmark_tabs.py,
ui_render.py or snapshot_cover.py. A test window appears on the screen for
about 30 seconds; leave it alone while it runs (a click on it, or on its
taskbar button, spoils the recording):

    venv\\Scripts\\python.exe tools\\page_change_check.py [out_dir]

Exit 0 = every change was one frame. Exit 1 = a glitch (the report names the
action and keeps the frames in out_dir). Exit 2 = the run itself failed.
"""

import os
import subprocess
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import tkinter as tk  # noqa: E402

# The shell may start us hidden: a throwaway window eats that first show.
_d = tk.Tk()
_d.geometry("1x1+0+0")
_d.update()
_d.destroy()

import brand  # noqa: E402
import config as config_mod  # noqa: E402
import app_window as aw  # noqa: E402

OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else tempfile.mkdtemp(
    prefix="echo_page_check_", dir=os.path.join(REPO, os.pardir))
os.makedirs(OUT, exist_ok=True)
# Pixel change (mean abs, 0-255, half-size greyscale) that counts as a frame.
_CHANGE = 0.05
# How long after an action its frames are still counted as its own.
_SETTLE_S = 1.2


class _FakeAuth:
    def __init__(self):
        self.is_authenticated = False
        self.user_email = None
        self.user_id = None
        self.access_token = None
        self.last_email = "check@example.com"
        self._user = None
        self._client = None
        self._listener = None

    def has_saved_session(self):
        return False

    def set_restore_listener(self, fn):
        self._listener = fn

    def note(self, *_a, **_k):
        pass

    def sign_in_now(self):
        self.is_authenticated = True
        self.user_email = "check@example.com"
        self.user_id = "00000000-0000-0000-0000-000000000000"

    def _get_client(self):
        return None


actions = []          # (name, perf_counter at start)
warm = []             # (start, end)


def main() -> int:
    cfg = config_mod.Config()
    cfg.save = lambda *a, **k: None
    cfg.save_async = lambda *a, **k: None
    auth = _FakeAuth()
    # The warm-up waits for the person to stop using the PC; this run must
    # not depend on whether somebody is typing elsewhere.
    aw._input_idle_ms = lambda: 10 ** 6
    orig_warm = aw.AppWindow._warm_page

    def _timed_warm(self, name):
        t = time.perf_counter()
        orig_warm(self, name)
        warm.append((t, time.perf_counter()))
    aw.AppWindow._warm_page = _timed_warm

    win = aw.AppWindow(auth=auth, on_authenticated=lambda *_a: None,
                       on_sign_out=lambda: None, on_open_config=lambda: None,
                       on_quit=lambda: None, on_hotkey_change=lambda *a: None,
                       config=cfg, db=None, stats=None, hotkey=cfg.hotkey,
                       refine_hotkey=cfg.refine_hotkey, version="check")
    cap = subprocess.Popen(
        [sys.executable, os.path.join(REPO, "tools", "_frame_capture.py"),
         OUT, brand.WINDOW_TITLE])
    failed = []

    def act(name, fn):
        def run():
            actions.append((name, time.perf_counter()))
            fn()
        win._ui_after(0, run)
        time.sleep(_SETTLE_S)

    def driver():
        try:
            if not win.first_paint.wait(60):
                failed.append("window never painted")
                return
            win._ui_after(0, lambda: win._root.attributes("-topmost", True))
            time.sleep(1.0)
            auth.sign_in_now()
            win._ui_after(0, win._login_ui._on_success, auth)
            time.sleep(1.5)
            open(os.path.join(OUT, "go.txt"), "w").close()
            # Long enough for every page to warm (one at a time).
            time.sleep(9.0)
            actions.append(("(warm-up done)", time.perf_counter()))
            for name in ("learning", "hotkey", "history", "settings", "home",
                         "learning", "hotkey", "history", "settings", "home"):
                act(name, lambda n=name: win._switch_dash_tab(n))
            act("gear", lambda: win._switch_dash_tab("settings"))
            act("home", lambda: win._switch_dash_tab("home"))
            act("range open", win._impact_range_menu.open)
            act("range close", win._impact_range_menu.close)
            first = next(iter(win._impact_cards))
            act("breakdown open", lambda: win._open_impact_detail(first))
            act("breakdown close", win._close_impact_detail)
            act("sign out", win._switch_to_login)
        finally:
            open(os.path.join(OUT, "stop.txt"), "w").close()
            win._ui_after(300, win._root.quit)

    threading.Thread(target=driver, daemon=True).start()
    win.run()
    try:
        cap.wait(120)
    except subprocess.TimeoutExpired:
        cap.kill()
        failed.append("recorder did not finish")
    if failed:
        print("RUN FAILED:", "; ".join(failed))
        return 2
    return _report(win)


def _report(win) -> int:
    from PIL import Image, ImageChops, ImageStat
    frames = sorted(
        (float(f[7:-4]), f) for f in os.listdir(OUT) if f.startswith("f"))
    if len(frames) < 2:
        print("RUN FAILED: no frames recorded (window hidden or covered?)")
        return 2

    def changes(t0, t1):
        before = [f for t, f in frames if t < t0]
        inside = [f for t, f in frames if t0 <= t < t1]
        if not before:
            return []
        prev = Image.open(os.path.join(OUT, before[-1]))
        out = []
        for f in inside:
            im = Image.open(os.path.join(OUT, f))
            if ImageStat.Stat(ImageChops.difference(im, prev)).mean[0] > _CHANGE:
                out.append(f)
            prev = im
        return out

    bad = 0
    print(f"frames kept in {OUT}")
    start = [t for n, t in actions if n == "(warm-up done)"][0]
    if warm:
        n = len(changes(warm[0][0], start))
        print(f"  page warm-up ({len(warm)} pages): {n} changes on screen")
        if n:
            bad += 1
    timed = [(n, t) for n, t in actions if not n.startswith("(")]
    for i, (name, t) in enumerate(timed):
        end = timed[i + 1][1] if i + 1 < len(timed) else t + _SETTLE_S
        ch = changes(t, end)
        verdict = "ok" if len(ch) <= 1 else "GLITCH"
        shown = (f"{(float(ch[-1][7:-4]) - t) * 1000:.0f}ms"
                 if ch else "no change")
        print(f"  {name:16s} {len(ch)} frame(s)  shown after {shown}  "
              f"{verdict}")
        if len(ch) > 1:
            bad += 1
    print("PASS: every page change is one frame" if not bad
          else f"FAIL: {bad} action(s) drew more than one frame")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
