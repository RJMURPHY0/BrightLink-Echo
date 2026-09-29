"""Choices that keep antivirus heuristics quiet, pinned so they are not undone.

Every PowerShell launch of ours is already windowless (CREATE_NO_WINDOW from
Python, SW_HIDE from the installer), so "-WindowStyle Hidden" does nothing for
us. It is, though, one of the command-line tokens AV behaviour rules score a
hidden PowerShell start on. See docs/FALSE_POSITIVE_REPORTING.md.
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class NoHiddenWindowStyleTests(unittest.TestCase):
    def test_no_powershell_launch_asks_for_a_hidden_window(self):
        for rel in ("updater.py", "app_install.py", os.path.join("installer", "echo.iss")):
            src = _src(rel)
            code = "\n".join(ln for ln in src.splitlines()
                             if not ln.lstrip().startswith(("#", "//", ";")))
            self.assertNotIn('"-WindowStyle"', code, rel)
            self.assertNotIn("-WindowStyle Hidden", code, rel)

    def test_launches_stay_windowless_without_it(self):
        self.assertIn("CREATE_NO_WINDOW", _src("updater.py"))
        self.assertIn("_NO_WIN", _src("app_install.py"))
        self.assertIn("SW_HIDE", _src(os.path.join("installer", "echo.iss")))


class ActivationScriptSigningTests(unittest.TestCase):
    def setUp(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        with open(os.path.join(ROOT, ".github", "workflows", "build-release.yml"),
                  encoding="utf-8") as f:
            wf = yaml.safe_load(f)
        self.names = [s.get("name") for s in wf["jobs"]["build-windows"]["steps"]]
        self.steps = {s.get("name"): s for s in wf["jobs"]["build-windows"]["steps"]}

    def test_the_script_is_signed_before_the_manifest_records_it(self):
        self.assertLess(self.names.index("Sign activation script"),
                        self.names.index("Write the installed-layout manifest"))

    def test_signing_the_script_never_blocks_a_release(self):
        step = self.steps["Sign activation script"]
        self.assertIs(True, step.get("continue-on-error"))
        self.assertEqual("ps1", step["with"]["files-folder-filter"])


if __name__ == "__main__":
    unittest.main()
