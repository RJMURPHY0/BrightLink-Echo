"""Guards for speech_health — the classifier that turns a silent speech-engine
failure into a visible, logged cause.

Each case here encodes a real way the engine dies on a user's machine:
antivirus quarantining a runtime DLL, antivirus removing the downloaded model,
a firewall blocking the download. The whole point of the module is that these
stop being invisible, so the classification must not drift.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import brand
import speech_health as sh


class CauseCodeStabilityTests(unittest.TestCase):
    """The cause codes are logged to the fleet error-events table and matched
    in its dashboard. Renaming one silently breaks every saved query, so the
    exact strings are pinned here."""

    def test_codes_are_exact(self):
        self.assertEqual(sh.OK, "ok")
        self.assertEqual(sh.RUNTIME_BLOCKED, "runtime_blocked")
        self.assertEqual(sh.MODEL_BLOCKED, "model_blocked")
        self.assertEqual(sh.DOWNLOAD_BLOCKED, "download_blocked")
        self.assertEqual(sh.MODEL_MISSING, "model_missing")
        self.assertEqual(sh.UNKNOWN, "unknown")


class LoadErrorClassificationTests(unittest.TestCase):

    def test_onnxruntime_dll_quarantined_is_runtime_blocked(self):
        # The exact text Python raises when onnxruntime's native DLL has been
        # quarantined — the "UI is there but speaking does nothing" signature.
        exc = ("ImportError: DLL load failed while importing "
               "onnxruntime_pybind11_state: The specified module could not be "
               "found.")
        self.assertEqual(
            sh.classify_load_error(exc, files_present=True), sh.RUNTIME_BLOCKED)

    def test_runtime_dll_wins_even_when_model_absent(self):
        # A quarantined runtime can't load any model, present or not.
        exc = "OSError: [WinError 126] The specified module could not be found"
        self.assertEqual(
            sh.classify_load_error(exc, files_present=False), sh.RUNTIME_BLOCKED)

    def test_whisper_runtime_removed_is_runtime_blocked(self):
        for exc in ("ModuleNotFoundError: No module named 'ctranslate2'",
                    "ModuleNotFoundError: No module named 'faster_whisper'",
                    "ImportError: No module named 'onnx_asr'"):
            self.assertEqual(
                sh.classify_load_error(exc, files_present=True),
                sh.RUNTIME_BLOCKED, exc)

    def test_model_present_but_load_fails_is_model_blocked(self):
        exc = "RuntimeError: failed to load model: invalid protobuf"
        self.assertEqual(
            sh.classify_load_error(exc, files_present=True), sh.MODEL_BLOCKED)

    def test_no_files_no_runtime_error_is_benign_missing(self):
        # First run before the download has finished: NOT a block — whisper or
        # a retry takes over, so the user must not be alarmed.
        c = sh.classify_load_error("", files_present=False)
        self.assertEqual(c, sh.MODEL_MISSING)
        self.assertFalse(sh.is_blocked(c))


class AntivirusSignatureTests(unittest.TestCase):
    """WinError 225 (ERROR_VIRUS_INFECTED) and 226 (ERROR_VIRUS_DELETED) are
    Windows saying antivirus stopped the file. 2, 5 and 193 are not (audit
    2026-10-28)."""

    VIRUS_INFECTED = ("OSError: [WinError 225] Operation did not complete "
                      "successfully because the file contains a virus or "
                      "potentially unwanted software")
    VIRUS_DELETED = ("OSError: [WinError 226] This file contains a virus or "
                     "potentially unwanted software and cannot be opened.")

    def test_225_and_226_are_antivirus(self):
        for exc in (self.VIRUS_INFECTED, self.VIRUS_DELETED):
            self.assertTrue(sh.is_antivirus_error(exc), exc)

    def test_a_dll_antivirus_blocked_is_runtime_blocked(self):
        exc = ("ImportError: DLL load failed while importing "
               "onnxruntime_pybind11_state: " + self.VIRUS_INFECTED)
        self.assertEqual(sh.RUNTIME_BLOCKED,
                         sh.classify_load_error(exc, files_present=True))

    def test_a_model_antivirus_deleted_is_never_benign_missing(self):
        # 226 removes the file, so it is "not on disk", but no first-run
        # download is on its way: the user must be told.
        c = sh.classify_load_error(self.VIRUS_DELETED, files_present=False)
        self.assertEqual(sh.MODEL_BLOCKED, c)
        self.assertTrue(sh.is_blocked(c))

    def test_generic_codes_are_not_antivirus(self):
        for exc in ("FileNotFoundError: [WinError 2] The system cannot find "
                    "the file specified",
                    "PermissionError: [WinError 5] Access is denied",
                    "OSError: [WinError 193] %1 is not a valid Win32 application"):
            self.assertFalse(sh.is_antivirus_error(exc), exc)
            self.assertNotEqual(sh.RUNTIME_BLOCKED,
                                sh.classify_load_error(exc, files_present=True), exc)
        self.assertEqual(sh.MODEL_MISSING, sh.classify_load_error(
            "FileNotFoundError: [WinError 2] The system cannot find the file",
            files_present=False))

    def test_log_detail_says_when_windows_confirmed_antivirus(self):
        self.assertTrue(sh.log_detail(sh.MODEL_BLOCKED,
                                      exc_text=self.VIRUS_DELETED)["antivirus"])
        self.assertFalse(sh.log_detail(sh.MODEL_BLOCKED,
                                       exc_text="[WinError 5] Access is denied")["antivirus"])


class DownloadErrorClassificationTests(unittest.TestCase):

    def test_download_failure_is_always_blocking(self):
        c = sh.classify_download_error("URLError: timed out")
        self.assertEqual(c, sh.DOWNLOAD_BLOCKED)
        self.assertTrue(sh.is_blocked(c))

    def test_network_failure_is_not_flagged_as_tamper(self):
        for err in ("URLError: timed out",
                    "ssl.SSLError: certificate verify failed",
                    "socket.gaierror: getaddrinfo failed",
                    "ConnectionRefusedError: connection refused"):
            self.assertFalse(sh.download_error_is_tamper(err), err)

    def test_hash_or_size_mismatch_reads_as_tamper(self):
        # Antivirus stripping/rewriting the file mid-download shows up as a
        # hash or size mismatch — the fix is an exclusion, not "check wifi".
        for err in ("IOError: encoder.onnx failed its SHA-256 check — discarded",
                    "IOError: decoder.onnx download truncated (12 of 340 bytes)"):
            self.assertTrue(sh.download_error_is_tamper(err), err)

    def test_mismatch_plus_network_is_treated_as_network(self):
        # A truncation caused by a dropped connection is a network problem,
        # not tampering — don't send the user chasing an AV exclusion.
        self.assertFalse(sh.download_error_is_tamper(
            "URLError: connection reset; download truncated"))


class BlockingSemanticsTests(unittest.TestCase):

    def test_only_model_missing_and_ok_are_non_blocking(self):
        self.assertFalse(sh.is_blocked(sh.OK))
        self.assertFalse(sh.is_blocked(sh.MODEL_MISSING))
        for c in (sh.RUNTIME_BLOCKED, sh.MODEL_BLOCKED,
                  sh.DOWNLOAD_BLOCKED, sh.UNKNOWN):
            self.assertTrue(sh.is_blocked(c), c)


class MessageTests(unittest.TestCase):

    def test_every_cause_has_a_headline_and_hint(self):
        for c in (sh.RUNTIME_BLOCKED, sh.MODEL_BLOCKED, sh.DOWNLOAD_BLOCKED,
                  sh.MODEL_MISSING, sh.UNKNOWN):
            headline, hint = sh.message_for(c)
            self.assertTrue(headline.strip(), c)
            self.assertTrue(hint.strip(), c)

    def test_headline_uses_the_brand_name_not_a_hard_coded_one(self):
        # Names people see come only from brand.py (CLAUDE.md invariant).
        headline, _ = sh.message_for(sh.RUNTIME_BLOCKED)
        self.assertIn(brand.PRODUCT_NAME, headline)

    def test_download_tamper_wording_differs(self):
        plain = sh.message_for(sh.DOWNLOAD_BLOCKED, download_tamper=False)
        tamper = sh.message_for(sh.DOWNLOAD_BLOCKED, download_tamper=True)
        self.assertNotEqual(plain, tamper)


class LogDetailTests(unittest.TestCase):

    def test_detail_carries_cause_and_engine_and_trims_signature(self):
        d = sh.log_detail(sh.RUNTIME_BLOCKED, engine="parakeet",
                          exc_text="X" * 500, files_present=True)
        self.assertEqual(d["cause"], sh.RUNTIME_BLOCKED)
        self.assertEqual(d["engine"], "parakeet")
        self.assertLessEqual(len(d["signature"]), 300)
        self.assertTrue(d["files_present"])

    def test_tamper_flag_only_on_download_cause(self):
        self.assertIn("tamper",
                      sh.log_detail(sh.DOWNLOAD_BLOCKED, download_tamper=True))
        self.assertNotIn("tamper",
                         sh.log_detail(sh.RUNTIME_BLOCKED, download_tamper=True))

    def test_detail_omits_empty_signature(self):
        d = sh.log_detail(sh.MODEL_MISSING, engine="whisper", exc_text="")
        self.assertNotIn("signature", d)


if __name__ == "__main__":
    unittest.main()
