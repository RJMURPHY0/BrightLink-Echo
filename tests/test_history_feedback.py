"""History → flag → "Report to improve model".

Pins the parts that are easy to break quietly: the flag's click zone must not
steal the copy or bin clicks; the report must carry the correction pair, the
engine that produced the text and its link to the dictation; the recording
leaves the machine ONLY when the user left "Include the recording" ticked;
an audio upload failure still files the report; and the dialog is a placed
card, never another Toplevel.
"""

import inspect
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import supabase_client  # noqa: E402
from supabase_client import SupabaseLogger  # noqa: E402
from app_window import AppWindow  # noqa: E402

_SHARED_ROOT = None


def tearDownModule():
    global _SHARED_ROOT
    try:
        import ui_render
        ui_render.clear_cache()
    except Exception:
        pass
    if _SHARED_ROOT is not None:
        try:
            _SHARED_ROOT.destroy()
        except Exception:
            pass
        _SHARED_ROOT = None


def _shared_root():
    """One Tk root for the module (see test_impact_panel for why)."""
    global _SHARED_ROOT
    import tkinter as tk
    if _SHARED_ROOT is not None and _SHARED_ROOT.winfo_exists():
        return _SHARED_ROOT
    try:
        _SHARED_ROOT = tk.Tk()
    except Exception as e:                          # no window station (CI)
        raise unittest.SkipTest(f"Tk unavailable: {e}")
    _SHARED_ROOT.geometry("440x620")
    return _SHARED_ROOT


ITEM = {
    "transcribed_text": "push it to maine",
    "created_at": "2026-09-25T09:00:00+00:00",
    "app_name": "Claude",
    "app_exe": "claude.exe",
}


# ── Supabase side ────────────────────────────────────────────────────────────

class _FakeTable:
    def __init__(self, sink):
        self.sink = sink

    def insert(self, payload, returning=None):
        self.sink["row"] = payload
        self.sink["returning"] = returning
        return self

    def execute(self):
        return None


class _FakeBucket:
    def __init__(self, sink, fail):
        self.sink, self.fail = sink, fail

    def upload(self, path, data, opts):
        if self.fail:
            raise RuntimeError("bucket missing")
        self.sink["upload"] = (path, len(data), opts)


class _FakeClient:
    def __init__(self, fail_upload=False):
        self.sink = {}
        self.storage = types.SimpleNamespace(
            from_=lambda bucket: (self.sink.__setitem__("bucket", bucket)
                                  or _FakeBucket(self.sink, fail_upload)))

    def table(self, name):
        self.sink["table"] = name
        return _FakeTable(self.sink)


def _logger(client, user="user-1"):
    log = SupabaseLogger("https://x.supabase.co", "anon")
    log._client = client
    log._user_id = user
    return log


def _send(log, report, wav=None):
    done = []
    with mock.patch.object(supabase_client.threading, "Thread") as T:
        log.send_feedback(report, wav_path=wav, on_done=done.append)
        target = T.call_args.kwargs["target"]
    target()                                        # run the worker inline
    return done


class SendFeedbackTests(unittest.TestCase):
    def setUp(self):
        fd, self.wav = tempfile.mkstemp(suffix=".wav")
        os.write(fd, b"RIFF" + b"\0" * 64)
        os.close(fd)
        self.addCleanup(os.remove, self.wav)
        self.report = {"transcribed_text": "a", "expected_text": "b",
                       "refined_text": None, "engine": ""}

    def test_row_goes_to_echo_feedback_as_the_user(self):
        c = _FakeClient()
        self.assertEqual(_send(_logger(c), self.report), [True])
        self.assertEqual(c.sink["table"], "echo_feedback")
        self.assertEqual(c.sink["row"]["user_id"], "user-1")
        # Empty values are dropped, not sent as "".
        self.assertNotIn("refined_text", c.sink["row"])
        self.assertNotIn("engine", c.sink["row"])
        # Only the super admin can SELECT the table, so asking for the row
        # back would make RLS refuse every other user's report.
        self.assertEqual(getattr(c.sink["returning"], "value", None),
                         "minimal")

    def test_no_wav_means_no_upload(self):
        c = _FakeClient()
        _send(_logger(c), self.report, wav=None)
        self.assertNotIn("upload", c.sink)
        self.assertNotIn("audio_path", c.sink["row"])

    def test_wav_goes_into_the_users_own_folder(self):
        c = _FakeClient()
        _send(_logger(c), self.report, wav=self.wav)
        path, size, opts = c.sink["upload"]
        self.assertEqual(c.sink["bucket"], "echo-feedback-audio")
        self.assertTrue(path.startswith("user-1/") and path.endswith(".wav"))
        self.assertEqual(opts["content-type"], "audio/wav")
        self.assertEqual(c.sink["row"]["audio_path"], path)

    def test_upload_failure_still_files_the_report(self):
        c = _FakeClient(fail_upload=True)
        self.assertEqual(_send(_logger(c), self.report, wav=self.wav), [True])
        self.assertIn("row", c.sink)
        self.assertNotIn("audio_path", c.sink["row"])

    def test_signed_out_sends_nothing(self):
        c = _FakeClient()
        log = _logger(c, user="local")
        self.assertFalse(log.can_send_feedback)
        self.assertEqual(_send(log, self.report, wav=self.wav), [False])
        self.assertEqual(c.sink, {})


class LocalMetaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = os.path.join(self.tmp.name, "history.json")
        p = mock.patch.object(supabase_client, "_local_history_path",
                              lambda: path)
        p.start()
        self.addCleanup(p.stop)
        self.path = path

    def test_engine_is_stamped_locally_and_read_back(self):
        log = SupabaseLogger("", "")                # disabled: local only
        meta = {"engine": "parakeet", "model": "parakeet-tdt-0.6b-v2",
                "language": "en", "app_version": "1.6.95", "junk": "x"}
        log.log_transcription("hello", created_at="T1", meta=meta)
        with open(self.path, encoding="utf-8") as f:
            rec = json.load(f)[0]
        self.assertEqual(rec["engine"], "parakeet")
        self.assertNotIn("junk", rec)
        self.assertEqual(log.local_meta("T1")["model"],
                         "parakeet-tdt-0.6b-v2")
        self.assertEqual(log.local_meta("nope"), {})

    def test_remote_payload_is_unchanged(self):
        log = SupabaseLogger("https://x.supabase.co", "anon")
        sent = []
        log._run = sent.append
        log.log_transcription("hello", created_at="T2",
                              meta={"engine": "whisper"})
        self.assertNotIn("engine", sent[0])


# ── The window side ──────────────────────────────────────────────────────────

class _Canvas:
    def __init__(self, width):
        self.width = width

    def winfo_width(self):
        return self.width


class FlagZoneTests(unittest.TestCase):
    def setUp(self):
        self.w = AppWindow.__new__(AppWindow)
        self.w._hist_cv = _Canvas(400)
        self.w._hist_layout = [{"key": "k0", "y0": 0}]
        self.w._hist_hover_index = 0
        self.w._hist_confirm_key = None

    def test_the_flag_sits_between_the_text_and_the_bin(self):
        far, near = AppWindow._HIST_FLAG_ZONE
        self.assertTrue(self.w._on_history_flag(400 - AppWindow._HIST_FLAG_CX,
                                                20, 0))
        # Never overlaps the bin (w-66 … w-34) or copy (w-34 …) zones.
        self.assertLessEqual(near, 66)
        self.assertFalse(self.w._on_history_flag(400 - 50, 20, 0))
        self.assertFalse(self.w._on_history_flag(400 - 20, 20, 0))

    def test_only_the_hovered_header_counts(self):
        x = 400 - AppWindow._HIST_FLAG_CX
        self.assertFalse(self.w._on_history_flag(x, 60, 0), "below header")
        self.w._hist_hover_index = None
        self.assertFalse(self.w._on_history_flag(x, 20, 0))

    def test_hidden_while_the_delete_confirm_shows(self):
        self.w._hist_confirm_key = "k0"
        self.assertFalse(self.w._on_history_flag(
            400 - AppWindow._HIST_FLAG_CX, 20, 0))

    def test_preview_text_stops_short_of_the_flag(self):
        src = inspect.getsource(AppWindow._draw_history_canvas_row)
        self.assertIn("(width - 164)", src)
        # Text starts at x=57, so it ends at width-107: clear of the flag's
        # left edge (width - CX - 8).
        self.assertGreater(57 + 164 - 57, AppWindow._HIST_FLAG_CX + 8)


class ReportPayloadTests(unittest.TestCase):
    def _window(self, local_meta):
        w = AppWindow.__new__(AppWindow)
        w._db = types.SimpleNamespace(local_meta=lambda ca: dict(local_meta))
        w._engine_meta = lambda: {"engine": "whisper", "model": "small.en",
                                  "language": "en", "app_version": "1.6.95"}
        w._auth = types.SimpleNamespace(user_email="ryan@example.com")
        w._wave_info = lambda p: (3.456, [])
        return w

    def test_recorded_engine_wins_and_is_marked_recorded(self):
        w = self._window({"engine": "parakeet", "model": "p-v2",
                          "app_version": "1.6.94"})
        r = w._feedback_report(ITEM, "push it to main", "x.wav")
        self.assertEqual(r["transcribed_text"], "push it to maine")
        self.assertEqual(r["expected_text"], "push it to main")
        self.assertEqual(r["transcription_created_at"], ITEM["created_at"])
        self.assertEqual((r["engine"], r["model"], r["app_version"]),
                         ("parakeet", "p-v2", "1.6.94"))
        self.assertEqual(r["engine_source"], "recorded")
        self.assertEqual(r["audio_seconds"], 3.46)
        self.assertEqual(r["user_email"], "ryan@example.com")

    def test_old_rows_fall_back_to_the_configured_engine(self):
        r = self._window({})._feedback_report(ITEM, "x", None)
        self.assertEqual(r["engine"], "whisper")
        self.assertEqual(r["engine_source"], "config")
        self.assertIsNone(r["audio_seconds"])


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = _shared_root()

    def setUp(self):
        import tkinter as tk
        from app_window import C
        fd, self.wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        self.addCleanup(os.remove, self.wav)
        self.sent = []
        w = AppWindow.__new__(AppWindow)
        w._root = self.root
        w._dash_frame = tk.Frame(self.root, bg=C["bg"])
        w._dash_frame.pack(fill="both", expand=True)
        self.addCleanup(w._dash_frame.destroy)
        w._atomic_ui = lambda fn: fn()
        w._audio_path_for = lambda item: self.wav
        w._wave_info = lambda p: (1.0, [])
        w._engine_meta = None
        w._auth = types.SimpleNamespace(user_email="")
        w._db = types.SimpleNamespace(
            can_send_feedback=True, local_meta=lambda ca: {},
            send_feedback=lambda report, wav_path=None, on_done=None:
                self.sent.append((report, wav_path)))
        self.w = w
        self.addCleanup(w._close_feedback)

    def _type(self, text):
        e = self.w._fb["entry"]
        e.delete("1.0", "end")
        e.insert("1.0", text)
        self.w._sync_feedback_send()

    def test_send_needs_a_real_correction(self):
        self.w._open_feedback(ITEM)
        self.w._send_feedback()                     # unchanged: inert
        self.assertEqual(self.sent, [])
        self.assertIsNone(self.w._fb["send"]._command)
        self._type("push it to main")
        self.assertIsNotNone(self.w._fb["send"]._command)

    def test_recording_is_attached_when_ticked(self):
        self.w._open_feedback(ITEM)
        self.assertTrue(self.w._fb["include"])
        self._type("push it to main")
        self.w._send_feedback()
        report, wav = self.sent[0]
        self.assertEqual(wav, self.wav)
        self.assertEqual(report["expected_text"], "push it to main")

    def test_unticking_keeps_the_recording_on_the_machine(self):
        self.w._open_feedback(ITEM)
        self.w._toggle_feedback_audio()
        self._type("push it to main")
        self.w._send_feedback()
        self.assertIsNone(self.sent[0][1])

    def test_no_tickbox_when_the_recording_is_not_here(self):
        self.w._audio_path_for = lambda item: None
        self.w._open_feedback(ITEM)
        self.assertNotIn("tick", self.w._fb)
        self._type("x y")
        self.w._send_feedback()
        self.assertIsNone(self.sent[0][1])

    def test_failure_keeps_what_was_typed(self):
        self.w._open_feedback(ITEM)
        self._type("push it to main")
        st = self.w._fb
        self.w._send_feedback()
        self.w._feedback_sent(st, False)
        self.assertIs(self.w._fb, st)
        self.assertEqual(self.w._feedback_text(), "push it to main")
        self.assertIn("Try again", st["status"].cget("text"))

    # ── listening back ───────────────────────────────────────────────────

    def _fake_winsound(self):
        calls = []
        fake = types.SimpleNamespace(
            SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4, SND_PURGE=8,
            PlaySound=lambda path, flags: calls.append(path))
        p = mock.patch.dict(sys.modules, {"winsound": fake})
        p.start()
        self.addCleanup(p.stop)
        return calls

    def test_the_recording_can_be_played_from_the_dialog(self):
        calls = self._fake_winsound()
        self.w._wave_info = lambda p: (2.0, [0.2, 0.9, 0.4, 0.1])
        self.w._open_feedback(ITEM)
        self.root.update_idletasks()
        st = self.w._fb
        self.assertIn("player", st)
        self.assertTrue(st["bars"], "no waveform drawn")
        self.w._toggle_feedback_play()
        self.assertTrue(st["playing"])
        self.assertEqual(calls, [self.wav])
        self.w._toggle_feedback_play()               # same button stops it
        self.assertFalse(st["playing"])
        self.assertEqual(calls[-1], None)            # SND_PURGE

    def test_the_player_sits_under_what_echo_heard(self):
        self.w._open_feedback(ITEM)
        kids = self.w._fb["player"].master.pack_slaves()
        i = kids.index(self.w._fb["player"])
        self.assertIsInstance(kids[i - 1], __import__("tkinter").Text)
        self.assertEqual(str(kids[i - 1].cget("state")), "disabled")

    def test_closing_the_dialog_stops_playback(self):
        calls = self._fake_winsound()
        self.w._open_feedback(ITEM)
        st = self.w._fb
        self.w._toggle_feedback_play()
        self.w._close_feedback()
        self.assertFalse(st["playing"])
        self.assertIsNone(st["play_job"])
        self.assertEqual(calls[-1], None)

    def test_playback_ends_on_its_own(self):
        self._fake_winsound()
        self.w._wave_info = lambda p: (0.2, [0.5] * 10)
        self.w._open_feedback(ITEM)
        self.root.update_idletasks()
        st = self.w._fb
        self.w._toggle_feedback_play()
        st["play_started"] -= 1.0                    # past the end
        self.w._tick_feedback_play()
        self.assertFalse(st["playing"])

    def test_no_player_without_the_recording(self):
        self.w._audio_path_for = lambda item: None
        self.w._open_feedback(ITEM)
        self.assertNotIn("player", self.w._fb)

    def test_the_dialog_is_placed_not_a_toplevel(self):
        src = inspect.getsource(AppWindow._open_feedback)
        self.assertNotIn("Toplevel", src)
        self.assertIn("place(in_=self._dash_frame", src)


class GlyphTests(unittest.TestCase):
    def test_flag_glyph_exists(self):
        root = _shared_root()
        import ui_render
        self.assertIsNotNone(ui_render.icon_glyph(root, "flag", 16,
                                                  "#8c8c8c", bg="#1a1a1a"))


if __name__ == "__main__":
    unittest.main()
