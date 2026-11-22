"""A manual-paste fallback must not lock the clipboard during queued Ctrl+V."""
import unittest
from unittest.mock import Mock, patch

from injector import Injector
from app import WhisperFlowApp


class ClipboardAfterPasteTests(unittest.TestCase):
    def setUp(self):
        self.injector = Injector()
        self.keep = patch.object(Injector, "keep_clipboard", True)
        self.keep.start()
        self.addCleanup(self.keep.stop)

    def test_queued_paste_is_not_interrupted_by_a_second_clipboard_write(self):
        for method in ("clipboard", "terminal-paste"):
            with self.subTest(method=method):
                self.injector.last_method = method
                with patch.object(self.injector, "_clipboard_set") as write:
                    self.assertTrue(self.injector.retain_dictation("words", True))
                    write.assert_not_called()

    def test_direct_input_still_copies_for_manual_recovery(self):
        self.injector.last_method = "WM_CHAR"
        with patch.object(self.injector, "_clipboard_set",
                          return_value=(True, None)) as write:
            self.assertTrue(self.injector.retain_dictation("words", True))
            write.assert_called_once_with("words")

    def test_failure_does_not_trust_a_stale_successful_method(self):
        self.injector.last_method = "clipboard"
        with patch.object(self.injector, "_clipboard_set",
                          return_value=(True, None)) as write:
            self.assertTrue(self.injector.retain_dictation("words", False))
            write.assert_called_once_with("words")

    def test_failed_fallback_copy_is_reported(self):
        with patch.object(self.injector, "_clipboard_set",
                          return_value=(False, None)):
            self.assertFalse(self.injector.retain_dictation("words", False))

    def test_scheduled_restore_requires_explicit_copy(self):
        self.injector.last_method = "clipboard"
        with patch.object(Injector, "keep_clipboard", False), \
                patch.object(self.injector, "_clipboard_set",
                             return_value=(True, None)) as write:
            self.assertTrue(self.injector.retain_dictation("words", True))
            write.assert_called_once_with("words")


class RecoveryReportingTests(unittest.TestCase):
    def test_failed_copy_reports_metadata_without_words_or_exception_text(self):
        for outcome in (False, RuntimeError("private dictated words")):
            app = WhisperFlowApp.__new__(WhisperFlowApp)
            app.injector = Mock()
            app._log_error_event = Mock()
            if isinstance(outcome, Exception):
                app.injector.retain_dictation.side_effect = outcome
            else:
                app.injector.retain_dictation.return_value = outcome
            with patch("builtins.print") as output:
                self.assertFalse(app._retain_dictation_for_recovery("private words", False))
            event, detail = app._log_error_event.call_args.args
            self.assertEqual(event, "clipboard_copy_failed")
            self.assertEqual(detail["chars"], 13)
            self.assertNotIn("private", str(detail))
            self.assertNotIn("private", str(output.call_args_list))

    def test_success_does_not_generate_failure_telemetry(self):
        app = WhisperFlowApp.__new__(WhisperFlowApp)
        app.injector = Mock()
        app.injector.retain_dictation.return_value = True
        app._log_error_event = Mock()
        self.assertTrue(app._retain_dictation_for_recovery("words", True))
        app._log_error_event.assert_not_called()

