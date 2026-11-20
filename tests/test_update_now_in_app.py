"""Update Now installs inside the app and never sends people to the browser
(Ryan, 2026-11-20: pressing it opened the GitHub download page in Chrome)."""
import os
import unittest
from unittest import mock

import update_now
import updater

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_GOOD = {
    "version": "v1.8.43",
    "download_url": "https://example.invalid/onefile-43",
    "setup": {"url": "https://example.invalid/setup-43", "sha256": "ab" * 32},
}


class UpdateTargetTest(unittest.TestCase):
    def setUp(self):
        # Never read this machine's real rollback marker.
        patcher = mock.patch.object(updater, "is_known_bad", return_value=False)
        self.known_bad = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        updater._cached_release = None

    def test_a_failed_fetch_uses_a_usable_cached_release(self):
        # Banner says 1.8.42, the cache already holds a usable 1.8.43 and
        # GitHub is unreachable: install 1.8.43 in the app, never fail at once.
        updater._cached_release = dict(_GOOD)
        got = update_now.update_target("v1.8.42", "old", fetch=lambda: None)
        self.assertEqual(got, ("v1.8.43", _GOOD["download_url"]))

    def test_a_rolled_back_version_is_never_picked(self):
        updater._cached_release = None
        self.known_bad.side_effect = lambda v: v.lstrip("vV") == "1.8.43"
        got = update_now.update_target("v1.8.42", "u", fetch=lambda: dict(_GOOD))
        self.assertEqual(got, ("v1.8.42", "u"))

    def test_a_usable_cache_is_used_without_a_fetch(self):
        updater._cached_release = dict(_GOOD)
        fetch = mock.Mock()
        self.assertEqual(update_now.update_target("1.8.43", "u"), ("1.8.43", "u"))
        self.assertEqual(update_now.update_target("v1.8.43", "u", fetch=fetch),
                         ("v1.8.43", "u"))
        fetch.assert_not_called()

    def test_an_empty_cache_is_refreshed(self):
        updater._cached_release = None
        got = update_now.update_target("v1.8.43", "old", fetch=lambda: dict(_GOOD))
        self.assertEqual(got, ("v1.8.43", _GOOD["download_url"]))

    def test_a_cache_for_another_version_is_refreshed(self):
        # Banner says 1.8.42, the cache holds 1.8.41: read again, and a newer
        # release (1.8.43) replaces the banner's version.
        updater._cached_release = dict(_GOOD, version="v1.8.41")
        got = update_now.update_target("v1.8.42", "old", fetch=lambda: dict(_GOOD))
        self.assertEqual(got, ("v1.8.43", _GOOD["download_url"]))

    def test_a_cache_without_an_installer_is_refreshed(self):
        updater._cached_release = dict(_GOOD, setup={})
        fetch = mock.Mock(return_value=dict(_GOOD))
        update_now.update_target("v1.8.43", "old", fetch=fetch)
        fetch.assert_called_once()

    def test_a_failed_fetch_keeps_the_banner_version(self):
        updater._cached_release = None
        self.assertEqual(update_now.update_target("v1.8.43", "u", fetch=lambda: None),
                         ("v1.8.43", "u"))

    def test_an_older_fetch_never_downgrades_the_target(self):
        updater._cached_release = None
        older = dict(_GOOD, version="v1.8.40")
        self.assertEqual(update_now.update_target("v1.8.43", "u", fetch=lambda: older),
                         ("v1.8.43", "u"))


class NoBrowserFallbackTest(unittest.TestCase):
    def test_update_now_never_opens_the_browser_in_an_installed_copy(self):
        with open(os.path.join(HERE, "app_window.py"), encoding="utf-8") as f:
            src = f.read()
        start = src.index("def show_update_banner(")
        end = src.index("\n    def ", start + 1)
        body = src[start:end]
        # One browser call is allowed: a source run, which has no exe to swap.
        self.assertEqual(body.count("webbrowser.open("), 1, body)
        guard = body.index("if not exe_path:")
        self.assertLess(guard, body.index("webbrowser.open("))
        self.assertNotIn("manual_fallback_browser", body)
        self.assertIn("update_target(", body)


if __name__ == "__main__":
    unittest.main()
