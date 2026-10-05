import io
import os
import tempfile
import time
import unittest
from unittest import mock

import app_icons


class AppIconTests(unittest.TestCase):
    def test_packaged_whatsapp_executable_uses_brand_name(self):
        with mock.patch.object(
            app_icons, "_exe_path_for_hwnd",
            return_value=r"C:\Program Files\WindowsApps\WhatsApp.Root.exe",
        ), mock.patch.object(app_icons, "_window_title", return_value="WhatsApp"):
            info = app_icons.capture_app_info(123)

        self.assertEqual("WhatsApp", info["app_name"])

    def tearDown(self):
        app_icons._raw_icon_cache.clear()
        app_icons._icon_cache.clear()
        app_icons._stat_memo.clear()

    def test_the_cache_key_does_not_stat_the_exe_on_every_lookup(self):
        # A history render redraws every visible row — on each search keystroke,
        # each resize and each tab switch. Statting per row per render put the
        # disk in the middle of typing.
        path = r"C:\Program Files\Example\Example.exe"
        with mock.patch.object(app_icons.os, "stat") as st:
            st.return_value = mock.Mock(st_mtime_ns=1234, st_size=99)
            first = app_icons._exe_icon_cache_key(path)
            for _ in range(50):
                app_icons._exe_icon_cache_key(path)
        self.assertEqual(1, st.call_count)
        self.assertEqual(first, app_icons._exe_icon_cache_key(path))

    def test_a_replaced_exe_still_gets_a_fresh_icon_after_the_ttl(self):
        # The signature is in the key so an in-place app update re-extracts.
        path = r"C:\Program Files\Example\Example.exe"
        with mock.patch.object(app_icons.os, "stat") as st:
            st.return_value = mock.Mock(st_mtime_ns=1, st_size=10)
            before = app_icons._exe_icon_cache_key(path)
            st.return_value = mock.Mock(st_mtime_ns=2, st_size=20)
            # Age the memo past its TTL rather than sleeping through it.
            stamp, key = app_icons._stat_memo[list(app_icons._stat_memo)[0]]
            app_icons._stat_memo[list(app_icons._stat_memo)[0]] = (
                stamp - app_icons._STAT_TTL - 1, key)
            after = app_icons._exe_icon_cache_key(path)
        self.assertNotEqual(before, after)

    def test_browser_titles_resolve_known_services_across_separators(self):
        cases = {
            "New chat - Claude - Google Chrome": "Claude",
            "Ask Jack AI — #1 AI Auto - Google Chrome": "Ask Jack AI",
            "Inbox – Gmail — Microsoft Edge": "Gmail",
            "Feature request | GitHub | Zen Browser": "GitHub",
            "Claude — Project — Zen Browser": "Claude",
            "Some Project — Settings — Zen Browser": "Settings",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(expected, app_icons._browser_service_label(title))

    def test_generic_browser_titles_fall_back_to_browser_name(self):
        for title in (
            "New Tab - Google Chrome",
            "about:blank — Microsoft Edge",
            "Google Chrome",
            "Start Page | Zen Browser",
        ):
            with self.subTest(title=title):
                self.assertEqual("", app_icons._browser_service_label(title))

        with (mock.patch.object(app_icons, "_exe_path_for_hwnd",
                                return_value=r"C:\Apps\zen.exe"),
              mock.patch.object(app_icons, "_window_title",
                                return_value="New Tab — Zen Browser")):
            self.assertEqual(
                {"app_name": "Zen", "app_exe": r"C:\Apps\zen.exe"},
                app_icons.capture_app_info(123),
            )

    def test_raw_extraction_retries_failures_then_reuses_success(self):
        sentinel = object()
        path = r"C:\Missing\Example.exe"
        with mock.patch.object(
                app_icons, "_extract_exe_icon",
                side_effect=[None, sentinel]) as extract:
            self.assertIsNone(app_icons._get_raw_exe_icon(path))
            self.assertIs(sentinel, app_icons._get_raw_exe_icon(path))
            self.assertIs(sentinel, app_icons._get_raw_exe_icon(path))
        self.assertEqual(2, extract.call_count)

    def test_failed_render_does_not_poison_photo_cache(self):
        path = r"C:\Missing\Example.exe"
        with mock.patch.object(app_icons, "_get_raw_exe_icon", return_value=None):
            self.assertIsNone(app_icons.get_app_icon(path, "#101010"))
        self.assertEqual({}, app_icons._icon_cache)

    def test_monogram_cache_key_uses_full_normalized_name(self):
        self.assertNotEqual(
            app_icons._monogram_cache_key("Alpha", "#000000"),
            app_icons._monogram_cache_key("Ask Jack AI", "#000000"),
        )
        self.assertEqual(
            app_icons._monogram_cache_key("  Claude ", "#111111"),
            app_icons._monogram_cache_key("claude", "#111111"),
        )

    def test_zen_is_recognized_as_a_browser(self):
        self.assertIn("zen", app_icons._BROWSERS)

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CRM_HTML = ('<head><link id="app-favicon" rel="icon" type="image/png" href="/favicon.png" />'
            '<link rel="apple-touch-icon" href="/touch.png" /><title>BrightLink</title></head>')


class CrmFaviconTests(unittest.TestCase):
    """History shows the live BrightLink CRM favicon for CRM tabs only."""

    def setUp(self):
        app_icons._site_state.update(fetching=False, last_attempt=0.0,
                                     mtime_ns=0, stat_at=0.0)

    def test_crm_tab_titles_resolve_to_the_crm_name(self):
        for title in ("Contacts | BrightLink - Google Chrome", "BrightLink - Google Chrome"):
            with mock.patch.object(app_icons, "_exe_path_for_hwnd", return_value=CHROME), \
                 mock.patch.object(app_icons, "_window_title", return_value=title):
                self.assertEqual(app_icons.brand.CRM_NAME,
                                 app_icons.capture_app_info(1)["app_name"], title)

    def test_a_page_about_brightlink_is_not_the_crm(self):
        with mock.patch.object(app_icons, "_exe_path_for_hwnd", return_value=CHROME), \
             mock.patch.object(app_icons, "_window_title",
                               return_value="BrightLink - Google Search - Google Chrome"):
            name = app_icons.capture_app_info(1)["app_name"]
        self.assertFalse(app_icons.is_crm_tab(name, CHROME))

    def test_only_a_browser_tab_named_brightlink_qualifies(self):
        self.assertTrue(app_icons.is_crm_tab("BrightLink", CHROME))
        self.assertTrue(app_icons.is_crm_tab(" brightlink ", r"C:\x\msedge.exe"))
        self.assertFalse(app_icons.is_crm_tab("Claude", CHROME))
        self.assertFalse(app_icons.is_crm_tab("BrightLink", r"C:\x\notepad.exe"))
        self.assertFalse(app_icons.is_crm_tab("BrightLink", ""))

    def test_other_rows_never_fetch(self):
        with mock.patch.object(app_icons, "_refresh_site_favicon_if_due") as due:
            self.assertIsNone(app_icons.get_site_icon("Claude", CHROME, "#111111"))
        due.assert_not_called()

    def test_the_favicon_link_is_read_from_the_page(self):
        self.assertEqual("/favicon.png", app_icons._favicon_href(CRM_HTML))
        self.assertEqual("/t.png", app_icons._favicon_href(
            '<link rel="apple-touch-icon" href="/t.png">'))
        self.assertEqual("/s.ico", app_icons._favicon_href(
            '<link rel="shortcut icon" href="/s.ico">'))
        self.assertEqual("/favicon.ico", app_icons._favicon_href("<title>x</title>"))

    def test_refresh_runs_when_missing_or_stale_and_not_in_a_loop(self):
        with mock.patch("threading.Thread") as thread:
            app_icons._refresh_site_favicon_if_due(time.time() - 60)    # fresh
            thread.assert_not_called()
            app_icons._refresh_site_favicon_if_due(0)                   # missing
            self.assertEqual(1, thread.call_count)
            app_icons._site_state["fetching"] = False                   # it failed
            app_icons._refresh_site_favicon_if_due(0)                   # retry waits
            self.assertEqual(1, thread.call_count)
            app_icons._site_state["last_attempt"] -= app_icons._SITE_RETRY_S + 1
            app_icons._refresh_site_favicon_if_due(time.time() - app_icons._SITE_REFRESH_S - 1)
            self.assertEqual(2, thread.call_count)

    def test_download_saves_the_live_favicon_as_png(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGBA", (64, 64), (243, 146, 0, 255)).save(buf, "PNG")
        pages = {"https://app.brightlink.io/": CRM_HTML.encode(),
                 "https://app.brightlink.io/favicon.png": buf.getvalue()}
        seen = []

        def fake_open(req, timeout):
            seen.append(req.full_url)
            resp = mock.MagicMock()
            resp.__enter__.return_value.read = lambda n=-1: pages[req.full_url]
            return resp

        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "icons", "crm-favicon.png")
            with mock.patch.object(app_icons, "_site_icon_path", return_value=out), \
                 mock.patch("urllib.request.urlopen", side_effect=fake_open):
                app_icons._site_state["fetching"] = True
                app_icons._download_site_favicon()
            self.assertEqual(list(pages), seen)
            self.assertFalse(app_icons._site_state["fetching"])
            with Image.open(out) as img:
                self.assertEqual((64, 64), img.size)

    def test_a_failed_download_keeps_the_last_good_favicon(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "crm-favicon.png")
            with open(out, "wb") as f:
                f.write(b"old")
            with mock.patch.object(app_icons, "_site_icon_path", return_value=out), \
                 mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
                app_icons._download_site_favicon()
            with open(out, "rb") as f:
                self.assertEqual(b"old", f.read())

    def test_the_bundled_mark_stands_in_before_the_first_download(self):
        self.assertTrue(os.path.exists(app_icons._SITE_BUNDLED))


if __name__ == "__main__":
    unittest.main()
