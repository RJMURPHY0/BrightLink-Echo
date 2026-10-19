"""Guards for av_report — the user-side allow-list fix and the developer-side
false-positive report.

The folder the user is told to allow-list must always be the one THIS install
actually uses (resolved through data_paths), never a name written by hand — the
old docs path went stale to `FTC Whisper` exactly because it was. And a report
must never carry anything the user said.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import brand
import data_paths
import av_report


class AllowlistPathTests(unittest.TestCase):

    def test_primary_dir_is_a_real_data_folder_name(self):
        # Must be one of the folders data_paths owns, current or legacy —
        # proving it came from data_paths, not a literal in av_report.
        base = os.path.basename(av_report.primary_allowlist_dir())
        self.assertIn(base, (brand.DATA_DIR_NAME, brand.LEGACY_DATA_DIR_NAME))

    def test_primary_dir_matches_data_paths_local_dir(self):
        self.assertEqual(av_report.primary_allowlist_dir(),
                         av_report.allowlist_dirs()[0])

    def test_allowlist_dirs_never_empty(self):
        self.assertTrue(av_report.allowlist_dirs())

    def test_module_source_hard_codes_no_folder_name(self):
        # The whole point: no product/folder name baked into this module.
        with open(os.path.join(ROOT, "av_report.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn(brand.DATA_DIR_NAME, src)
        self.assertNotIn(brand.LEGACY_DATA_DIR_NAME, src)


class FixGuidanceTests(unittest.TestCase):

    def test_fix_steps_name_the_folder_and_restart(self):
        steps = av_report.fix_steps()
        self.assertTrue(steps)
        joined = "\n".join(steps)
        self.assertIn(av_report.primary_allowlist_dir(), joined)
        self.assertIn(brand.PRODUCT_NAME, joined)

    def test_fix_message_includes_the_folder(self):
        self.assertIn(av_report.primary_allowlist_dir(), av_report.fix_message())


class VendorFormTests(unittest.TestCase):

    def test_covers_the_reach_vendors_over_https(self):
        names = [n for n, _ in av_report.vendor_form_urls()]
        self.assertTrue(any("Microsoft" in n for n in names))
        self.assertTrue(any("Avast" in n for n in names))
        for _name, url in av_report.vendor_form_urls():
            self.assertTrue(url.startswith("https://"), url)


class ReportTests(unittest.TestCase):

    _DETAIL = {"cause": "runtime_blocked", "engine": "parakeet",
               "signature": "dll load failed", "files_present": True}

    def test_report_carries_the_essentials(self):
        r = av_report.build_report(cause="runtime_blocked", detail=self._DETAIL,
                                   app_version="1.8.14")
        self.assertEqual(r["cause"], "runtime_blocked")
        self.assertEqual(r["app_version"], "1.8.14")
        self.assertEqual(r["signature"], "dll load failed")
        self.assertEqual(r["allowlist_dir"], av_report.primary_allowlist_dir())
        self.assertEqual(r["github_repo"], brand.GITHUB_REPO)

    def test_report_never_carries_user_speech(self):
        # Even if a speech sample leaked into detail, the report must not echo
        # it — build_report only reads a fixed set of non-speech fields.
        detail = dict(self._DETAIL, text="what the user said",
                      sample="secret", excerpt="more")
        r = av_report.build_report(cause="x", detail=detail, app_version="1")
        for banned in ("text", "sample", "excerpt"):
            self.assertNotIn(banned, r)
        self.assertNotIn("what the user said", av_report.report_text(r))

    def test_report_text_is_readable_and_states_legitimacy(self):
        r = av_report.build_report(cause="download_blocked", detail=self._DETAIL,
                                   app_version="1.8.14")
        text = av_report.report_text(r)
        self.assertIn(av_report.primary_allowlist_dir(), text)
        self.assertIn("1.8.14", text)
        self.assertIn("legitimate", text.lower())

    def test_build_report_tolerates_empty_inputs(self):
        r = av_report.build_report()  # no cause, no detail
        self.assertEqual(r["kind"], "av_false_positive")
        self.assertEqual(r["product"], brand.PRODUCT_NAME)
        # report_text must still render without raising.
        self.assertTrue(av_report.report_text(r).strip())


if __name__ == "__main__":
    unittest.main()
