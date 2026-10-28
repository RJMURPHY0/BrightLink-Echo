"""tools/vt_report.py: reads VirusTotal's verdict on a build's uploads.

A Microsoft detection must stop the release (Defender quarantines it on almost
every customer PC); any other detection only warns; VirusTotal being down or
slow never fails the build.
"""

import http.client
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import vt_report  # noqa: E402


def attrs(**flags):
    results = {"Kaspersky": {"category": "undetected", "result": None}}
    for engine, (category, name) in flags.items():
        results[engine] = {"category": category, "result": name}
    mal = sum(1 for c, _ in flags.values() if c == "malicious")
    return {"last_analysis_date": int(time.time()),
            "last_analysis_results": results,
            "last_analysis_stats": {"malicious": mal, "suspicious": 0,
                                    "undetected": 1}}


class VtReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.exe = os.path.join(self.tmp, "app.exe")
        with open(self.exe, "wb") as f:
            f.write(b"MZ test")
        patches = [mock.patch.object(vt_report, "REQUEST_GAP", 0),
                   mock.patch.dict(os.environ, {"VT_API_KEY": "fake-key"}),
                   mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_with(self, report):
        out = os.path.join(self.tmp, "vt.json")
        with mock.patch.object(vt_report, "fetch", side_effect=report):
            code = vt_report.main(["--out", out, "--timeout", "1", self.exe])
        return code, out

    def test_clean_build_passes(self):
        code, out = self.run_with(lambda sha, key: attrs())
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out))

    def test_microsoft_detection_blocks(self):
        code, _ = self.run_with(lambda sha, key: attrs(
            Microsoft=("malicious", "Trojan:Win32/Wacatac.B!ml")))
        self.assertEqual(code, 1)

    def test_other_engine_only_warns(self):
        code, _ = self.run_with(lambda sha, key: attrs(
            Elastic=("malicious", "malicious (moderate Confidence)")))
        self.assertEqual(code, 0)

    def test_microsoft_suspicious_only_warns(self):
        code, _ = self.run_with(lambda sha, key: attrs(
            Microsoft=("suspicious", "Program:Win32/Wacapew.C!ml")))
        self.assertEqual(code, 0)

    def test_block_engines_configurable(self):
        with mock.patch.dict(os.environ, {"VT_BLOCK_ENGINES": "Microsoft,Avast"}):
            code, _ = self.run_with(lambda sha, key: attrs(
                Avast=("malicious", "Win64:Malware-gen")))
        self.assertEqual(code, 1)

    def test_virustotal_down_never_fails(self):
        def down(sha, key):
            raise urllib.error.URLError("unreachable")
        code, _ = self.run_with(down)
        self.assertEqual(code, 0)

    def test_bad_key_stops_at_once(self):
        calls = []

        def refused(sha, key):
            calls.append(sha)
            raise urllib.error.HTTPError(vt_report.API, 401, "nope", {}, None)
        code, _ = self.run_with(refused)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)

    def test_later_refusal_keeps_an_earlier_microsoft_block(self):
        second = os.path.join(self.tmp, "bridge.exe")
        with open(second, "wb") as f:
            f.write(b"MZ other")
        answers = iter([attrs(Microsoft=("malicious", "Trojan:Win32/X!ml"))])

        def report(sha, key):
            try:
                return next(answers)
            except StopIteration:
                raise urllib.error.HTTPError(vt_report.API, 403, "no", {}, None)
        with mock.patch.object(vt_report, "fetch", side_effect=report):
            code = vt_report.main(["--timeout", "1", self.exe, second])
        self.assertEqual(code, 1)

    def test_truncated_response_only_warns(self):
        def cut(sha, key):
            raise http.client.IncompleteRead(b"{", 100)
        code, _ = self.run_with(cut)
        self.assertEqual(code, 0)

    def test_report_not_ready_never_fails(self):
        code, out = self.run_with(lambda sha, key: None)
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8") as f:
            self.assertIn("pending", f.read())

    def test_stale_analysis_is_not_this_upload(self):
        old = attrs()
        old["last_analysis_date"] = int(time.time()) - 3 * 86400
        self.assertFalse(vt_report.analysis_done(old, int(time.time()) - 86400))

    def test_no_key_skips(self):
        with mock.patch.dict(os.environ, {"VT_API_KEY": ""}):
            self.assertEqual(vt_report.main([self.exe]), 0)


if __name__ == "__main__":
    unittest.main()
