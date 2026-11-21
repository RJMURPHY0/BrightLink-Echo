"""Keep the processed mic endpoint and its 16 kHz voice-isolation path."""
import unittest
import time
from unittest.mock import Mock, patch

import recorder as R


class CaptureProcessingTests(unittest.TestCase):
    def setUp(self):
        self.rec = R.Recorder()
        self.apis = [{"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}]
        self.devices = [
            {"name": "Microphone Array", "hostapi": api,
             "max_input_channels": 2, "default_samplerate": 48000}
            for api in (0, 1)]

    def test_shared_endpoint_wins_with_legacy_fallback(self):
        with patch.object(R.sd, "query_devices", return_value=self.devices), \
                patch.object(R.sd, "query_hostapis", return_value=self.apis), \
                patch.object(self.rec, "_get_default_input_index", return_value=0):
            self.assertEqual(self.rec._candidate_device_indices(), [1, 0])

    def test_failed_shared_endpoint_tries_same_physical_microphone(self):
        stream = Mock()
        with patch.object(R.sd, "query_devices", side_effect=lambda idx=None: (
                self.devices if idx is None else self.devices[idx])), \
                patch.object(R.sd, "query_hostapis", return_value=self.apis), \
                patch.object(self.rec, "_get_default_input_index", return_value=0), \
                patch.object(self.rec, "_open_stream_with_rates",
                             side_effect=[RuntimeError("unavailable"), stream]) as opened:
            self.assertIs(self.rec._open_best_input_stream(), stream)
            self.assertEqual([c.args[0] for c in opened.call_args_list], [1, 0])

    def test_shared_capture_requests_conversion_without_exclusive_access(self):
        settings = object()
        with patch.object(R.sd, "query_devices", return_value=self.devices[1]), \
                patch.object(R.sd, "query_hostapis", return_value=self.apis[1]), \
                patch.object(R.sd, "WasapiSettings", return_value=settings) as wasapi, \
                patch.object(R.sd, "InputStream") as opened:
            self.rec._open_stream_with_rates(1)
            wasapi.assert_called_once_with(exclusive=False, auto_convert=True)
            self.assertEqual(opened.call_args.kwargs["samplerate"], 16000)
            self.assertIs(opened.call_args.kwargs["extra_settings"], settings)

    def test_legacy_capture_has_no_wasapi_settings(self):
        with patch.object(R.sd, "query_devices", return_value=self.devices[0]), \
                patch.object(R.sd, "query_hostapis", return_value=self.apis[0]), \
                patch.object(R.sd, "InputStream") as opened:
            self.rec._open_stream_with_rates(0)
            self.assertNotIn("extra_settings", opened.call_args.kwargs)

    def test_native_rate_still_available_if_16k_open_fails(self):
        with patch.object(R.sd, "query_devices", return_value=self.devices[1]), \
                patch.object(R.sd, "query_hostapis", return_value=self.apis[1]), \
                patch.object(R.sd, "InputStream", side_effect=[ValueError("format"), Mock()]) as opened:
            self.rec._open_stream_with_rates(1)
            self.assertEqual([c.kwargs["samplerate"] for c in opened.call_args_list],
                             [16000, 48000])
            self.assertEqual(self.rec.active_sample_rate, 48000)

    def test_known_processed_mics_compete_with_external_hardware(self):
        for name in ("Microphone (NVIDIA Broadcast)", "Krisp Microphone",
                     "Virtual Microphone (NVIDIA Broadcast)"):
            self.assertEqual(self.rec._auto_rank(name), 0)
        for name in ("Stereo Mix", "CABLE Output (VB-Audio)", "Virtual Loopback",
                     "Microphone Loopback (Krisp)"):
            self.assertEqual(self.rec._auto_rank(name), 4)

    def test_quiet_release_does_not_calculate_speech_percentile(self):
        now = time.monotonic()
        self.rec._recording = True
        self.rec._release_ts = now
        self.rec._tail_marks.append((now - 0.02, 0.02, 0.0002, False))
        with patch.object(self.rec, "_speech_level", side_effect=AssertionError("stop work")):
            self.rec._await_release_tail()
        self.assertEqual(self.rec.last_tail_ms, 0)
