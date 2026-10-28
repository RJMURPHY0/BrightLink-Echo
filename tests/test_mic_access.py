"""A dictation that hears nothing because of Windows (a microphone privacy
switch off, the mic muted or at 0, pure digital silence) must say exactly that
with a button to the right Settings page, log the cause, and stay silent when
everything is working (fleet data 2026-10-25: a Realtek mic sent bit-exact
silence for ten minutes and the user was never told why)."""

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mic_access  # noqa: E402
import app  # noqa: E402

ALLOW = {"device": "Allow", "apps": "Allow", "desktop": "Allow", "policy": None}
EP_OK = {"name": "Microphone (Realtek HD Audio Mic input)", "muted": False,
         "volume": 0.8, "default": True}


class DiagnoseTests(unittest.TestCase):
    def test_each_privacy_switch_is_named(self):
        for key, cause in (("device", mic_access.DEVICE_ACCESS_OFF),
                           ("apps", mic_access.APPS_ACCESS_OFF),
                           ("desktop", mic_access.DESKTOP_ACCESS_OFF)):
            state = dict(ALLOW, **{key: "Deny"})
            got, detail = mic_access.diagnose(0.0, "Mic", state=state, endpoints=[])
            self.assertEqual(cause, got)
            self.assertEqual(state, detail["privacy"])

    def test_widest_switch_wins(self):
        state = {"device": "Deny", "apps": "Deny", "desktop": "Deny"}
        self.assertEqual(mic_access.DEVICE_ACCESS_OFF, mic_access.privacy_cause(state))

    def test_absent_values_are_the_windows_default_on(self):
        self.assertEqual(mic_access.OK, mic_access.privacy_cause(
            {"device": None, "apps": None, "desktop": None}))

    def test_muted_and_zero_volume(self):
        muted = dict(EP_OK, muted=True)
        self.assertEqual(mic_access.MUTED, mic_access.diagnose(
            0.0, EP_OK["name"], state=ALLOW, endpoints=[muted])[0])
        quiet = dict(EP_OK, volume=0.0)
        self.assertEqual(mic_access.VOLUME_ZERO, mic_access.diagnose(
            0.0, EP_OK["name"], state=ALLOW, endpoints=[quiet])[0])

    def test_pure_zeros_with_everything_on_is_digital_silence(self):
        self.assertEqual(mic_access.DIGITAL_SILENCE, mic_access.diagnose(
            0.0, EP_OK["name"], state=ALLOW, endpoints=[EP_OK])[0])

    def test_a_live_quiet_mic_is_not_a_problem(self):
        # Room noise, nobody spoke: never prompt.
        cause, _ = mic_access.diagnose(0.0007, EP_OK["name"], state=ALLOW,
                                       endpoints=[EP_OK])
        self.assertEqual(mic_access.OK, cause)
        self.assertFalse(mic_access.is_blocking(cause))

    def test_endpoint_check_failure_still_diagnoses(self):
        with mock.patch.object(mic_access, "_endpoints_with_timeout",
                               side_effect=TimeoutError("hung")):
            cause, detail = mic_access.diagnose(0.01, "Mic", state=ALLOW)
        self.assertEqual(mic_access.OK, cause)
        self.assertIn("hung", detail["endpoint_error"])

    def test_truncated_portaudio_name_matches_its_endpoint(self):
        other = {"name": "Microphone (Logi USB Headset)", "muted": False,
                 "volume": 1.0, "default": True}
        target = dict(EP_OK, muted=True, default=False)
        # MME keeps 31 characters of the name.
        ep = mic_access.match_endpoint([other, target], EP_OK["name"][:31])
        self.assertIs(target, ep)

    def test_an_unmatched_name_never_blames_another_mic(self):
        muted_default = dict(EP_OK, name="Microphone (Logi USB Headset)",
                             muted=True, default=True)
        self.assertIsNone(mic_access.match_endpoint([muted_default], "Yeti Stereo"))
        cause, _ = mic_access.diagnose(0.001, "Yeti Stereo", state=ALLOW,
                                       endpoints=[muted_default])
        self.assertEqual(mic_access.OK, cause)

    def test_two_matches_are_not_certain(self):
        a, b = dict(EP_OK), dict(EP_OK, muted=True)
        self.assertIsNone(mic_access.match_endpoint([a, b], EP_OK["name"]))

    def test_no_device_name_uses_the_default(self):
        dflt = dict(EP_OK, default=True)
        self.assertIs(dflt, mic_access.match_endpoint(
            [dict(EP_OK, name="Other", default=False), dflt], ""))

    def test_privacy_only_never_scans_endpoints(self):
        with mock.patch.object(mic_access, "_endpoints_with_timeout") as scan:
            cause, _ = mic_access.diagnose(0.0, "Mic", state=ALLOW, privacy_only=True)
        scan.assert_not_called()
        self.assertEqual(mic_access.OK, cause)

    def test_every_blocking_cause_has_a_message_and_a_settings_page(self):
        for cause in mic_access._BLOCKING:
            msg, button, uri = mic_access.message_for(cause, "Mic")
            self.assertTrue(msg and button, cause)
            self.assertTrue(uri.startswith("ms-settings:"), cause)
            self.assertNotIn("—", msg)  # no em dashes in user copy

    def test_desktop_message_names_the_exact_switch(self):
        msg, _b, uri = mic_access.message_for(mic_access.DESKTOP_ACCESS_OFF)
        self.assertIn("Let desktop apps access your microphone", msg)
        self.assertEqual("ms-settings:privacy-microphone", uri)

    def test_open_settings_refuses_anything_but_settings(self):
        with mock.patch("os.startfile") as start:
            self.assertFalse(mic_access.open_settings("https://example.com"))
            start.assert_not_called()
            self.assertTrue(mic_access.open_settings(mic_access.PRIVACY_URI))
            start.assert_called_once_with(mic_access.PRIVACY_URI)


@unittest.skipUnless(sys.platform == "win32", "Core Audio is Windows only")
class RealMachineReadTests(unittest.TestCase):
    """Read only: never changes a switch, mute or volume."""

    def test_privacy_state_reads(self):
        state = mic_access.privacy_state()
        self.assertEqual({"device", "apps", "desktop", "policy"}, set(state))

    def test_endpoint_scan_returns_well_formed_rows(self):
        try:
            eps = mic_access._endpoints_with_timeout()
        except OSError as e:  # a runner with no audio service
            self.skipTest(str(e))
        for ep in eps:
            self.assertIn(ep["muted"], (True, False, None))
            if ep["volume"] is not None:
                self.assertGreaterEqual(ep["volume"], 0.0)
                self.assertLessEqual(ep["volume"], 1.0)


def _bare_app():
    a = object.__new__(app.WhisperFlowApp)
    a.recorder = types.SimpleNamespace(
        last_recording_seconds=3.0, _active_device_name="Mic",
        restart_warm=lambda: None, voiced_seconds=0.0, probe_in_flight=False,
        consume_mic_advice=lambda: None)
    a.feedback = mock.Mock()
    a._log_error_event = mock.Mock()
    a.app_window = mock.Mock()
    a.tray = mock.Mock()
    a._auth = types.SimpleNamespace(user_email="u@example.com",
                                    access_token="fake-token")
    return a


class AppWiringTests(unittest.TestCase):
    def _no_speech(self, a, cause, peak=0.0):
        diag = {"privacy": ALLOW, "cause": cause, "endpoints": 1}
        with mock.patch.object(mic_access, "diagnose", return_value=(cause, diag)), \
                mock.patch("error_reporter.report_error") as report:
            handled = a._handle_no_speech("empty_result", 2.0, peak)
        return handled, report

    def test_blocked_mic_gets_message_event_and_report(self):
        a = _bare_app()
        handled, report = self._no_speech(a, mic_access.DESKTOP_ACCESS_OFF)
        self.assertTrue(handled)
        msg = a.feedback.error_occurred.call_args[0][0]
        self.assertIn("Let desktop apps access your microphone", msg)
        events = [c[0][0] for c in a._log_error_event.call_args_list]
        self.assertEqual(["mic_blocked"], events)
        payload = a._log_error_event.call_args[0][1]
        self.assertEqual(mic_access.DESKTOP_ACCESS_OFF, payload["cause"])
        self.assertEqual(ALLOW, payload["privacy"])
        report.assert_called_once()
        self.assertEqual("fake-token", report.call_args.kwargs["token"])

    def test_report_goes_once_per_cause(self):
        a = _bare_app()
        _h, r1 = self._no_speech(a, mic_access.MUTED)
        _h, r2 = self._no_speech(a, mic_access.MUTED)
        self.assertEqual(1, r1.call_count)
        self.assertEqual(0, r2.call_count)

    def test_working_mic_keeps_the_old_path_and_shows_nothing_new(self):
        a = _bare_app()
        handled, report = self._no_speech(a, mic_access.OK, peak=0.001)
        self.assertFalse(handled)
        a.feedback.error_occurred.assert_not_called()
        report.assert_not_called()
        self.assertEqual("mic_silent", a._log_error_event.call_args[0][0])
        # ...but the log now carries the Windows state.
        self.assertEqual(ALLOW, a._log_error_event.call_args[0][1]["privacy"])

    def test_audible_clip_is_never_blamed_on_windows(self):
        # Low voiced time but a real peak: sound got through, so no switch,
        # mute or volume is at fault and diagnosis must not even run.
        a = _bare_app()
        with mock.patch.object(mic_access, "diagnose") as diag:
            handled = a._handle_no_speech("empty_result", 2.0, 0.05)
        self.assertFalse(handled)
        diag.assert_not_called()
        a.feedback.error_occurred.assert_not_called()

    def test_message_becomes_a_toast_with_the_settings_button(self):
        a = _bare_app()
        self._no_speech(a, mic_access.APPS_ACCESS_OFF)
        msg = a.feedback.error_occurred.call_args[0][0]
        with mock.patch.object(app, "_startup_log_path", return_value=os.devnull):
            a._on_pipeline_error(msg)
        args = a.app_window.show_action_toast.call_args[0]
        self.assertEqual("Open setting", args[1])
        with mock.patch.object(mic_access, "open_settings") as opener, \
                mock.patch("threading.Thread"):
            args[2]()
        opener.assert_called_once_with(mic_access.PRIVACY_URI)
        a.tray.notify.assert_not_called()

    def test_dead_capture_names_a_privacy_block_instead_of_reconnecting(self):
        a = _bare_app()
        diag = {"privacy": dict(ALLOW, desktop="Deny"),
                "cause": mic_access.DESKTOP_ACCESS_OFF}
        with mock.patch.object(mic_access, "diagnose",
                               return_value=(mic_access.DESKTOP_ACCESS_OFF, diag)), \
                mock.patch("error_reporter.report_error"):
            self.assertTrue(a._handle_dead_capture(0.0))
        self.assertNotIn("reconnected", a.feedback.error_occurred.call_args[0][0])
        events = [c[0][0] for c in a._log_error_event.call_args_list]
        self.assertEqual(["mic_blocked"], events)

    def test_dead_capture_ignores_mute(self):
        # A muted endpoint still delivers samples; zero captured is a dead
        # stream and keeps the reconnect path.
        a = _bare_app()
        with mock.patch.object(mic_access, "diagnose",
                               return_value=(mic_access.MUTED, {"privacy": ALLOW})), \
                mock.patch("audio_engine.service_running", return_value=True):
            a._handle_dead_capture(0.0)
        self.assertIn("reconnected", a.feedback.error_occurred.call_args[0][0])

    def test_fix_watch_reopens_the_mic_and_says_so(self):
        a = _bare_app()
        a.recorder.restart_warm = mock.Mock()
        a._MIC_FIX_WATCH_S = 5.0
        started = []
        with mock.patch.object(mic_access, "open_settings"), \
                mock.patch("threading.Thread",
                           side_effect=lambda target, **kw: types.SimpleNamespace(
                               start=lambda: started.append(target))):
            a._open_mic_fix(mic_access.PRIVACY_URI, mic_access.DESKTOP_ACCESS_OFF, "Mic")
        with mock.patch.object(mic_access, "privacy_state", return_value=ALLOW), \
                mock.patch("time.sleep"):
            started[0]()
        a.recorder.restart_warm.assert_called_once()
        self.assertIn("Dictate again", a.app_window.show_toast.call_args[0][0])

    def test_fix_watch_does_not_claim_success_when_reopen_fails(self):
        a = _bare_app()
        a.recorder.restart_warm = mock.Mock(side_effect=OSError("PortAudio"))
        a._MIC_FIX_WATCH_S = 5.0
        started = []
        with mock.patch.object(mic_access, "open_settings"), \
                mock.patch("threading.Thread",
                           side_effect=lambda target, **kw: types.SimpleNamespace(
                               start=lambda: started.append(target))):
            a._open_mic_fix(mic_access.PRIVACY_URI, mic_access.DESKTOP_ACCESS_OFF, "Mic")
        with mock.patch.object(mic_access, "privacy_state", return_value=ALLOW), \
                mock.patch("time.sleep"):
            started[0]()
        msg = a.app_window.show_toast.call_args[0][0]
        self.assertNotIn("Dictate again", msg)
        self.assertIn("Restart", msg)
        self.assertIn("reopen_error", a._log_error_event.call_args[0][1])


class ReporterTests(unittest.TestCase):
    def test_token_alone_reaches_the_brightlink_intake(self):
        import error_reporter
        sent = {}

        def fake_urlopen(req, timeout=None):
            sent["url"] = req.full_url
            sent["headers"] = dict(req.header_items())
            return mock.MagicMock()

        with mock.patch.object(error_reporter, "_load_contacts_config",
                               return_value=("", "")), \
                mock.patch.object(error_reporter.urllib.request, "urlopen", fake_urlopen), \
                mock.patch.object(error_reporter.threading, "Thread",
                                  side_effect=lambda target, daemon: types.SimpleNamespace(
                                      start=target)):
            error_reporter.report_error("x", token="fake-token")
        self.assertTrue(sent["url"].endswith("/api/log-error"))
        self.assertEqual("Bearer fake-token", sent["headers"]["Authorization"])
        self.assertNotIn("X-app-secret", sent["headers"])

    def test_no_token_and_no_secret_sends_nothing(self):
        import error_reporter
        with mock.patch.object(error_reporter, "_load_contacts_config",
                               return_value=("", "")), \
                mock.patch.object(error_reporter.urllib.request, "urlopen") as op, \
                mock.patch.object(error_reporter.threading, "Thread",
                                  side_effect=lambda target, daemon: types.SimpleNamespace(
                                      start=target)):
            error_reporter.report_error("x")
        op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
