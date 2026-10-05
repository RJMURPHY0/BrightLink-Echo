"""A hung Windows audio engine (2026-10-05) gave five dead dictations in a row,
each claiming "reconnected". The second dead capture, or one while Windows
Audio is not running, must offer the engine restart instead."""

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audio_engine  # noqa: E402
import app  # noqa: E402


def _bare_app():
    a = object.__new__(app.WhisperFlowApp)
    a.recorder = types.SimpleNamespace(last_recording_seconds=3.0,
                                       _active_device_name="Mic",
                                       restart_warm=lambda: None)
    a.feedback = mock.Mock()
    a._log_error_event = mock.Mock()
    return a


class DeadCaptureEscalationTests(unittest.TestCase):
    def test_first_dead_capture_reconnects_quietly(self):
        a = _bare_app()
        with mock.patch.object(audio_engine, "service_running", return_value=True):
            self.assertTrue(a._handle_dead_capture(0.0))
        msg = a.feedback.error_occurred.call_args[0][0]
        self.assertIn("reconnected", msg)

    def test_second_dead_capture_offers_engine_restart(self):
        a = _bare_app()
        with mock.patch.object(audio_engine, "service_running", return_value=True):
            a._handle_dead_capture(0.0)
            a._handle_dead_capture(0.0)
        self.assertEqual(a.feedback.error_occurred.call_args[0][0],
                         app.WhisperFlowApp._AUDIO_ENGINE_DOWN_MSG)

    def test_stopped_service_offers_restart_at_once(self):
        a = _bare_app()
        with mock.patch.object(audio_engine, "service_running", return_value=False):
            a._handle_dead_capture(0.0)
        self.assertEqual(a.feedback.error_occurred.call_args[0][0],
                         app.WhisperFlowApp._AUDIO_ENGINE_DOWN_MSG)

    def test_short_tap_is_not_a_dead_stream(self):
        a = _bare_app()
        a.recorder.last_recording_seconds = 0.2
        self.assertFalse(a._handle_dead_capture(0.0))
        a.feedback.error_occurred.assert_not_called()

    def test_engine_message_gets_the_button_toast(self):
        a = _bare_app()
        a.app_window = mock.Mock()
        a.tray = mock.Mock()
        with mock.patch.object(app, "_startup_log_path",
                               return_value=os.devnull):
            a._on_pipeline_error(app.WhisperFlowApp._AUDIO_ENGINE_DOWN_MSG)
        a.app_window.show_action_toast.assert_called_once()
        self.assertEqual(a.app_window.show_action_toast.call_args[0][1],
                         "Restart audio")
        a.tray.notify.assert_not_called()


class ServiceQueryTests(unittest.TestCase):
    def _sc(self, out):
        return mock.patch.object(audio_engine.subprocess, "run",
                                 return_value=types.SimpleNamespace(stdout=out))

    def test_running(self):
        with self._sc("        STATE              : 4  RUNNING\n"):
            self.assertTrue(audio_engine.service_running())

    def test_stopped(self):
        with self._sc("        STATE              : 1  STOPPED\n"):
            self.assertFalse(audio_engine.service_running())

    def test_unreadable_counts_as_running(self):
        with self._sc("garbage"):
            self.assertTrue(audio_engine.service_running())


if __name__ == "__main__":
    unittest.main()
