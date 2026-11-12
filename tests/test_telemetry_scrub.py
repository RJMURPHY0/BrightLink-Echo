"""Diagnostics reports carry kinds and categories, never names, and stop
entirely when Send Diagnostics is off. No network: the Supabase client is
replaced by a recorder of what would have been inserted."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telemetry_scrub as ts  # noqa: E402


class DeviceKindTests(unittest.TestCase):
    def test_kinds(self):
        cases = {
            "Microphone Array (Realtek(R) Audio)": "built-in array",
            "Microphone (C922 Pro Stream Webcam)": "webcam",
            "Microphone (Logi USB Headset)": "headset",
            "Headset (Sam's AirPods Pro)": "headset",
            "Microphone (Yeti Stereo Microphone)": "usb mic",
            "Stereo Mix (Realtek HD Audio Stereo input)": "virtual",
            "Microphone (Realtek HD Audio Mic input)": "built-in",
            "Primary Sound Capture Driver": "default",
            "Sam's special mic": "other",
            "": "",
        }
        for name, kind in cases.items():
            self.assertEqual(kind, ts.device_kind(name), name)

    def test_an_owner_name_never_survives(self):
        self.assertNotIn("Sam", ts.device_kind("Sam's AirPods"))


class AppKindTests(unittest.TestCase):
    def test_categories(self):
        self.assertEqual("browser", ts.app_kind("chrome.exe"))
        self.assertEqual("office", ts.app_kind("WINWORD.EXE"))
        self.assertEqual("chat", ts.app_kind("ms-teams.exe"))
        self.assertEqual("terminal", ts.app_kind("WindowsTerminal.exe"))
        self.assertEqual("other", ts.app_kind("acme-crm.exe"))
        self.assertEqual("", ts.app_kind("", ""))

    def test_window_families(self):
        self.assertEqual("chromium", ts.window_family("Chrome_WidgetWin_1"))
        self.assertEqual("office", ts.window_family("OpusApp"))
        self.assertEqual("other", ts.window_family("SomeAppMainWnd"))


class LogTailTests(unittest.TestCase):
    LOG = "\n".join([
        "[2026-11-12 15:00:57] [Recorder] Enumerated 2 input device(s): "
        "['Microphone Array (Realtek(R) Audio)', 'Headset (Sam AirPods)']",
        "[2026-11-12 15:00:57] [Recorder] Auto-detect using 'Headset (Sam AirPods)' (#5)",
        "[2026-11-12 15:00:57] [Recorder] Using input device 'Headset (Sam AirPods)' (#5)",
        "[2026-11-12 15:00:57] [Recorder] Warm mic stream open (Headset (Sam AirPods), 16000 Hz).",
        "[2026-11-12 15:01:01] [Recorder] Recording started instantly (warm, "
        "Headset (Sam AirPods), 16000 Hz, seed 800ms).",
        "[2026-11-12 15:01:02] [App] Saved C:\\Users\\sam.jones\\AppData\\Roaming\\x.json",
        "[2026-11-12 15:01:03] [Auth] Signed in as sam@example.com",
        "[2026-11-12 15:01:04] [Stop] 2000 ms for 10.0s tail",
    ])

    def test_no_mic_name_user_folder_or_email_survives(self):
        out = ts.scrub_log_text(self.LOG)
        for secret in ("Sam", "sam.jones", "sam@example.com", "AirPods", "Realtek"):
            self.assertNotIn(secret, out, secret)
        self.assertIn("[Stop] 2000 ms for 10.0s tail", out)
        self.assertIn("16000 Hz", out)
        self.assertEqual(len(self.LOG.splitlines()), len(out.splitlines()))


class ScrubEventTests(unittest.TestCase):
    def test_top_level_identifiers_become_categories(self):
        row = ts.scrub_event({
            "event_type": "inject_failed",
            "app_name": "Google Chrome", "app_exe": "chrome.exe",
            "window_class": "Chrome_WidgetWin_1",
            "detail": {"device": "Headset (Sam AirPods)",
                       "fg_exe": "chrome.exe", "fg_class": "Chrome_WidgetWin_1",
                       "exception": r"C:\Users\sam.jones\x failed for sam@example.com",
                       "privacy": {"device": "Allow"}, "peak": 0.01},
        })
        self.assertNotIn("app_name", row)
        self.assertNotIn("app_exe", row)
        self.assertNotIn("window_class", row)
        d = row["detail"]
        self.assertEqual("browser", d["app_kind"])
        self.assertEqual("chromium", d["window_family"])
        self.assertEqual("headset", d["device"])
        self.assertEqual("browser", d["fg_app_kind"])
        self.assertEqual("chromium", d["fg_window_family"])
        self.assertNotIn("fg_exe", d)
        self.assertNotIn("sam", d["exception"].lower())
        self.assertEqual({"device": "Allow"}, d["privacy"])
        self.assertEqual(0.01, d["peak"])

    def test_every_payload_key_is_known(self):
        # A new top-level field must be added here on purpose.
        row = ts.scrub_event({"event_type": "x", "created_at": "t",
                              "app_version": "1", "user_id": "u",
                              "transcription_created_at": "t2", "detail": {}})
        self.assertEqual({"event_type", "created_at", "app_version", "user_id",
                          "transcription_created_at", "detail"}, set(row))


class SendDiagnosticsSwitchTests(unittest.TestCase):
    def _logger(self):
        import supabase_client
        lg = supabase_client.SupabaseLogger(url="https://x.supabase.co", key="k")
        lg._user_id = "00000000-0000-0000-0000-000000000001"
        sent = []

        class _Table:
            def insert(self, payload, returning=None):
                sent.append(payload)
                return self

            def execute(self):
                return None

        lg._get_client = lambda: mock.Mock(table=lambda _n: _Table())
        return lg, sent

    def test_rows_are_scrubbed_on_the_way_out(self):
        lg, sent = self._logger()
        with mock.patch("threading.Thread") as T, mock.patch("builtins.print"):
            T.side_effect = lambda target=None, **kw: mock.Mock(start=target)
            lg.log_error_event("mic_silent", {"device": "Headset (Sam AirPods)"},
                               app_name="Slack", app_exe="slack.exe",
                               window_class="Chrome_WidgetWin_1")
            self.assertTrue(lg.insert_error_event_now(
                "app_crashed", {"log_tail": "[Recorder] Using input device 'Sam mic'"}))
        self.assertEqual(2, len(sent))
        self.assertNotIn("app_exe", sent[0])
        self.assertEqual("headset", sent[0]["detail"]["device"])
        self.assertEqual("chat", sent[0]["detail"]["app_kind"])
        self.assertNotIn("Sam", sent[1]["detail"]["log_tail"])

    def test_off_sends_nothing_and_drops_crash_reports(self):
        lg, sent = self._logger()
        with mock.patch("builtins.print"):
            lg.set_diagnostics_enabled(False)
            lg.log_error_event("mic_silent", {"peak": 0})
            # True = handled (dropped on purpose), so crash_watch does not retry.
            self.assertTrue(lg.insert_error_event_now("app_crashed", {"cause": "x"}))
        self.assertEqual([], sent)

    def test_on_by_default_and_setting_defaults_on(self):
        import config
        lg, _ = self._logger()
        self.assertTrue(lg.diagnostics_enabled)
        self.assertTrue(config.Config().send_diagnostics)


class ErrorReporterTests(unittest.TestCase):
    """The BrightLink error-log copy obeys the same switch and scrubbing."""

    def _capture(self):
        import error_reporter
        sent = []
        started = []

        class _T:
            def __init__(self, target=None, daemon=None, **kw):
                self.target = target

            def start(self):
                started.append(1)
                self.target()

        return error_reporter, sent, started, _T

    def test_off_sends_nothing(self):
        er, sent, started, _T = self._capture()
        with mock.patch.object(er, "_ENABLED", False), \
                mock.patch.object(er.threading, "Thread", _T), \
                mock.patch("builtins.print"):
            er.report_error("x", {"device": "Sam's AirPods"}, token="t")
        self.assertEqual([], started)

    def test_on_scrubs_message_and_context(self):
        er, sent, started, _T = self._capture()

        def fake_urlopen(req, timeout=0):
            import json
            sent.append(json.loads(req.data.decode()))

        with mock.patch.object(er, "_ENABLED", True), \
                mock.patch.object(er.threading, "Thread", _T), \
                mock.patch.object(er, "_load_contacts_config", lambda: ("", "")), \
                mock.patch.object(er.urllib.request, "urlopen", fake_urlopen):
            er.report_error(r"Failed at C:\Users\sam.jones\x for sam@example.com",
                            {"device": "Headset (Sam AirPods)", "version": "1.8"},
                            token="t")
        self.assertEqual(1, len(sent))
        body = sent[0]
        self.assertNotIn("sam", body["message"].lower())
        self.assertEqual("headset", body["context"]["device"])
        self.assertEqual("1.8", body["context"]["version"])


if __name__ == "__main__":
    unittest.main()
