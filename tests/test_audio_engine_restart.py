"""A hung Windows audio engine (2026-10-05) gave five dead dictations in a row,
each claiming "reconnected". The second dead capture, or one while Windows
Audio is not running, must offer the engine restart instead."""

import ctypes
import os
import sys
import threading
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audio_engine  # noqa: E402
import app  # noqa: E402


def _bare_app():
    a = object.__new__(app.WhisperFlowApp)
    a.recorder = types.SimpleNamespace(last_recording_seconds=3.0,
                                       _active_device_name="Mic",
                                       restart_warm=lambda: None)
    a.feedback = mock.Mock()
    a._log_error_event = mock.Mock()
    return a


class DeadCaptureEscalationTests(unittest.TestCase):
    def test_first_dead_capture_reconnects_quietly(self):
        a = _bare_app()
        with mock.patch.object(audio_engine, "service_running", return_value=True):
            self.assertTrue(a._handle_dead_capture(0.0))
        msg = a.feedback.error_occurred.call_args[0][0]
        self.assertIn("reconnected", msg)

    def test_second_dead_capture_offers_engine_restart(self):
        a = _bare_app()
        with mock.patch.object(audio_engine, "service_running", return_value=True):
            a._handle_dead_capture(0.0)
            a._handle_dead_capture(0.0)
        self.assertEqual(a.feedback.error_occurred.call_args[0][0],
                         app.WhisperFlowApp._AUDIO_ENGINE_DOWN_MSG)

    def test_stopped_service_offers_restart_at_once(self):
        a = _bare_app()
        with mock.patch.object(audio_engine, "service_running", return_value=False):
            a._handle_dead_capture(0.0)
        self.assertEqual(a.feedback.error_occurred.call_args[0][0],
                         app.WhisperFlowApp._AUDIO_ENGINE_DOWN_MSG)

    def test_short_tap_is_not_a_dead_stream(self):
        a = _bare_app()
        a.recorder.last_recording_seconds = 0.2
        self.assertFalse(a._handle_dead_capture(0.0))
        a.feedback.error_occurred.assert_not_called()

    def test_engine_message_gets_the_button_toast(self):
        a = _bare_app()
        a.app_window = mock.Mock()
        a.tray = mock.Mock()
        with mock.patch.object(app, "_startup_log_path",
                               return_value=os.devnull):
            a._on_pipeline_error(app.WhisperFlowApp._AUDIO_ENGINE_DOWN_MSG)
        a.app_window.show_action_toast.assert_called_once()
        self.assertEqual(a.app_window.show_action_toast.call_args[0][1],
                         "Restart audio")
        a.tray.notify.assert_not_called()


class ServiceQueryTests(unittest.TestCase):
    def _sc(self, out):
        return mock.patch.object(audio_engine.subprocess, "run",
                                 return_value=types.SimpleNamespace(stdout=out))

    def test_running(self):
        with self._sc("        STATE              : 4  RUNNING\n"):
            self.assertTrue(audio_engine.service_running())

    def test_stopped(self):
        with self._sc("        STATE              : 1  STOPPED\n"):
            self.assertFalse(audio_engine.service_running())

    def test_unreadable_counts_as_running(self):
        with self._sc("garbage"):
            self.assertTrue(audio_engine.service_running())


class _FakeWindows:
    """Stands in for taskkill.exe, sc.exe and tasklist.exe, so the elevated
    half runs for real without touching Windows Audio or any process. Output
    shapes copied from Windows 11 26300."""

    def __init__(self, stops=True, starts=True, host="Audiosrv"):
        self.state = "RUNNING"
        self.stops, self.starts, self.host = stops, starts, host
        self.calls = []
        self.paths = []

    def run(self, args, **kw):
        self.paths.append(args[0])
        exe, rest = os.path.basename(args[0]).lower(), [a.lower() for a in args[1:]]
        self.calls.append([exe] + rest)
        out = ""
        if exe == "taskkill.exe" and rest[:2] == ["/f", "/pid"] and self.stops:
            self.state = "STOPPED"
        elif exe == "sc.exe" and rest[0] == "stop" and self.stops:
            self.state = "STOPPED"
        elif exe == "sc.exe" and rest[0] == "start" and self.starts:
            self.state = "RUNNING"
        elif exe == "sc.exe" and rest[0] == "queryex":
            pid = 4720 if self.state == "RUNNING" else 0
            out = (f"        STATE              : 4  {self.state} \n"
                   f"        PID                : {pid}\n")
        elif exe == "sc.exe" and rest[0] == "query":
            out = f"        STATE              : 1  {self.state} \n"
        elif exe == "tasklist.exe":
            out = f'"svchost.exe","4720","{self.host}"\n'
        return types.SimpleNamespace(stdout=out, returncode=0)

    def ran(self, *args):
        return [a.lower() for a in args] in self.calls


class ElevatedHalfTests(unittest.TestCase):
    def _run(self, **kw):
        fake = _FakeWindows(**kw)
        with mock.patch.object(audio_engine.subprocess, "run", side_effect=fake.run), \
                mock.patch.object(audio_engine.time, "sleep"):
            return audio_engine.restart_elevated(), fake

    def test_a_real_restart_reports_success(self):
        code, fake = self._run()
        self.assertEqual(audio_engine.RESTARTED, code)
        self.assertEqual(["taskkill.exe", "/f", "/im", "audiodg.exe"], fake.calls[0])
        self.assertTrue(fake.ran("sc.exe", "start", "Audiosrv"))

    def test_a_host_of_its_own_is_killed(self):
        _, fake = self._run()
        self.assertTrue(fake.ran("taskkill.exe", "/F", "/PID", "4720"))
        self.assertFalse(fake.ran("sc.exe", "stop", "Audiosrv"))

    def test_a_shared_host_is_never_killed(self):
        code, fake = self._run(host="AudioEndpointBuilder,Audiosrv")
        self.assertEqual(audio_engine.RESTARTED, code)
        self.assertFalse(fake.ran("taskkill.exe", "/F", "/PID", "4720"))
        self.assertTrue(fake.ran("sc.exe", "stop", "Audiosrv"))

    def test_an_unreadable_host_takes_the_gentle_path(self):
        _, fake = self._run(host="N/A")
        self.assertFalse(fake.ran("taskkill.exe", "/F", "/PID", "4720"))
        self.assertTrue(fake.ran("sc.exe", "stop", "Audiosrv"))

    def test_a_service_that_never_stopped_is_not_reported_as_restarted(self):
        # Codex review 2026-10-06: a stop that fails leaves the service
        # RUNNING, and the final check used to read that as a restart.
        code, fake = self._run(stops=False)
        self.assertEqual(audio_engine.NOT_STOPPED, code)
        self.assertNotEqual(audio_engine.CANCELLED, code)
        self.assertFalse(fake.ran("sc.exe", "start", "Audiosrv"))

    def test_a_service_that_never_came_back_is_a_failure(self):
        code, _ = self._run(starts=False)
        self.assertEqual(audio_engine.NOT_STARTED, code)

    def test_it_only_runs_tools_from_system32(self):
        # As admin, a bare "sc.exe" would be looked for in Echo's own
        # user-writable folder first.
        _, fake = self._run()
        sys32 = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32")
        self.assertTrue(fake.paths)
        for path in fake.paths:
            self.assertEqual(os.path.normcase(sys32), os.path.normcase(os.path.dirname(path)))

    def test_an_unexpected_error_is_a_failure_never_a_crash(self):
        # Uncaught in the windowless exe, it would show PyInstaller's dialog.
        with mock.patch.object(audio_engine, "_service_pid", side_effect=RuntimeError("x")),                 mock.patch.object(audio_engine, "_run", return_value=""):
            self.assertEqual(audio_engine.HELPER_ERROR, audio_engine.restart_elevated())

    def test_a_missing_tool_is_a_failure_not_a_crash(self):
        with mock.patch.object(audio_engine.subprocess, "run",
                               side_effect=FileNotFoundError("sc.exe")), \
                mock.patch.object(audio_engine.time, "sleep"):
            self.assertEqual(audio_engine.NOT_STOPPED, audio_engine.restart_elevated())


class ElevationTests(unittest.TestCase):
    """restart() asks Windows to start a copy of Echo as admin: one UAC prompt,
    no PowerShell, no script on the command line."""

    def setUp(self):
        if sys.platform != "win32":
            self.skipTest("Windows only")

    def test_it_elevates_a_copy_of_echo_not_powershell(self):
        with mock.patch.object(audio_engine, "_shell_execute", return_value=0) as se:
            self.assertEqual(audio_engine.RESTARTED, audio_engine.restart())
        verb, program, params, _ = se.call_args[0]
        self.assertEqual("runas", verb)
        self.assertEqual(audio_engine._helper_command()[0], program)
        self.assertIn(audio_engine.HELPER_ARG, params)
        self.assertNotIn("powershell", (program + params).lower())

    def test_frozen_it_starts_the_exe_with_only_the_flag(self):
        with mock.patch.object(audio_engine.sys, "frozen", True, create=True):
            self.assertEqual((sys.executable, [audio_engine.HELPER_ARG]),
                             audio_engine._helper_command())

    def test_saying_no_is_cancelled(self):
        with mock.patch.object(audio_engine, "_shell_execute",
                               return_value=audio_engine.CANCELLED):
            self.assertEqual(audio_engine.CANCELLED, audio_engine.restart())

    def test_the_elevated_exit_code_comes_back(self):
        with mock.patch.object(audio_engine, "_shell_execute",
                               return_value=audio_engine.NOT_STOPPED):
            self.assertEqual(audio_engine.NOT_STOPPED, audio_engine.restart())

    def test_an_unanswered_prompt_times_out_as_cancelled(self):
        gate = threading.Event()
        try:
            with mock.patch.object(audio_engine, "_shell_execute",
                                   side_effect=lambda *a: gate.wait(5) and 0):
                self.assertEqual(audio_engine.CANCELLED,
                                 audio_engine.restart(timeout=0.2))
        finally:
            gate.set()

    def test_a_launch_error_is_a_failure(self):
        with mock.patch.object(audio_engine, "_shell_execute",
                               side_effect=OSError("boom")):
            code = audio_engine.restart()
        self.assertNotIn(code, (audio_engine.RESTARTED, audio_engine.CANCELLED))

    def test_app_hands_the_flag_to_the_elevated_half_before_anything_else(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "app.py"), encoding="utf-8") as f:
            src = f.read()
        check = f'sys.argv[1:2] == ["{audio_engine.HELPER_ARG}"]'
        self.assertIn(check, src)
        self.assertLess(src.index(check), src.index("import pyi_runtime"))
        self.assertLess(src.index(check), src.index("_ensure_single_instance()"))

    def test_app_exits_with_the_elevated_halfs_code(self):
        # The real app.py, with only the elevated half stubbed: it must exit
        # with that code before the runtime guard (whose relaunch exits 0 and
        # would read as a restart), the mutex or the window.
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        probe = ("import sys, runpy, audio_engine\n"
                 "audio_engine.restart_elevated = lambda: 42\n"
                 "sys.argv = ['app.py', audio_engine.HELPER_ARG]\n"
                 "runpy.run_path('app.py', run_name='__main__')\n")
        r = subprocess.run([sys.executable, "-c", probe], cwd=root,
                           capture_output=True, timeout=60,
                           creationflags=audio_engine._NO_WINDOW)
        self.assertEqual(42, r.returncode, r.stderr.decode(errors="replace")[-2000:])


class ShellExecutePlumbingTests(unittest.TestCase):
    """The real ShellExecuteExW path with the plain "open" verb (no UAC):
    struct layout, wait and exit code."""

    def setUp(self):
        if sys.platform != "win32":
            self.skipTest("Windows only")

    def test_struct_matches_the_windows_layout(self):
        size = 112 if ctypes.sizeof(ctypes.c_void_p) == 8 else 60
        self.assertEqual(size, ctypes.sizeof(audio_engine._SHELLEXECUTEINFOW))

    def test_exit_code_comes_back(self):
        program = audio_engine._helper_command()[0]  # pythonw: no console
        code = audio_engine._shell_execute(
            "open", program, '-c "import sys; sys.exit(7)"', 60)
        self.assertEqual(7, code)

    def test_a_program_that_is_not_there_fails_quietly(self):
        missing = os.path.join(os.path.dirname(sys.executable), "no-such-program.exe")
        code = audio_engine._shell_execute("open", missing, "", 10)
        self.assertNotIn(code, (audio_engine.RESTARTED, audio_engine.CANCELLED))


if __name__ == "__main__":
    unittest.main()
