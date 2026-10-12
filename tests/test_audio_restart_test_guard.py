"""No test may stop the real Windows Audio service, kill audiodg.exe or raise
a UAC prompt (Windows Audio crashed twice on 2026-10-12 while the restart was
being worked on). The guard lives in the real primitives, so a test that
forgets a mock fails instead of cutting off every app's microphone."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audio_engine


class RealRestartRefusedInTestsTests(unittest.TestCase):
    def test_stopping_the_service_is_refused(self):
        with self.assertRaises(RuntimeError):
            audio_engine._stop("Audiosrv")

    def test_taskkill_is_refused(self):
        with mock.patch.object(audio_engine, "_REAL_SUBPROCESS_RUN",
                               audio_engine.subprocess.run):
            with self.assertRaises(RuntimeError):
                audio_engine._run([audio_engine._tool("taskkill.exe"),
                                   "/F", "/IM", "audiodg.exe"])

    def test_an_elevated_launch_is_refused(self):
        with self.assertRaises(RuntimeError):
            audio_engine._shell_execute("runas", "nothing.exe", "", 1)

    def test_the_installed_app_is_never_affected(self):
        with mock.patch.object(audio_engine.sys, "frozen", True, create=True):
            self.assertFalse(audio_engine._under_tests())

    def test_other_tools_still_run(self):
        out = audio_engine._run([audio_engine._tool("where.exe"), "where.exe"])
        self.assertIsInstance(out, str)


if __name__ == "__main__":
    unittest.main()
