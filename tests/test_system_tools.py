"""Hardening: Windows tools are started by full System32 path, never a bare name."""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import system_tools


class SystemToolsTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_paths_exist_and_are_absolute(self):
        for p in (system_tools.system_tool("schtasks.exe"), system_tools.powershell_exe()):
            self.assertTrue(os.path.isabs(p), p)
            self.assertTrue(os.path.exists(p), p)
        self.assertEqual(os.path.basename(system_tools.powershell_exe()).lower(),
                         "powershell.exe")

    def test_environment_is_not_trusted(self):
        saved = os.environ.get("SystemRoot")
        os.environ["SystemRoot"] = r"C:\planted"
        try:
            self.assertNotIn("planted", system_tools.system32_dir())
            self.assertNotIn("planted", system_tools.system_tool("taskkill.exe"))
        finally:
            if saved is None:
                os.environ.pop("SystemRoot", None)
            else:
                os.environ["SystemRoot"] = saved

    def test_no_bare_powershell_or_schtasks_launch_in_runtime_modules(self):
        """First list element of a subprocess call must not be a bare tool name."""
        for rel in ("updater.py", "app.py", "audio_engine.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.List) and node.elts:
                    first = node.elts[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        self.assertNotIn(first.value.lower(),
                                         ("powershell", "powershell.exe", "schtasks",
                                          "schtasks.exe", "taskkill", "taskkill.exe"),
                                         f"{rel}:{node.lineno} starts a bare tool name")


if __name__ == "__main__":
    unittest.main()
