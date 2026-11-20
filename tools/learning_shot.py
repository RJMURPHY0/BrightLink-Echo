"""Screenshot of the Learning tab's Your Work card from the real AppWindow.

    venv\\Scripts\\python.exe tools\\learning_shot.py out.png [role,role...]

Runs the window with a fake signed-in account BEHIND every other window
(nobody's work is covered), opens Learning, scrolls the card into view and
reads the window's own surface to a PNG.
"""

import os
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import config as config_mod  # noqa: E402
import app_window as aw  # noqa: E402


class _FakeAuth:
    def __init__(self):
        self.is_authenticated = False
        self.user_email = None
        self.user_id = None
        self.access_token = None
        self.last_email = "check@example.com"

    def has_saved_session(self):
        return False

    def set_restore_listener(self, fn):
        pass

    def note(self, *_a, **_k):
        pass

    def sign_in_now(self):
        self.is_authenticated = True
        self.user_email = "check@example.com"
        self.user_id = "00000000-0000-0000-0000-000000000000"

    def _get_client(self):
        return None


def main() -> int:
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "learning.png")
    roles = sys.argv[2].split(",") if len(sys.argv) > 2 else ["software", "sales", "safety"]
    cfg = config_mod.Config()
    cfg.save = lambda *a, **k: None
    cfg.save_async = lambda *a, **k: None
    cfg.work_roles = roles
    cfg.work_description = "Co-founder of a SaaS company, health and safety background"
    auth = _FakeAuth()
    aw._input_idle_ms = lambda: 10 ** 6
    win = aw.AppWindow(auth=auth, on_authenticated=lambda *_a: None,
                       on_sign_out=lambda: None, on_open_config=lambda: None,
                       on_quit=lambda: None, on_hotkey_change=lambda *a: None,
                       config=cfg, db=None, stats=None, hotkey=cfg.hotkey,
                       refine_hotkey=cfg.refine_hotkey, version="shot")
    res = {}

    def on_ui(fn):
        box, done = {}, threading.Event()

        def run():
            try:
                box["v"] = fn()
            except Exception as exc:
                box["e"] = exc
            done.set()
        win._ui_after(0, run)
        done.wait(10)
        if "e" in box:
            raise box["e"]
        return box.get("v")

    def shot():
        from PIL import Image
        (_x, _y, w, h), raw = aw.snapshot_cover._client_pixels(win._top_hwnd())
        Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1).convert("RGB").save(out)
        return (w, h)

    def driver():
        try:
            win.first_paint.wait(60)
            time.sleep(1.0)
            auth.sign_in_now()
            win._ui_after(0, win._login_ui._on_success, auth)
            time.sleep(2.0)
            on_ui(win._root.lower)
            time.sleep(4.0)
            on_ui(lambda: win._switch_dash_tab("learning"))
            time.sleep(1.5)

            def _scroll():
                pane = win._learning_cv
                card = win._work_entry.master.master
                y = card.winfo_rooty() - pane.content.winfo_rooty() - 40
                pane.yview_moveto(max(0, y) / max(1, pane._content_h()))
            on_ui(_scroll)
            time.sleep(1.0)
            res["size"] = on_ui(shot)
        except Exception as exc:
            res["error"] = repr(exc)
        finally:
            win._ui_after(300, win._root.quit)

    threading.Thread(target=driver, daemon=True).start()
    win.run()
    print(res, out)
    return 0 if "size" in res else 2


if __name__ == "__main__":
    sys.exit(main())
