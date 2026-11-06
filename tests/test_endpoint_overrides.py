"""Hardening: shipped builds ignore endpoint overrides; source runs need https."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import error_reporter
import voice_training


class VoiceTrainingBaseUrlTests(unittest.TestCase):
    def _url(self, env, frozen):
        with mock.patch.dict(os.environ, {"FTC_TRANSCRIBE_URL": env}), \
                mock.patch.object(sys, "frozen", frozen, create=True):
            return voice_training.base_url()

    def test_frozen_ignores_override(self):
        self.assertEqual(self._url("https://example.test", True),
                         voice_training.DEFAULT_BASE_URL)

    def test_source_accepts_https(self):
        self.assertEqual(self._url("https://example.test/", False), "https://example.test")

    def test_source_accepts_loopback_http(self):
        self.assertEqual(self._url("http://localhost:3000", False), "http://localhost:3000")

    def test_source_refuses_plain_http_elsewhere(self):
        self.assertEqual(self._url("http://example.test", False),
                         voice_training.DEFAULT_BASE_URL)

    def test_no_override_uses_default(self):
        self.assertEqual(self._url("", False), voice_training.DEFAULT_BASE_URL)


class ErrorReporterUrlTests(unittest.TestCase):
    def _safe(self, url, frozen):
        with mock.patch.object(sys, "frozen", frozen, create=True):
            return error_reporter._safe_api_url(url)

    def test_frozen_ignores_configured_host(self):
        self.assertEqual(self._safe("https://example.test", True), "")

    def test_source_https_kept(self):
        self.assertEqual(self._safe("https://example.test", False), "https://example.test")

    def test_source_plain_http_refused(self):
        self.assertEqual(self._safe("http://example.test", False), "")

    def test_source_loopback_http_kept(self):
        self.assertEqual(self._safe("http://127.0.0.1:8080", False), "http://127.0.0.1:8080")

    def test_empty_stays_empty(self):
        self.assertEqual(self._safe("", True), "")


if __name__ == "__main__":
    unittest.main()
