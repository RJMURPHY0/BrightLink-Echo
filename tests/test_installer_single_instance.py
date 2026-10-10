"""A second launch of Setup exits silently while the first is running.

Seven clicks on the download left six "Setup is already running" boxes to
dismiss. This builds a tiny Setup around installer/single_instance.isi (the
file echo.iss includes) and launches it twice. Skipped without Inno Setup."""

import ctypes
import os
import subprocess
import sys
import tempfile
import time
import unittest
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FIXTURE = os.path.join(ROOT, "tests", "installer_fixture", "single_instance_test.iss")
NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _find_iscc() -> str:
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        path = os.path.join(base, "Inno Setup 6", "ISCC.exe") if base else ""
        if path and os.path.isfile(path):
            return path
    return ""


def _kill_tree(proc) -> None:
    """Inno's loader starts a .tmp child that does the work; killing only the
    loader leaves it holding the mutex."""
    if proc.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, creationflags=NO_WIN)


def _visible_windows_of(pid: int) -> list:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            found.append(buf.value)
        return True

    user32.EnumWindows(proc(cb), 0)
    return found


@unittest.skipUnless(sys.platform == "win32" and _find_iscc(), "needs Windows and Inno Setup 6")
class SecondSetupIsSilentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp(prefix="echo_single_instance_")
        r = subprocess.run([_find_iscc(), "/Q", f"/DOutDir={cls.out}", FIXTURE],
                           capture_output=True, text=True, creationflags=NO_WIN)
        if r.returncode != 0:
            raise AssertionError(f"ISCC failed:\n{r.stdout}\n{r.stderr}")
        cls.exe = os.path.join(cls.out, "single-instance-test.exe")

    def test_a_second_launch_exits_at_once_without_a_window(self):
        first = subprocess.Popen([self.exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                                 creationflags=NO_WIN)
        try:
            time.sleep(2.0)  # the first has claimed the mutex and is holding it
            self.assertIsNone(first.poll(), "the first Setup must still be running")
            # No /SUPPRESSMSGBOXES here: the old behaviour put a box on screen.
            second = subprocess.Popen([self.exe], creationflags=NO_WIN)
            seen = []
            deadline = time.time() + 4.0
            while time.time() < deadline and second.poll() is None:
                seen += _visible_windows_of(second.pid)
                time.sleep(0.1)
            exited = second.poll() is not None
            if not exited:
                _kill_tree(second)
            self.assertTrue(exited, f"the second Setup stayed open; windows seen: {seen}")
            self.assertEqual(seen, [], "the second Setup must show nothing")
            self.assertIsNone(first.poll(), "the first Setup is unaffected by the second")
        finally:
            first.wait(timeout=30)
        self.assertEqual(first.returncode, 0)

    def test_many_launches_at_once_leave_exactly_one(self):
        first = subprocess.Popen([self.exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                                 creationflags=NO_WIN)
        time.sleep(2.0)  # the first has claimed the mutex; a launch that wins the race would stay open
        extras = [subprocess.Popen([self.exe], creationflags=NO_WIN) for _ in range(6)]
        try:
            deadline = time.time() + 5.0
            while time.time() < deadline and any(p.poll() is None for p in extras):
                time.sleep(0.1)
            alive = [p.pid for p in extras if p.poll() is None]
            self.assertEqual(alive, [], f"extra Setups still open: {alive}")
        finally:
            for p in extras:
                _kill_tree(p)
            first.wait(timeout=30)

    def test_launches_in_the_same_instant_leave_exactly_one(self):
        # No head start for anyone: every launch races for the mutex. A guard
        # that let two of them each win one name would leave none running.
        procs = [subprocess.Popen([self.exe], creationflags=NO_WIN) for _ in range(8)]
        try:
            time.sleep(3.0)  # the winner holds for the test's 6 s; the rest have exited
            alive = [p.pid for p in procs if p.poll() is None]
            self.assertEqual(len(alive), 1, f"expected exactly one Setup, found {alive}")
        finally:
            for p in procs:
                _kill_tree(p)

    def test_it_is_free_again_once_the_first_finishes(self):
        subprocess.run([self.exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                       creationflags=NO_WIN, timeout=60)
        again = subprocess.run([self.exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                               creationflags=NO_WIN, timeout=60)
        self.assertEqual(again.returncode, 0)


class EchoIssUsesTheGuardTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "installer", "echo.iss"), encoding="utf-8") as f:
            self.iss = f.read()

    def test_echo_iss_includes_the_guard_and_drops_the_loud_mutex(self):
        self.assertIn('#include "single_instance.isi"', self.iss)
        # SetupMutex= in [Setup] is Inno's own check, the one that shows the box.
        setup_lines = [ln.strip() for ln in self.iss.splitlines()]
        self.assertFalse([ln for ln in setup_lines if ln.startswith("SetupMutex=")])


if __name__ == "__main__":
    unittest.main()
