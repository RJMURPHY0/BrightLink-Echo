"""A press must never wait on the tray, the dashboard or the Tk loop, every
press is timed, and the post-insert badge goes on the Enter the user presses
the moment the text lands (2026-10-12).

Before: the hotkey thread repainted the tray icon (a temporary .ico written,
read back and handed to Explorer: 12-22 ms per press on Ryan's laptop, 1.1 s
cold) and handed the dashboard's status label to the Tk loop, which waits until
the loop is free, all before the start cue played. Nothing recorded how long a
press took, and "No speech detected" was only written to a local file.
"""
import os
import sys
import threading
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import popup as popup_mod
from latest_worker import LatestWorker
from popup import FloatingPopup


class LatestWorkerTests(unittest.TestCase):
    def test_submit_returns_while_the_apply_is_still_blocked(self):
        gate = threading.Event()
        applied = []

        def apply(v):
            gate.wait(5)
            applied.append(v)

        w = LatestWorker(apply, "test-worker")
        t = time.perf_counter()
        w.submit("recording")
        self.assertLess(time.perf_counter() - t, 0.5)
        gate.set()
        for _ in range(200):
            if applied:
                break
            time.sleep(0.01)
        self.assertEqual(["recording"], applied)

    def test_the_last_value_submitted_is_the_last_applied(self):
        gate = threading.Event()
        applied = []

        def apply(v):
            gate.wait(5)
            applied.append(v)

        w = LatestWorker(apply, "test-worker")
        for v in ("recording", "processing", "idle"):
            w.submit(v)
        gate.set()
        for _ in range(200):
            if applied and applied[-1] == "idle":
                break
            time.sleep(0.01)
        self.assertEqual("idle", applied[-1])
        self.assertLessEqual(len(applied), 3)

    def test_a_failing_apply_does_not_stop_the_worker(self):
        applied = []

        def apply(v):
            if v == "bad":
                raise RuntimeError("boom")
            applied.append(v)

        w = LatestWorker(apply, "test-worker")
        w.submit("bad")
        time.sleep(0.05)
        w.submit("good")
        for _ in range(200):
            if applied:
                break
            time.sleep(0.01)
        self.assertEqual(["good"], applied)


class TrayOffThePressPathTests(unittest.TestCase):
    def test_update_icon_returns_while_the_repaint_is_slow(self):
        import tray

        gate = threading.Event()

        class _SlowIcon:
            title = ""

            def update_menu(self):
                pass

            @property
            def icon(self):
                return None

            @icon.setter
            def icon(self, _v):
                gate.wait(5)          # the .ico round trip + Explorer

        t = tray.TrayApp()
        t._icon = _SlowIcon()
        start = time.perf_counter()
        t.update_icon("recording")
        self.assertLess(time.perf_counter() - start, 0.5)
        self.assertEqual("recording", t._current_state)
        gate.set()


class CueBeforeIconTests(unittest.TestCase):
    def test_the_start_cue_is_started_before_the_icon_changes(self):
        import feedback

        order = []
        fb = feedback.Feedback.__new__(feedback.Feedback)
        fb.sound_enabled = True
        fb.on_icon_change = lambda s: order.append(("icon", s))

        class _T:
            def __init__(self, target=None, args=(), daemon=None):
                self.args = args

            def start(self):
                order.append(("sound", self.args[0]))

        with mock.patch.object(feedback.threading, "Thread", _T):
            fb.recording_started()
            fb.recording_stopped()
        self.assertEqual([("sound", "start"), ("icon", "recording"),
                          ("sound", "stop"), ("icon", "processing")], order)


class StatusLabelOffThePressPathTests(unittest.TestCase):
    def test_update_status_never_calls_tk_on_the_caller_thread(self):
        import app_window

        gate = threading.Event()
        calls = []

        class _Root:
            def after(self, _ms, fn, *a):
                calls.append(threading.get_ident())
                gate.wait(5)          # the Tk loop is busy

        w = app_window.AppWindow.__new__(app_window.AppWindow)
        w._root = _Root()
        w._status_lbl = mock.Mock()
        w._status_worker = LatestWorker(w._apply_status, "status-label")
        start = time.perf_counter()
        w.update_status("recording")
        self.assertLess(time.perf_counter() - start, 0.5)
        for _ in range(200):
            if calls:
                break
            time.sleep(0.01)
        self.assertTrue(calls)
        self.assertNotEqual(threading.get_ident(), calls[0])
        gate.set()


class PressTimingTests(unittest.TestCase):
    def _app(self):
        import app

        a = app.WhisperFlowApp.__new__(app.WhisperFlowApp)
        a.popup = types.SimpleNamespace(status_shown_at=None)
        a.recorder = types.SimpleNamespace(last_seed_ms=800,
                                           last_recording_seconds=2.5)
        a._log_error_event = mock.Mock()
        return a

    def test_marks_are_ms_from_the_key_and_set_once(self):
        a = self._app()
        a._press_t0 = time.perf_counter() - 0.040
        a._press_marks = {}
        a._press_mark("cue")
        first = a._press_marks["cue"]
        a._press_mark("cue")
        self.assertEqual(first, a._press_marks["cue"])
        self.assertGreaterEqual(first, 40)

    def test_pill_shown_comes_from_the_popup_and_ignores_an_older_press(self):
        a = self._app()
        a._press_t0 = 100.0
        a._press_marks = {"cue": 2}
        a.popup.status_shown_at = 100.120
        self.assertEqual(120, a.press_timing()["pill_shown"])
        a.popup.status_shown_at = 99.0      # the previous press's pill
        self.assertNotIn("pill_shown", a.press_timing())

    def _report(self, a):
        class _Timer:
            def __init__(self, _s, fn):
                self.fn = fn
                self.daemon = False

            def start(self):
                self.fn()

        import app
        with mock.patch.object(app.threading, "Timer", _Timer):
            a._schedule_press_report()

    def test_a_fast_press_reports_nothing(self):
        a = self._app()
        a._press_t0 = 100.0
        a._press_marks = {"cue": 3, "pill_queued": 5, "capture": 60}
        a.popup.status_shown_at = 100.030
        self._report(a)
        a._log_error_event.assert_not_called()

    def test_a_slow_press_is_reported_with_its_marks(self):
        a = self._app()
        a._press_t0 = 100.0
        a._press_marks = {"cue": 400, "pill_queued": 420, "capture": 700}
        a.popup.status_shown_at = 100.900
        self._report(a)
        event, detail = a._log_error_event.call_args[0]
        self.assertEqual("press_slow", event)
        self.assertEqual(["capture", "cue", "pill_shown"], detail["slow"])
        self.assertEqual(900, detail["marks_ms"]["pill_shown"])

    def test_a_late_cue_on_the_cold_mic_path_is_not_slow(self):
        # The cue waits for proven audio there by design.
        a = self._app()
        a._press_t0 = 100.0
        a._press_marks = {"cue": 400, "pill_queued": 5, "capture": 390}
        a.popup.status_shown_at = 100.030
        self._report(a)
        a._log_error_event.assert_not_called()

    def test_reports_are_capped_per_run(self):
        a = self._app()
        a._press_t0 = None
        a._press_marks = {}
        for _ in range(a._TELEMETRY_CAP + 5):
            a._report_empty_dictation("No speech detected")
        self.assertEqual(a._TELEMETRY_CAP, a._log_error_event.call_count)

    def test_an_empty_dictation_is_reported(self):
        import app

        a = self._app()
        a._press_t0 = None
        a._press_marks = {}
        with mock.patch.object(app, "_startup_log_path",
                               return_value=os.devnull):
            a._on_pipeline_error("No speech detected")
        event, detail = a._log_error_event.call_args[0]
        self.assertEqual("dictation_empty", event)
        self.assertEqual(2.5, detail["seconds"])
        self.assertEqual("No speech detected", detail["error"])


class EnterAsTheTextLandsTests(unittest.TestCase):
    """The badge appears the moment the text lands; the user's Enter is often
    already down, or goes down inside the 0.25 s grace window. Both used to be
    ignored and the badge stayed up."""

    def _armed(self, at_stop=(), at_arm=(), snapshot=True, synthetic_enter=False,
               tapped_before_arm=()):
        keys = {}
        clock = [1000.0]
        fake_time = types.SimpleNamespace(time=lambda: clock[0])
        orig_time = popup_mod.time
        self.addCleanup(setattr, popup_mod, "time", orig_time)
        popup_mod.time = fake_time
        orig_win = popup_mod._windows_key_held
        self.addCleanup(setattr, popup_mod, "_windows_key_held", orig_win)
        popup_mod._windows_key_held = lambda: False

        p = FloatingPopup.__new__(FloatingPopup)
        p._dismiss_poll = None
        def _state(vk):
            # Like GetAsyncKeyState: reading clears the "pressed since" bit.
            v = keys.get(vk, 0)
            keys[vk] = v & ~0x0001
            return v
        p._key_state = _state
        for vk in at_stop:
            keys[vk] = 0x8000
        if snapshot:
            FloatingPopup.note_dictation_stop_keys(p)
        if synthetic_enter:
            FloatingPopup.note_synthetic_enter(p)
        for vk in at_stop:
            keys[vk] = 0
        for vk in at_arm:
            keys[vk] = 0x8000
        for vk in tapped_before_arm:
            keys[vk] = 0x0001
        p._icon_entered = clock[0]
        queued = []

        class _Root:
            def after(self, _ms, fn):
                queued.append(fn)
        p.root = _Root()
        hidden = []
        p._do_hide = lambda: hidden.append(True)
        self._popup = p
        FloatingPopup._register_key_dismiss(p)

        def tick(dt=0.03):
            clock[0] += dt
            if queued:
                queued.pop(0)()
        return keys, tick, hidden

    def test_enter_already_down_when_the_badge_arms_dismisses_at_once(self):
        keys, tick, hidden = self._armed(at_stop=(0x56,), at_arm=(0x0D,))
        tick()                      # first poll, still inside the grace window
        self.assertEqual([True], hidden)

    def test_enter_tapped_before_the_badge_appears_dismisses_it(self):
        # Pressed and released between the stop and the text landing: only the
        # "pressed since" bit is left.
        keys, tick, hidden = self._armed(at_stop=(0x56,), tapped_before_arm=(0x0D,))
        tick()
        self.assertEqual([True], hidden)

    def test_our_line_break_before_the_badge_appears_never_dismisses(self):
        keys, tick, hidden = self._armed(at_stop=(0x56,),
                                         tapped_before_arm=(0x0D, 0x10))
        tick()
        tick(0.3)
        tick()
        self.assertEqual([], hidden)

    def test_one_poll_enter_tap_inside_the_grace_window_dismisses_at_once(self):
        keys, tick, hidden = self._armed(at_stop=(0x56,))
        keys[0x0D] = 0x8000
        tick(0.03)
        self.assertEqual([True], hidden)

    def test_enter_tap_between_two_polls_inside_the_grace_dismisses(self):
        keys, tick, hidden = self._armed(at_stop=(0x56,))
        keys[0x0D] = 0x0001         # down and up between polls
        tick(0.03)
        self.assertEqual([True], hidden)

    def test_ctrl_enter_dismisses_at_once(self):
        keys, tick, hidden = self._armed(at_stop=(0x56,))
        keys[0x11] = 0x8000
        keys[0x0D] = 0x8000
        tick(0.03)
        self.assertEqual([True], hidden)

    def test_our_line_break_tapped_before_the_badge_never_dismisses(self):
        keys, tick, hidden = self._armed(at_stop=(0x56,))
        keys[0x0D] = 0x0001
        keys[0x10] = 0x0001         # Shift went down and up with it
        tick(0.03)
        tick(0.3)
        tick()
        self.assertEqual([], hidden)

    def test_auto_enter_landing_after_the_badge_arms_never_dismisses(self):
        keys, tick, hidden = self._armed(at_stop=(0x56,))
        tick(0.03)
        FloatingPopup.note_synthetic_enter(self._popup)
        keys[0x0D] = 0x8000
        tick(0.03)
        keys[0x0D] = 0
        tick(0.03)
        self.assertEqual([], hidden)

    def test_the_stop_hotkey_still_held_never_dismisses(self):
        # V of Alt+V still physically down when the badge arms.
        keys, tick, hidden = self._armed(at_stop=(0x56,), at_arm=(0x56,))
        tick(0.3)
        tick()
        self.assertEqual([], hidden)

    def test_our_own_paste_chord_is_not_a_fresh_press(self):
        # Ctrl+V still landing as the badge arms.
        keys, tick, hidden = self._armed(at_arm=(0x11, 0x56))
        tick(0.3)
        tick()
        self.assertEqual([], hidden)

    def test_our_typed_line_break_is_not_a_fresh_press(self):
        keys, tick, hidden = self._armed(at_arm=(0x10, 0x0D))
        tick(0.3)
        self.assertEqual([], hidden)

    def test_without_a_stop_snapshot_a_held_key_stays_ignored(self):
        # A badge from a path that took no stop snapshot: the old rule.
        keys, tick, hidden = self._armed(at_arm=(0x0D,), snapshot=False)
        tick(0.3)
        tick()
        self.assertEqual([], hidden)

    def test_space_pressed_in_the_grace_window_and_held_past_it_dismisses(self):
        keys, tick, hidden = self._armed(at_stop=(0x56,))
        tick(0.1)
        keys[0x20] = 0x8000
        tick(0.05)                  # still in grace
        self.assertEqual([], hidden)
        tick(0.15)                  # grace over, Enter still down
        self.assertEqual([True], hidden)

    def test_a_blip_inside_the_grace_window_still_never_dismisses(self):
        # Our own keystrokes landing as the badge arms are down and up at once:
        # the Shift+Enter line break, or a non-Enter key.
        for blip in ((0x10, 0x0D), (0x56,)):
            keys, tick, hidden = self._armed(at_stop=(0x56,))
            for vk in blip:
                keys[vk] = 0x8000
            tick(0.05)
            for vk in blip:
                keys[vk] = 0
            tick(0.05)
            tick(0.3)
            tick()
            self.assertEqual([], hidden, blip)

    def test_a_quick_space_tap_inside_the_grace_window_dismisses(self):
        # A person's tap is seen on two polls; it counts when the grace ends.
        keys, tick, hidden = self._armed(at_stop=(0x56,))
        keys[0x20] = 0x8000
        tick(0.03)
        tick(0.03)
        keys[0x20] = 0
        tick(0.03)
        self.assertEqual([], hidden)
        tick(0.3)
        self.assertEqual([True], hidden)

    def test_our_auto_enter_never_dismisses(self):
        keys, tick, hidden = self._armed(at_stop=(0x56,), at_arm=(0x0D,),
                                         synthetic_enter=True)
        tick(0.03)
        tick(0.03)
        keys[0x0D] = 0
        tick(0.3)
        tick()
        self.assertEqual([], hidden)

    def test_the_snapshot_serves_one_badge_only(self):
        keys = {0x0D: 0x8000}
        p = FloatingPopup.__new__(FloatingPopup)
        p._key_state = lambda vk: keys.get(vk, 0)
        FloatingPopup.note_dictation_stop_keys(p)
        self.assertEqual({0x0D}, p._stop_keys)
        p._dismiss_poll = None
        p._icon_entered = time.time()
        p.root = types.SimpleNamespace(after=lambda *_a: None)
        p._do_hide = lambda: None
        FloatingPopup._register_key_dismiss(p)
        self.assertIsNone(p._stop_keys)


if __name__ == "__main__":
    unittest.main()
