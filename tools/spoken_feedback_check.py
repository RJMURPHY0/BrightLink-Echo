"""Render and verify the real feedback card using isolated test data, no uploads.

Usage: python tools/spoken_feedback_check.py OUTPUT_DIRECTORY
The microphone transcript and backend are test doubles. All widgets, correction
parsing, report construction and vocabulary learning are production code.
"""
import json
import os
import sys
import threading
import time
from types import SimpleNamespace

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(__file__))
import app_window as aw
import config as config_mod
from learning_shot import _FakeAuth
from spoken_feedback import correction_draft
import vocab_store


def main():
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    cfg = config_mod.Config()
    cfg.save = cfg.save_async = lambda *a, **kw: None
    auth = _FakeAuth()
    aw._input_idle_ms = lambda: 10 ** 6
    win = aw.AppWindow(auth=auth, on_authenticated=lambda *_: None,
                       on_sign_out=lambda: None, on_open_config=lambda: None,
                       on_quit=lambda: None, on_hotkey_change=lambda *a: None,
                       config=cfg, db=None, stats=None, hotkey=cfg.hotkey,
                       refine_hotkey=cfg.refine_hotkey, version="Feedback UI test")
    result = {"test_data": True, "microphone_tested": False,
              "backend_upload_mocked": True}
    sent = []

    def ui(fn):
        box, done = {}, threading.Event()
        def run():
            try:
                box["value"] = fn()
            except Exception as exc:
                box["error"] = exc
            finally:
                done.set()
        win._ui_after(0, run)
        if not done.wait(15):
            raise RuntimeError("UI queue did not respond")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def shot(name):
        from PIL import Image
        (_, _, w, h), raw = aw.snapshot_cover._client_pixels(win._top_hwnd())
        Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1).convert("RGB").save(
            os.path.join(out, name))
        return [w, h]

    def driver():
        try:
            win.first_paint.wait(60)
            auth.sign_in_now()
            ui(lambda: win._login_ui._on_success(auth))
            time.sleep(3)
            item = {"transcribed_text": "Remind me to email UNICEF after lunch.",
                    "created_at": "2099-01-01T10:00:00+00:00"}
            feedback = "Replace UNICEF with Uniserve"
            draft = correction_draft(item["transcribed_text"], feedback,
                                     SimpleNamespace(is_available=False))
            def prepare():
                def send(report, wav_path=None, on_done=None):
                    sent.append({"report": report, "audio": wav_path})
                    on_done(True)
                win._db = SimpleNamespace(_user_id=auth.user_id,
                    can_send_feedback=True, local_meta=lambda _: {},
                    send_feedback=send, push_library=lambda *a, **kw: None)
                win._audio_path_for = lambda _: None
                win._open_spoken_feedback(item, draft, feedback, auth.user_id)
            ui(prepare)
            time.sleep(1)
            result["review_size"] = ui(lambda: shot("echo-feedback-review.png"))
            def narrow():
                win._root.minsize(375, 670)
                win._root.geometry("375x670")
            ui(narrow)
            time.sleep(0.5)
            result["narrow_size"] = ui(lambda: shot("echo-feedback-375.png"))
            assert ui(lambda: win._fb["send"].winfo_rootx() + win._fb["send"].winfo_width()
                      <= win._root.winfo_rootx() + win._root.winfo_width())
            assert ui(lambda: win._feedback_text()) == draft
            assert not ui(lambda: win._fb["include"])
            ui(win._send_feedback)
            time.sleep(0.25)
            ui(lambda: shot("echo-feedback-learned.png"))
            assert sent[0]["report"]["expected_text"] == draft
            assert sent[0]["audio"] is None
            rows = vocab_store.load(cfg, "vocabulary", auth.user_email)
            assert any(r["term"] == "Uniserve" for r in rows), rows
            from text_expansion import apply_vocabulary
            assert apply_vocabulary("Remind me to email UNICEF after lunch.", rows) == draft, rows
            result["future_dictation_correction_verified"] = True
            result["report_pair_verified"] = True
            result["account_vocabulary_learning_verified"] = True
            result["status"] = "PASS"
        except Exception as exc:
            result["status"], result["error"] = "FAIL", repr(exc)
        finally:
            win._ui_after(0, win._root.quit)

    threading.Thread(target=driver, daemon=True).start()
    win.run()
    with open(os.path.join(out, "echo-feedback-check.json"), "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
