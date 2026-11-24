"""Auto moves off a mic that sends pure silence, and proves the next one works.

James Murphy, 24 Nov 2026: Auto ranked 'Analogue 1 + 2 (2- Focusrite USB
Audio)' first (it reads as 'usb audio') with nothing plugged into the
interface, and every dictation came back digital silence. Echo only reopened
the same dead input. These tests pin the fix:

  1. Auto drops the dead mic and names the next real one.
  2. A pinned mic is never switched.
  3. Never switches to a loopback endpoint, and with no alternative the
     demotion is undone.
  4. switch_to_next_input keeps a mic that shows signal, and drops a second
     dead one for the next.

No audio streams are opened.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recorder as recorder_mod
from recorder import Recorder

FOCUSRITE = "Analogue 1 + 2 (2- Focusrite USB Audio)"
WEBCAM = "Microphone (C920 HD Pro Webcam)"
ARRAY = "Microphone Array (Realtek Audio)"
STEREO = "Stereo Mix (Realtek Audio)"


def _dev(i, name):
    return {"index": i, "name": name, "channels": 1, "sample_rate": 48000.0}


DEVICES = [_dev(2, FOCUSRITE), _dev(4, WEBCAM), _dev(6, ARRAY), _dev(8, STEREO)]


def _rec(devices=DEVICES, input_device="auto", active=FOCUSRITE):
    rec = Recorder(input_device=input_device)
    rec._get_default_input_index = staticmethod(lambda: None)
    rec.get_input_devices = lambda: list(devices)
    rec._active_device_name = active
    rec._active_device_index = 2
    return rec


class SwitchFromDeadInputTests(unittest.TestCase):
    def test_focusrite_ranks_first_then_is_dropped(self):
        rec = _rec()
        self.assertEqual(rec.pick_best_input_name(DEVICES), FOCUSRITE)
        self.assertEqual(rec.switch_from_dead_input(), WEBCAM)
        self.assertIn(FOCUSRITE.lower(), rec._demoted_devices)
        self.assertIsNone(rec._active_device_index)
        self.assertEqual(rec.pick_best_input_name(DEVICES), WEBCAM)

    def test_pinned_mic_is_never_switched(self):
        rec = _rec(input_device=FOCUSRITE)
        self.assertEqual(rec.switch_from_dead_input(), "")
        self.assertFalse(rec._demoted_devices)

    def test_no_switch_to_loopback_and_demotion_undone(self):
        rec = _rec(devices=[_dev(2, FOCUSRITE), _dev(8, STEREO)])
        self.assertEqual(rec.switch_from_dead_input(), "")
        self.assertFalse(rec._demoted_devices)

    def test_plugging_something_in_gives_dead_mic_a_fresh_chance(self):
        rec = _rec()
        rec.switch_from_dead_input()
        more = DEVICES + [_dev(10, "Microphone (Yeti)")]
        rec._pick_best_input(more)
        self.assertFalse(rec._demoted_devices)


class SwitchToNextInputTests(unittest.TestCase):
    def setUp(self):
        self._p = mock.patch.object(recorder_mod, "_DEAD_VERIFY_SECONDS", 0.2)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def _fake_restart(self, rec, live):
        """restart_warm stand-in: 'opens' Auto's pick and, when that mic is in
        `live`, delivers a block with real signal."""
        def restart():
            name = rec.pick_best_input_name(rec.get_input_devices())
            with rec._lock:
                rec._active_device_name = name
                rec._stream_opened_ts = recorder_mod.time.monotonic()
                if name in live:
                    rec._last_live_ts = rec._stream_opened_ts + 0.01
            rec.restarts.append(name)
        rec.restarts = []
        rec.restart_warm = restart

    def test_keeps_new_mic_that_carries_sound(self):
        rec = _rec()
        rec.switch_from_dead_input()
        self._fake_restart(rec, live={WEBCAM})
        rec.switch_to_next_input()
        self.assertEqual(rec.restarts, [WEBCAM])
        self.assertNotIn(WEBCAM.lower(), rec._demoted_devices)

    def test_second_dead_mic_dropped_for_the_next(self):
        rec = _rec()
        rec.switch_from_dead_input()
        self._fake_restart(rec, live={ARRAY})
        rec.switch_to_next_input()
        self.assertEqual(rec.restarts, [WEBCAM, ARRAY])
        self.assertIn(WEBCAM.lower(), rec._demoted_devices)

    def test_abandoned_when_a_dictation_starts(self):
        rec = _rec()
        rec.switch_from_dead_input()
        self._fake_restart(rec, live=set())
        rec._recording = True
        rec.switch_to_next_input()
        self.assertEqual(rec.restarts, [WEBCAM])
        self.assertNotIn(WEBCAM.lower(), rec._demoted_devices)


class AppDeadMicSwitchTests(unittest.TestCase):
    """The no-speech path: digital silence on an Auto mic switches and says
    which mic it moved to, instead of the 'sending no sound' toast."""

    def _run(self, switch_to):
        import types
        import app
        import mic_access
        a = object.__new__(app.WhisperFlowApp)
        a.recorder = types.SimpleNamespace(
            last_recording_seconds=3.0, _active_device_name=FOCUSRITE,
            voiced_seconds=0.0, probe_in_flight=False,
            consume_mic_advice=lambda: None,
            switch_from_dead_input=lambda: switch_to,
            switch_to_next_input=mock.Mock(),
            request_dead_input_reopen=mock.Mock(return_value=True))
        a.feedback = mock.Mock()
        a._log_error_event = mock.Mock()
        diag = {"privacy": {}, "cause": mic_access.DIGITAL_SILENCE,
                "endpoints": 1}
        with mock.patch.object(mic_access, "diagnose",
                               return_value=(mic_access.DIGITAL_SILENCE, diag)), \
                mock.patch("error_reporter.report_error"), \
                mock.patch.object(app.threading, "Thread") as thread:
            handled = a._handle_no_speech("empty_result", 3.0, 0.00001)
        return a, handled, thread

    def test_switches_and_names_the_new_mic(self):
        a, handled, thread = self._run(WEBCAM)
        self.assertTrue(handled)
        msg = a.feedback.error_occurred.call_args[0][0]
        self.assertIn(f"switched to '{WEBCAM}'", msg)
        events = [c[0][0] for c in a._log_error_event.call_args_list]
        self.assertEqual(["mic_switched"], events)
        self.assertIs(thread.call_args.kwargs["target"],
                      a.recorder.switch_to_next_input)
        a.recorder.request_dead_input_reopen.assert_not_called()

    def test_no_alternative_keeps_the_dead_mic_message(self):
        a, handled, _t = self._run("")
        self.assertTrue(handled)
        self.assertIn("sending no sound",
                      a.feedback.error_occurred.call_args[0][0])
        a.recorder.request_dead_input_reopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
