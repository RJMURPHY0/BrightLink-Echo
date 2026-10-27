"""The two ways a web page can reach a running Echo (security review
2026-10-27), each against the real code:

  * the local server on 127.0.0.1:47832 answers only requests addressed to it
    by name (no DNS rebinding), only the CRM's origin or a local tool, and
    reflects that one origin instead of "*";
  * a URL-scheme launch (`"<exe>" "%1"`) carries the URL and nothing else, so
    a crafted link can never smuggle in --uninstall or another flag.

The server itself is not started here: Ryan's installed Echo owns port 47832.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand  # noqa: E402
import app as app_mod  # noqa: E402

HOST = "127.0.0.1:47832"
CRM = "https://app.brightlink.io"


class LocalServerOriginTests(unittest.TestCase):
    def check(self, **headers):
        return app_mod._local_request_origin({k.replace("_", "-"): v for k, v in headers.items()})

    def test_the_crm_is_allowed_and_its_origin_reflected(self):
        self.assertEqual(CRM, self.check(Host=HOST, Origin=CRM, Sec_Fetch_Site="cross-site"))
        self.assertEqual(CRM, self.check(Host="localhost:47832", Origin=CRM))

    def test_local_tools_without_an_origin_are_allowed(self):
        # The second-instance launcher, tools/selftest_install.py, e2e_upgrade.
        self.assertEqual("", self.check(Host=HOST))
        # Typed into the address bar by hand.
        self.assertEqual("", self.check(Host=HOST, Sec_Fetch_Site="none"))

    def test_any_other_web_page_is_refused(self):
        for origin in ("https://evil.example", "http://app.brightlink.io", "null",
                       "https://app.brightlink.io.evil.example", "https://brightlink.io"):
            self.assertIsNone(self.check(Host=HOST, Origin=origin), msg=origin)

    def test_a_page_that_strips_the_origin_is_refused(self):
        # <img src="http://127.0.0.1:47832/update"> sends no Origin on a GET.
        for site in ("cross-site", "same-site", "same-origin"):
            self.assertIsNone(self.check(Host=HOST, Sec_Fetch_Site=site), msg=site)

    def test_dns_rebinding_hosts_are_refused(self):
        for host in ("evil.example:47832", "", "127.0.0.1", "127.0.0.1:80",
                     "attacker.127.0.0.1.nip.io:47832"):
            self.assertIsNone(self.check(Host=host), msg=host)
            self.assertIsNone(self.check(Host=host, Origin=CRM), msg=host)

    def test_the_handler_checks_before_doing_anything(self):
        src = open(app_mod.__file__, encoding="utf-8").read()
        body = src[src.index("def _start_local_server"):src.index("class _Server(")]
        self.assertNotIn('"Access-Control-Allow-Origin", "*"', body)
        for method in ("def do_GET(self):", "def do_OPTIONS(self):"):
            after = body[body.index(method):]
            self.assertTrue(after.split("\n", 2)[1].strip().startswith("origin = self._allowed()"),
                            msg=method)


class UrlLaunchArgvTests(unittest.TestCase):
    def test_a_url_launch_keeps_only_the_url(self):
        for scheme in (brand.URL_SCHEME, brand.LEGACY_URL_SCHEME):
            url = f"{scheme}://launch"
            for argv in (["echo.exe", url, "--uninstall", "/S"],
                         ["echo.exe", "--uninstall", url],
                         ["echo.exe", "--restart-audio-engine", url, "x"],
                         ["echo.exe", url.upper(), "--install"]):
                out = app_mod._url_launch_argv(argv)
                self.assertEqual(2, len(out), msg=argv)
                self.assertEqual("echo.exe", out[0])
                self.assertTrue(out[1].lower().startswith(scheme + ":"), msg=argv)

    def test_ordinary_command_lines_are_untouched(self):
        for argv in (["echo.exe"], ["echo.exe", "--startup"], ["echo.exe", "--uninstall", "/S"],
                     ["echo.exe", "--selftest", "C:\\x.wav", "r.json"],
                     ["echo.exe", "--install", "--start-with-windows=1"],
                     ["echo.exe", "https://example.com"]):
            self.assertEqual(argv, app_mod._url_launch_argv(argv))

    def test_it_runs_before_any_flag_is_read(self):
        src = open(app_mod.__file__, encoding="utf-8").read()
        sanitise = src.index("sys.argv = _url_launch_argv(sys.argv)")
        self.assertLess(sanitise, src.index('sys.argv[1:2] == ["--restart-audio-engine"]'))
        self.assertLess(sanitise, src.index("pyi_runtime.relaunch_if_foreign_runtime("))
        self.assertLess(sanitise, src.index("def _uninstall_requested"))


if __name__ == "__main__":
    unittest.main()
