"""numpy's OpenBLAS is held to one thread, set before anything imports numpy.

OpenBLAS commits a 32 MB buffer per thread, one thread per CPU thread by
default: importing numpy cost 781 MB of private memory on a 24-thread laptop
(12 Nov 2026), 48 MB with one thread, with identical transcripts from Parakeet
and base.en. The variable only works if it is set before numpy loads.
"""
import ast
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app.py")


def _top_level(tree):
    for node in tree.body:
        yield node
        if isinstance(node, ast.If):
            yield from node.body


class OpenBlasThreadsTests(unittest.TestCase):
    def test_app_sets_it_before_its_first_project_import(self):
        with open(APP, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        set_line = None
        first_project_import = None
        stdlib = {"os", "sys", "threading", "time", "collections", "ctypes"}
        for node in _top_level(tree):
            src = ast.unparse(node)
            if set_line is None and "OPENBLAS_NUM_THREADS" in src and "setdefault" in src:
                set_line = node.lineno
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module or ""])
                if any(n.split(".")[0] not in stdlib for n in names):
                    if first_project_import is None:
                        first_project_import = node.lineno
        self.assertIsNotNone(set_line, "app.py must set OPENBLAS_NUM_THREADS")
        self.assertLess(set_line, first_project_import)

    @unittest.skipUnless(sys.platform == "win32", "private bytes via psapi")
    def test_numpy_stays_small_with_app_line(self):
        # A clean interpreter running app.py's own line, then numpy: private
        # memory after the import stays far below one buffer per CPU thread.
        code = (
            "import os, ctypes as C, ctypes.wintypes as W\n"
            "os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')\n"
            "import numpy\n"
            "numpy.ones((300, 300)) @ numpy.ones((300, 300))\n"
            "class P(C.Structure):\n"
            "    _fields_=[('cb',W.DWORD),('f',W.DWORD)]+[(n,C.c_size_t) for n in "
            "'a b c d e g h i PrivateUsage'.split()]\n"
            "C.windll.kernel32.GetCurrentProcess.restype=W.HANDLE\n"
            "C.windll.psapi.GetProcessMemoryInfo.argtypes=[W.HANDLE,C.c_void_p,W.DWORD]\n"
            "p=P(); p.cb=C.sizeof(p)\n"
            "C.windll.psapi.GetProcessMemoryInfo(C.windll.kernel32.GetCurrentProcess(),C.byref(p),p.cb)\n"
            "print(p.PrivateUsage // 2**20)\n"
        )
        env = {k: v for k, v in os.environ.items() if k != "OPENBLAS_NUM_THREADS"}
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env=env, timeout=120,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        mb = int(out.stdout.strip().splitlines()[-1])
        # 48 MB measured with one thread; 788 MB on 24 threads without it.
        self.assertLess(mb, 150, out.stderr)


if __name__ == "__main__":
    unittest.main()
