"""AI refine through the BrightLink relay.

Released builds hold no model key. A signed-in user's refine goes to
POST {relay}/api/whisper/ai with their Supabase token, and the server picks the
model. These tests pin the payload contract and that every failure (signed out,
401, 403, 429, server error, network) hands back the ORIGINAL text, never an
empty string or an exception, with a plain reason for the popup.

Pure stubs, no network. Safe to run anywhere.
"""
import io
import json
import os
import sys
import threading
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_refiner
from ai_refiner import AIRefiner

TEXT = "so we should ship it on tuesday and tell the team"


class _Resp:
    def __init__(self, body: dict):
        self._raw = json.dumps(body).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code: int):
    return urllib.error.HTTPError("https://x/api/whisper/ai", code, "err", {},
                                  io.BytesIO(b'{"error":"no"}'))


def _refiner(token="tok-123"):
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "", "ANTHROPIC_API_KEY": ""}):
        return AIRefiner(token_provider=lambda: token,
                         signed_in=lambda: bool(token))


class RelayPayloadTests(unittest.TestCase):
    def test_sends_bearer_token_and_chat_to_the_relay(self):
        r = _refiner()
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _Resp({"text": "So we should ship it on Tuesday and tell the team."})

        with mock.patch.object(ai_refiner.urllib.request, "urlopen", fake_urlopen), \
                mock.patch.dict(os.environ, {"BRIGHTLINK_APP_URL": ""}):
            out = r.refine(TEXT, mode="punctuation")

        self.assertEqual(out, "So we should ship it on Tuesday and tell the team.")
        self.assertEqual(seen["url"], "https://app.brightlink.io/api/whisper/ai")
        self.assertEqual(seen["auth"], "Bearer tok-123")
        body = seen["body"]
        self.assertEqual(set(body), {"system", "user", "max_tokens", "temperature"})
        self.assertIn(TEXT, body["user"])
        self.assertTrue(body["system"])
        self.assertEqual(body["temperature"], 0)
        self.assertGreaterEqual(body["max_tokens"], 1024)
        # The server picks the model: the client never names one.
        self.assertNotIn("model", json.dumps(body))
        self.assertEqual(r.relay_failure_message(), "")

    def test_relay_url_is_overridable_for_dev(self):
        with mock.patch.dict(os.environ, {"BRIGHTLINK_APP_URL": "http://localhost:3006/"}):
            self.assertEqual(ai_refiner.relay_url(), "http://localhost:3006")

    def test_a_released_build_ignores_the_override(self):
        # Security review 2026-10-27: the user's Supabase token goes to this
        # URL, so a frozen build never takes it from the environment.
        with mock.patch.dict(os.environ, {"BRIGHTLINK_APP_URL": "https://evil.example"}),                 mock.patch.object(ai_refiner.sys, "frozen", True, create=True):
            self.assertEqual(ai_refiner.relay_url(), ai_refiner.DEFAULT_RELAY_URL)

    def test_the_override_must_be_https_or_this_machine(self):
        for url in ("http://evil.example", "ftp://localhost", "file:///c:/x", "not a url",
                    "http://localhost.evil.example"):
            with mock.patch.dict(os.environ, {"BRIGHTLINK_APP_URL": url}):
                self.assertEqual(ai_refiner.relay_url(), ai_refiner.DEFAULT_RELAY_URL, msg=url)
        with mock.patch.dict(os.environ, {"BRIGHTLINK_APP_URL": "https://staging.example/"}):
            self.assertEqual(ai_refiner.relay_url(), "https://staging.example")

    def test_local_key_wins_over_the_relay(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "", "ANTHROPIC_API_KEY": ""}):
            r = AIRefiner(openrouter_api_key="sk-or-dev", token_provider=lambda: "tok")
        r._refine_via_openrouter = lambda *a, **k: "LOCAL"
        with mock.patch.object(ai_refiner.urllib.request, "urlopen",
                               side_effect=AssertionError("relay must not be called")):
            self.assertEqual(r.refine(TEXT), "LOCAL")

    def test_available_when_signed_in_without_any_key(self):
        self.assertTrue(_refiner().is_available)
        self.assertFalse(_refiner(token="").is_available)

    def test_is_available_never_reads_the_token(self):
        # is_available runs on the dictation path; reading the token may
        # refresh the session over the network.
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "", "ANTHROPIC_API_KEY": ""}):
            r = AIRefiner(token_provider=mock.Mock(side_effect=AssertionError("read")),
                          signed_in=lambda: True)
        self.assertTrue(r.is_available)

    def test_suggest_mishearings_uses_the_relay(self):
        r = _refiner()
        with mock.patch.object(ai_refiner.urllib.request, "urlopen",
                               return_value=_Resp({"text": "the cell\nver sell"})):
            self.assertEqual(r.suggest_mishearings("Vercel"), ["the cell", "ver sell"])


class RelayFailureTests(unittest.TestCase):
    def _assert_original(self, side_effect, reason, message_part):
        r = _refiner()
        with mock.patch.object(ai_refiner.urllib.request, "urlopen", side_effect=side_effect):
            self.assertEqual(r.refine(TEXT), TEXT)
        self.assertEqual(r.last_relay_error, reason)
        self.assertIn(message_part, r.relay_failure_message())

    def test_401_returns_original(self):
        self._assert_original(_http_error(401), "unauthorised", "Sign in again")

    def test_403_returns_original(self):
        self._assert_original(_http_error(403), "restricted", "switched off")

    def test_429_returns_original(self):
        self._assert_original(_http_error(429), "rate_limited", "Too many")

    def test_502_returns_original(self):
        self._assert_original(_http_error(502), "http_502", "unavailable")

    def test_network_error_returns_original(self):
        self._assert_original(urllib.error.URLError("offline"), "network", "connection")

    def test_timeout_returns_original(self):
        self._assert_original(TimeoutError("slow"), "network", "connection")

    def test_signed_out_never_calls_the_relay(self):
        r = _refiner(token="")
        with mock.patch.object(ai_refiner.urllib.request, "urlopen",
                               side_effect=AssertionError("must not call")):
            self.assertEqual(r.refine(TEXT), TEXT)
        self.assertIn("Sign in", r.relay_failure_message())

    def test_context_fix_keeps_original_on_failure(self):
        r = _refiner()
        with mock.patch.object(ai_refiner.urllib.request, "urlopen",
                               side_effect=_http_error(429)):
            self.assertEqual(r.context_fix(TEXT), TEXT)

    def test_a_failure_on_one_thread_is_not_reported_on_another(self):
        r = _refiner()
        with mock.patch.object(ai_refiner.urllib.request, "urlopen",
                               side_effect=_http_error(429)):
            t = threading.Thread(target=lambda: r.refine(TEXT))
            t.start()
            t.join()
        self.assertEqual(r.relay_failure_message(), "")


if __name__ == "__main__":
    unittest.main()
