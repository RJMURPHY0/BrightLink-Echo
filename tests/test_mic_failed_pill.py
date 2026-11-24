"""The pill says "Mic failed" instead of "Recording" when the mic is dead.

Ryan (24 Nov 2026): "if somebody's microphone stops working, when you then
press Alt V ... instead of saying recording, it should be like failed".

Both directions are pinned: a dead mic shows the failure, a working mic (or a
noise-suppressed one that outputs exact zeros until you talk) never does.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mic_health as mh


class Verdict(unittest.TestCase):

    def test_nothing_judged_during_the_start_grace(self):
        self.assertFalse(mh.mic_failed(0.3, 0, float("inf"), 0.0, False))

    def test_no_audio_at_all_is_failed(self):
        self.assertTrue(mh.mic_failed(1.0, 0, float("inf"), 0.0, False))

    def test_stalled_stream_is_failed(self):
        self.assertTrue(mh.mic_failed(3.0, 16000, 2.0, 0.0, False))

    def test_working_mic_is_fine(self):
        self.assertFalse(mh.mic_failed(3.0, 48000, 0.02, 0.0, False))

    def test_quiet_room_is_fine(self):
        # Exact zeros but Windows says nothing is switched off: noise
        # suppression before the user talks. Never a false "failed".
        self.assertFalse(mh.mic_failed(5.0, 80000, 0.02, 4.0, False))

    def test_silence_windows_explains_is_failed(self):
        self.assertTrue(mh.mic_failed(2.0, 32000, 0.02, 1.6, True))

    def test_dead_input_never_live_is_failed(self):
        # James Murphy's usb mic: peak 0.00001 on every press, never louder.
        self.assertTrue(mh.mic_failed(2.5, 40000, 0.02, 0.0, False,
                                      dead_run=2.5, ever_live=False))

    def test_dead_input_on_a_mic_that_worked_is_fine(self):
        # Noise suppression at zero before you talk, mic heard before.
        self.assertFalse(mh.mic_failed(5.0, 80000, 0.02, 4.0, False,
                                       dead_run=5.0, ever_live=True))

    def test_dead_input_needs_two_seconds(self):
        self.assertFalse(mh.mic_failed(1.9, 30000, 0.02, 0.0, False,
                                       dead_run=1.9, ever_live=False))

    def test_dead_peak_matches_the_after_dictation_check(self):
        import mic_access
        import recorder
        self.assertEqual(recorder._DEAD_PEAK, mic_access.DEAD_PEAK)

    def test_block_check_waits_for_long_silence(self):
        self.assertFalse(mh.needs_block_check(1.0))
        self.assertTrue(mh.needs_block_check(1.5))


class _Recorder:
    def __init__(self):
        self.total_recorded_samples = 9600   # pre-roll seed
        self.heartbeat = 0.02
        self.silent = 0.0
        self.dead = 0.0
        self.ever_live = True

    def live_health(self):
        return (self.heartbeat, self.silent, "Test Mic", self.dead,
                self.ever_live)


class Watch(unittest.TestCase):

    def setUp(self):
        import app
        self.app = app
        self.rec = _Recorder()
        self.popup = mock.Mock()
        self.log = mock.Mock()
        self.clock = [100.0]
        p = mock.patch.object(app.time, "monotonic", lambda: self.clock[0])
        p.start()
        self.addCleanup(p.stop)
        self.opened = [100.0]            # recorder.start() returned at t=0
        self.watch = app._MicHealthWatch(self.rec, self.popup, self.log,
                                         lambda: self.opened[0])

    def _tick(self, at):
        self.clock[0] = 100.0 + at
        self.watch.tick()

    def test_dead_stream_flips_to_failed_then_back(self):
        self._tick(0.5)
        self.popup.set_mic_failed.assert_not_called()
        self._tick(1.0)                      # no samples since the press
        self.popup.set_mic_failed.assert_called_once_with(True)
        self.log.assert_called_once()
        self.assertEqual(self.log.call_args[0][0], "mic_failed_live")
        self.rec.total_recorded_samples += 1600   # watchdog revived it
        self._tick(1.2)
        self.popup.set_mic_failed.assert_called_with(False)
        self.rec.total_recorded_samples = 9600 + 1600
        self.rec.heartbeat = 2.0             # dies again
        self._tick(4.0)
        self.assertEqual(self.popup.set_mic_failed.call_args[0], (True,))
        self.log.assert_called_once()        # logged once per recording

    def test_james_dead_usb_mic_flips_to_failed(self):
        self.rec.ever_live = False
        for i in range(1, 30):
            self.rec.total_recorded_samples += 640
            self.rec.dead = i * 0.1
            self._tick(i * 0.1)
        self.popup.set_mic_failed.assert_called_once_with(True)
        self.assertTrue(self.log.call_args[0][1]["dead_ms"] >= 2000)

    def test_nothing_judged_until_start_returns(self):
        # A slow but working open (dead warm stream reopened, Bluetooth
        # profile switch): start() has not returned, so no "Mic failed".
        self.opened[0] = 0.0
        for i in range(1, 30):
            self._tick(i * 0.1)
        self.popup.set_mic_failed.assert_not_called()
        self.opened[0] = 103.0           # start() returned 3 s after the press
        self.rec.total_recorded_samples += 640
        self._tick(3.1)
        self._tick(3.5)
        self.popup.set_mic_failed.assert_not_called()

    def test_idle_silence_before_the_press_never_counts(self):
        # Noise suppression at zero all morning, first press of the day: the
        # dead run is long but none of it is inside this dictation yet.
        self.rec.ever_live = False
        self.rec.dead = 3600.0
        self.rec.silent = 3600.0
        for i in range(1, 15):
            self.rec.total_recorded_samples += 640
            self._tick(i * 0.1)          # 1.4 s into the dictation
        self.popup.set_mic_failed.assert_not_called()

    def test_a_new_recording_starts_clean(self):
        self._tick(1.0)                  # dead: no samples
        self.popup.set_mic_failed.assert_called_once_with(True)
        self.opened[0] = 110.0           # next press, mic fine
        for i in range(1, 30):
            self.rec.total_recorded_samples += 640
            self._tick(10.0 + i * 0.1)
        self.popup.set_mic_failed.assert_called_once_with(True)  # no new flip
        self.assertFalse(self.watch._failed)

    def test_working_mic_never_flips(self):
        for i in range(1, 40):
            self.rec.total_recorded_samples += 640
            self._tick(i * 0.1)
        self.popup.set_mic_failed.assert_not_called()

    def test_privacy_switch_off_flips_after_windows_says_so(self):
        import mic_access
        self.rec.silent = 60.0           # exact zeros since long before
        with mock.patch.object(mic_access, "diagnose",
                               return_value=(mic_access.APPS_ACCESS_OFF, {})), \
             mock.patch.object(self.app.threading, "Thread") as T:
            T.return_value.start.side_effect = lambda: T.call_args[1]["target"]()
            for i in range(1, 25):           # asks Windows at 1.5 s (sync)
                self.rec.total_recorded_samples += 640
                self._tick(i * 0.1)
        self.popup.set_mic_failed.assert_called_with(True)

    def test_noise_suppression_silence_never_flips(self):
        import mic_access
        self.rec.silent = 3.0
        with mock.patch.object(mic_access, "diagnose",
                               return_value=(mic_access.DIGITAL_SILENCE, {})), \
             mock.patch.object(self.app.threading, "Thread") as T:
            T.return_value.start.side_effect = lambda: T.call_args[1]["target"]()
            for i in range(1, 40):
                self.rec.total_recorded_samples += 640
                self._tick(i * 0.1)
        self.popup.set_mic_failed.assert_not_called()


class _Root:
    """Runs after() callbacks at once, like a Tk loop that is idle."""
    def after(self, _ms, fn=None, *args):
        if fn is not None:
            fn(*args)


class PillLabel(unittest.TestCase):

    def _popup(self, mode="status"):
        import popup as pm
        p = pm.FloatingPopup()
        p.root = _Root()
        p._mode = mode
        p._captions_enabled = False
        p._status_label = mock.Mock()
        p._status_label.cget.return_value = "Recording"
        p._pill_edit = mock.MagicMock()
        return p, pm

    def test_failed_is_red_and_back_is_recording(self):
        p, pm = self._popup()
        p.set_mic_failed(True)
        p._status_label.configure.assert_called_with(text="Mic failed",
                                                     fg=pm.CP["error"])
        p.set_mic_failed(False)
        p._status_label.configure.assert_called_with(text="Recording",
                                                     fg=pm.CP["subtext"])

    def test_late_recording_flip_never_hides_a_failure(self):
        p, _ = self._popup()
        p.set_mic_failed(True)
        p._status_label.configure.reset_mock()
        p.set_status_text("Recording")
        p._status_label.configure.assert_not_called()

    def test_no_op_outside_the_pill(self):
        p, _ = self._popup(mode="icon")
        p.set_mic_failed(True)
        p._status_label.configure.assert_not_called()

    def test_a_quick_retry_ends_the_hold(self):
        p, _ = self._popup()
        with mock.patch.object(p, "flash_status"):
            p.flash_mic_failed(ms=2600)
        self.assertTrue(p.holding_mic_failed)
        src = open(sys.modules["popup"].__file__, encoding="utf-8").read()
        body = src[src.index("    def _enter_status_mode"):]
        body = body[:body.index("    def _reset_caption_widget")]
        self.assertIn("if recording:", body)
        self.assertIn("self._mic_failed_until = 0.0", body)

    def test_press_failure_holds_the_pill_until_its_timer(self):
        p, _ = self._popup()
        with mock.patch.object(p, "flash_status"):
            p.flash_mic_failed(ms=2600)
        self.assertTrue(p.holding_mic_failed)
        p._mic_failed_until = 0
        self.assertFalse(p.holding_mic_failed)


class StartFailure(unittest.TestCase):

    def test_app_shows_mic_failed_when_no_mic_opens(self):
        import app
        with open(app.__file__, encoding="utf-8") as f:
            src = f.read()
        start = src.index("    def _on_start_recording(self)")
        end = src.index("    def _on_stop_recording(self)")
        body = src[start:end]
        self.assertIn("flash_mic_failed", body)
        # Only when the mic itself would not open: a later error in the start
        # path (spec fixer, streaming session, timer) is not "Mic failed".
        self.assertIn("mic_open = True", body)
        self.assertIn("if not mic_open:", body)
        self.assertLess(body.index("self.recorder.start()"),
                        body.index("mic_open = True"))
        # Going idle must not hide the failure it just showed.
        self.assertIn("holding_mic_failed", src)


if __name__ == "__main__":
    unittest.main()
