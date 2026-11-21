import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from spoken_feedback import correction_draft, SpokenFeedback


class DraftTests(unittest.TestCase):
    def test_exact_replacement_never_calls_ai(self):
        ai = Mock()
        self.assertEqual(correction_draft("Meet Brian tomorrow.", "Replace Brian with Ryan.", ai),
                         "Meet Ryan tomorrow.")
        ai.refine.assert_not_called()

    def test_ambiguous_or_partial_match_refused(self):
        for text in ("Brian saw Brian", "Brianna arrived"):
            with self.assertRaises(ValueError):
                correction_draft(text, "replace Brian with Ryan", Mock())

    def test_free_speech_failure_does_not_become_a_correction(self):
        ai = Mock(is_available=True)
        ai.refine.return_value = "Hello Ryan"
        with self.assertRaises(ValueError):
            correction_draft("Hello Ryan", "That name is wrong", ai)

    def test_offline_explicit_replacement_still_works(self):
        ai = Mock(is_available=False)
        self.assertEqual(correction_draft("Hello Brian", "replace Brian with Ryan", ai), "Hello Ryan")
        with self.assertRaises(ValueError):
            correction_draft("Hello Brian", "It got the name wrong", ai)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.app = Mock()
        self.app._auth.user_id = "account-a"
        self.app.popup._mic_recording = False
        self.app._not_dictating.return_value = True
        self.app.db.can_send_feedback = True
        self.app.db.get_cached_history.return_value = [{"transcribed_text": "Hello Brian"}]
        self.app.recorder.read_aux_audio.return_value = None
        self.app.config.live_captions = False
        self.flow = SpokenFeedback(self.app)
        self.addCleanup(self.flow.cancel)

    def test_start_pins_account_and_suspends_other_capture(self):
        self.flow.toggle()
        self.assertTrue(self.flow.active)
        self.app.feedback.recording_started.assert_called_once()
        self.assertEqual(self.flow.target[0], "account-a")
        self.app.hotkey_manager.suspend.assert_called_once()
        self.app.refine_hotkey_manager.suspend.assert_called_once()
        self.flow.cancel()
        self.app.recorder.stop_aux_capture.assert_called_once()
        self.app.feedback.recording_stopped.assert_called_once()
        self.app.feedback.transcription_complete.assert_called_once()
        self.assertIsNone(self.flow.target)
        self.app.hotkey_manager.resume.assert_called_once()

    def test_feedback_instruction_stays_visible_even_with_live_captions(self):
        self.flow.toggle()
        self.app.popup.show_status.assert_called_with(
            "Feedback recording. Alt+F to stop", recording=True)

    def test_no_main_or_popup_recording_overlap(self):
        self.app.popup._mic_recording = True
        self.flow.toggle()
        self.app.recorder.start_aux_capture.assert_not_called()
        self.app.popup._mic_recording = False
        self.app._not_dictating.return_value = False
        self.flow.toggle()
        self.app.recorder.start_aux_capture.assert_not_called()

    def test_mic_failure_restores_hotkeys(self):
        self.app.recorder.start_aux_capture.return_value = False
        self.flow.toggle()
        self.assertFalse(self.flow.active)
        self.app.hotkey_manager.resume.assert_called_once()

    def test_empty_history_allows_general_spoken_feedback(self):
        self.app.db.get_cached_history.return_value = []
        self.flow.toggle()
        self.assertTrue(self.flow.active)
        self.assertEqual(self.flow.target[1], {})

    def test_free_speech_is_reviewed_before_cloud_drafting(self):
        self.flow.toggle()
        self.app.recorder.stop_aux_capture.return_value = [1, 2, 3]
        self.app._fast_engine.return_value.transcribe.return_value = "Please add shortcut help"
        queued = []
        self.app.app_window._ui_after.side_effect = lambda delay, fn: queued.append(fn)
        with patch("spoken_feedback.threading.Thread") as thread:
            thread.side_effect = lambda **kw: SimpleNamespace(start=kw["target"])
            self.flow.stop()
        queued[0]()
        self.app.ai_refiner.refine.assert_not_called()
        args = self.app.app_window._open_spoken_feedback.call_args.args
        self.assertEqual(args[1], "Hello Brian")
        self.assertEqual(args[2], "Please add shortcut help")

    def test_stop_failure_restores_captions_and_opens_typed_fallback(self):
        self.flow.toggle()
        self.app.recorder.stop_aux_capture.side_effect = RuntimeError("device disconnected")
        self.flow.stop()
        self.assertFalse(self.flow.active)
        self.app.popup.set_captions_enabled.assert_called_with(False)
        self.app.hotkey_manager.resume.assert_called_once()
        self.assertIn("Type your feedback", self.app.app_window._open_spoken_feedback.call_args.kwargs["error"])

    def test_signed_out_does_not_capture(self):
        self.app.db.can_send_feedback = False
        self.flow.toggle()
        self.app.recorder.start_aux_capture.assert_not_called()

    def test_account_change_discards_completed_draft(self):
        self.flow.toggle()
        self.app.recorder.stop_aux_capture.return_value = [1, 2, 3]
        self.app._fast_engine.return_value.transcribe.return_value = "replace Brian with Ryan"
        queued = []
        self.app.app_window._ui_after.side_effect = lambda delay, fn: queued.append(fn)
        with patch("spoken_feedback.threading.Thread") as thread:
            thread.side_effect = lambda **kw: SimpleNamespace(start=kw["target"])
            self.flow.stop()
        self.app._auth.user_id = "account-b"
        queued[0]()
        self.app.app_window._open_spoken_feedback.assert_not_called()
        self.assertFalse(self.flow.busy)
        self.app.hotkey_manager.resume.assert_called_once()

    def test_cancel_invalidates_worker_completion(self):
        self.flow.toggle()
        self.app.recorder.stop_aux_capture.return_value = [1, 2, 3]
        self.app._fast_engine.return_value.transcribe.return_value = "replace Brian with Ryan"
        queued = []
        self.app.app_window._ui_after.side_effect = lambda delay, fn: queued.append(fn)
        with patch("spoken_feedback.threading.Thread") as thread:
            thread.side_effect = lambda **kw: SimpleNamespace(start=kw["target"])
            self.flow.stop()
        self.flow.cancel()
        queued[0]()
        self.app.app_window._open_spoken_feedback.assert_not_called()

    def test_cancel_during_asr_never_calls_the_cloud_refiner(self):
        self.flow.toggle()
        self.app.recorder.stop_aux_capture.return_value = [1, 2, 3]
        def transcribe(*args, **kwargs):
            self.flow.cancel()
            return "The name is wrong"
        self.app._fast_engine.return_value.transcribe.side_effect = transcribe
        with patch("spoken_feedback.threading.Thread") as thread:
            thread.side_effect = lambda **kw: SimpleNamespace(start=kw["target"])
            self.flow.stop()
        self.app.ai_refiner.refine.assert_not_called()
