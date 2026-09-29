"""A failed Parakeet download is retried, not given up on for the session.

Found 2026-09-29 on a fresh install: the single first-run download attempt
failed (empty model folder, no .part file) and the app ran the whole day on
whisper small.en, which is markedly less accurate, with nothing on screen or
in telemetry to say so. These pin that the download is retried, that the
failure is reported, and that the retries go quiet after the third report.
"""

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asr_engine


def _app_double():
    import app as app_mod
    a = app_mod.WhisperFlowApp.__new__(app_mod.WhisperFlowApp)
    a.config = types.SimpleNamespace(use_parakeet=True)
    a.events = []
    a._log_error_event = lambda ev, detail, **kw: a.events.append((ev, detail))
    return a, app_mod


class DownloadRetryTests(unittest.TestCase):

    def _run(self, outcomes):
        a, app_mod = _app_double()
        calls = []

        def fake_download(progress=None, version="v2", error_out=None, **kw):
            ok = outcomes[len(calls)]
            calls.append(ok)
            if not ok and error_out is not None:
                error_out.append("URLError: <urlopen error timed out>")
            return ok

        sleeps = []
        with mock.patch.object(asr_engine, "download_model", fake_download), \
                mock.patch.object(asr_engine, "model_files_present",
                                  lambda **kw: False), \
                mock.patch.object(app_mod.time, "sleep", sleeps.append):
            result = a._download_parakeet_with_retry("v2")
        return result, calls, sleeps, a.events

    def test_a_failed_download_is_retried_until_it_succeeds(self):
        result, calls, sleeps, events = self._run([False, False, True])
        self.assertTrue(result)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [30, 120])

    def test_the_failure_and_the_recovery_are_reported(self):
        _, _, _, events = self._run([False, True])
        self.assertEqual(events[0], ("parakeet_download_failed", {
            "attempt": 1, "error": "URLError: <urlopen error timed out>"}))
        self.assertEqual(events[1], ("parakeet_download_recovered",
                                     {"attempt": 2}))

    def test_retries_settle_into_a_slow_quiet_cadence(self):
        result, calls, sleeps, events = self._run([False] * 6 + [True])
        self.assertTrue(result)
        self.assertEqual(sleeps, [30, 120, 600, 1800, 1800, 1800])
        failed = [e for e in events if e[0] == "parakeet_download_failed"]
        self.assertEqual(len(failed), 3)

    def test_a_first_attempt_success_reports_nothing(self):
        result, calls, sleeps, events = self._run([True])
        self.assertTrue(result)
        self.assertEqual((sleeps, events), ([], []))


if __name__ == "__main__":
    unittest.main()
