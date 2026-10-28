"""The app exits for an update only once the helper it started says it runs.

Audit 2026-10-28: apply_installed_update and apply_update Popen'd the helper
(activate.ps1 / the swap script) and exited at once. Antivirus that killed
powershell.exe on start left no app and no update. The uninstaller already
waited for its script's first log line (app_install._cleanup_confirmed); the
updater now does the same, per attempt.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import install_layout as il  # noqa: E402
import updater  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Exited(Exception):
    pass


def _raise_exit(code):
    raise _Exited(code)


class HelperConfirmedTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.log = os.path.join(self.dir, "update.log")

    def test_only_a_line_written_after_the_offset_counts(self):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("Started. Mode=Update WaitPid=42\n")      # an older attempt
        offset = os.path.getsize(self.log)
        self.assertFalse(updater.helper_confirmed(
            self.log, offset, "Started. Mode=Update WaitPid=42", wait=0))
        with open(self.log, "a", encoding="utf-8-sig") as f:
            f.write("[x] [activate 1.8.0] Started. Mode=Update WaitPid=42 Relaunch=True\n")
        self.assertTrue(updater.helper_confirmed(
            self.log, offset, "Started. Mode=Update WaitPid=42", wait=0))

    def test_a_missing_log_is_not_a_confirmation(self):
        self.assertFalse(updater.helper_confirmed(self.log, 0, "x", wait=0))

    def test_a_log_that_shrank_is_read_from_the_start(self):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("Update started. PID=7\n")
        self.assertTrue(updater.helper_confirmed(self.log, 10_000, "Update started. PID=7", wait=0))


class ApplyWaitsForTheHelperTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        updater._apply_started = False
        updater._helper_proc = None
        self.addCleanup(setattr, updater, "_apply_started", False)
        self.addCleanup(setattr, updater, "_helper_proc", None)
        for p in (mock.patch.object(updater, "_HELPER_CONFIRM_SECONDS", 0.0),
                  mock.patch.object(updater.time, "sleep", lambda _s: None),
                  mock.patch.object(updater.os, "_exit", _raise_exit)):
            p.start()
            self.addCleanup(p.stop)

    def _activation_spawner(self, starts):
        log = os.path.join(self.dir, il.UPDATE_LOG)

        def spawn(version, pid, root="", launch=True):
            if starts:
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"[t] [activate 1.8.0] Started. Mode=Update WaitPid={pid} Relaunch=True\n")
            return "script"
        return spawn

    def test_activation_killed_at_start_keeps_the_app_running(self):
        with mock.patch.object(updater, "spawn_activation", self._activation_spawner(False)):
            self.assertFalse(updater.apply_installed_update("1.8.0", self.dir))
        with open(os.path.join(self.dir, il.UPDATE_LOG), encoding="utf-8") as f:
            self.assertIn("did not start", f.read())

    def test_activation_that_logs_its_start_lets_the_app_exit(self):
        with mock.patch.object(updater, "spawn_activation", self._activation_spawner(True)):
            with self.assertRaises(_Exited):
                updater.apply_installed_update("1.8.0", self.dir)

    def test_an_unconfirmed_helper_is_stopped_and_update_now_can_retry(self):
        # Left running, a helper that started late would wait for this
        # process and then close it mid-dictation (Codex review 2026-10-28).
        killed = []
        proc = mock.Mock(poll=mock.Mock(side_effect=[None, 1]),
                         kill=lambda: killed.append(1), wait=lambda _t: 1)
        calls = []

        def spawn(*a, **k):
            calls.append(a)
            updater._helper_proc = proc
        with mock.patch.object(updater, "spawn_activation", spawn):
            self.assertFalse(updater.apply_installed_update("1.8.0", self.dir))
        self.assertEqual([1], killed)
        with mock.patch.object(updater, "spawn_activation", lambda *a, **k: calls.append(a)):
            updater._helper_proc = None
            self.assertFalse(updater.apply_installed_update("1.8.0", self.dir))
        self.assertEqual(2, len(calls))

    def test_a_helper_that_cannot_be_stopped_never_gets_a_twin(self):
        proc = mock.Mock(poll=mock.Mock(return_value=None),
                         kill=mock.Mock(side_effect=PermissionError("denied")))
        calls = []

        def spawn(*a, **k):
            calls.append(a)
            updater._helper_proc = proc
        with mock.patch.object(updater, "spawn_activation", spawn):
            self.assertFalse(updater.apply_installed_update("1.8.0", self.dir))
            self.assertFalse(updater.apply_installed_update("1.8.0", self.dir))
        self.assertEqual(1, len(calls))

    def test_a_dictation_started_during_the_wait_is_not_cut_off(self):
        # Confirmation can take seconds after the idle check: exit only once
        # the app is idle again.
        answers = iter([False, False, True])
        seen = []

        def is_idle():
            v = next(answers)
            seen.append(v)
            return v
        with mock.patch.object(updater, "spawn_activation", self._activation_spawner(True)):
            with self.assertRaises(_Exited):
                updater.apply_installed_update("1.8.0", self.dir, is_idle=is_idle)
        self.assertEqual([False, False, True], seen)

    def _swap(self, starts):
        def spawn(new_exe, current_exe, pid, sha256="", log_file=None, **kw):
            if starts:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"[00:00:00] Update started. PID={pid}\n")
            return log_file
        return spawn

    def test_swap_script_killed_at_start_keeps_the_app_running(self):
        log = os.path.join(self.dir, "swap.log")
        with mock.patch.object(updater, "_swap_log_path", lambda: log), \
                mock.patch.object(updater, "spawn_swap_script", self._swap(False)):
            self.assertFalse(updater.apply_update("new.exe", "cur.exe", sha256="ab" * 32))

    def test_swap_script_that_logs_its_start_lets_the_app_exit(self):
        log = os.path.join(self.dir, "swap.log")
        with mock.patch.object(updater, "_swap_log_path", lambda: log), \
                mock.patch.object(updater, "spawn_swap_script", self._swap(True)):
            with self.assertRaises(_Exited):
                updater.apply_update("new.exe", "cur.exe", sha256="ab" * 32)


class MarkerContractTests(unittest.TestCase):
    """The lines the app waits for must stay in the helpers."""

    def test_activate_ps1_logs_the_started_line(self):
        with open(os.path.join(_ROOT, "installer", "activate.ps1"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('Log "Started. Mode=$Mode WaitPid=$WaitPid', src)

    def test_swap_script_logs_the_started_line(self):
        import inspect
        src = inspect.getsource(updater.spawn_swap_script)
        self.assertIn('Log "Update started. PID={pid}"', src)


if __name__ == "__main__":
    unittest.main()
