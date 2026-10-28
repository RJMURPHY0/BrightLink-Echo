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


class _FakeParakeet:
    """Fails its first load with *first_error*, loads on any later call that
    follows reset_load_failure (the real engine's latch)."""

    def __init__(self, first_error):
        self.first_error = first_error
        self.last_load_error = ""
        self.is_loaded = False
        self._failed = False
        self.loads = 0

    def load_model(self):
        self.loads += 1
        if self._failed:
            return False
        if self.loads == 1:
            self.last_load_error = self.first_error
            self._failed = True
            return False
        self.is_loaded = True
        return True

    def reset_load_failure(self):
        self._failed = False
        self.last_load_error = ""


class ModelRepairTests(unittest.TestCase):
    """A model removed after the startup check (antivirus) is downloaded
    again, as the model_blocked message promises. Before 2026-10-28 the load
    failure latched and nothing re-downloaded until a restart."""

    def _init(self, first_error, present_after_failure):
        a, app_mod = _app_double()
        a.config = types.SimpleNamespace(use_parakeet=True, parakeet_version="v2")
        a.parakeet = _FakeParakeet(first_error)
        a._load_whisper_fallback = lambda: None
        downloads = []
        present = {"now": True}

        def files_present(**kw):
            return present["now"]

        def load_then_vanish():
            ok = _FakeParakeet.load_model(a.parakeet)
            if not ok and a.parakeet.loads == 1:
                present["now"] = present_after_failure
            return ok
        a.parakeet.load_model = load_then_vanish

        def download(version):
            downloads.append(version)
            present["now"] = True
            return True
        a._download_parakeet_with_retry = download
        with mock.patch.object(asr_engine, "model_files_present", files_present), \
                mock.patch.object(asr_engine, "verify_model_files",
                                  lambda **kw: present["now"]):
            a._init_parakeet()
        return a, downloads

    def test_a_model_deleted_before_the_load_is_downloaded_again(self):
        a, downloads = self._init(
            "NoSuchFile: [ONNXRuntimeError] : 3 : NO_SUCHFILE : encoder-model.int8.onnx",
            present_after_failure=False)
        self.assertEqual(["v2"], downloads)
        self.assertTrue(a.parakeet.is_loaded)
        self.assertEqual("parakeet_model_repair", a.events[0][0])

    def test_a_quarantined_runtime_dll_never_re_downloads(self):
        a, downloads = self._init(
            "ImportError: DLL load failed while importing onnxruntime_pybind11_state",
            present_after_failure=False)
        self.assertEqual([], downloads)
        self.assertFalse(a.parakeet.is_loaded)

    def test_intact_files_that_fail_to_load_are_not_downloaded_again(self):
        a, downloads = self._init("RuntimeError: something else",
                                  present_after_failure=True)
        self.assertEqual([], downloads)


class LoadLatchTests(unittest.TestCase):
    def test_reset_lets_a_failed_engine_load_again(self):
        eng = asr_engine.ParakeetTranscriber.__new__(asr_engine.ParakeetTranscriber)
        eng._load_lock = __import__("threading").Lock()
        eng._load_failed = True
        eng.last_load_error = "x"
        eng.reset_load_failure()
        self.assertFalse(eng._load_failed)
        self.assertEqual("", eng.last_load_error)


if __name__ == "__main__":
    unittest.main()
