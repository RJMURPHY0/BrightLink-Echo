"""Crash watch and update gate contract: a real crash in a real process is seen
by the next run, a deliberate exit is not, and an update never restarts Echo
under someone who is still working."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import crash_watch
from crash_watch import CrashWatch, classify_previous, exception_summary
from update_gate import RestartGate, safe_to_restart

_CHILD = textwrap.dedent("""
    import faulthandler, os, sys, time
    sys.path.insert(0, {root!r})
    from crash_watch import CrashWatch
    watch = CrashWatch({folder!r}, "9.9.9", boot_time=lambda: 0.0)
    watch.start()
    mode = {mode!r}
    if mode == "native":
        faulthandler._sigsegv()
    elif mode == "killed":
        os._exit(3)
    else:
        watch.mark_exit("quit")
        os._exit(0)
""")


def _run_child(folder, mode):
    code = _CHILD.format(root=ROOT, folder=folder, mode=mode)
    subprocess.run([sys.executable, "-I", "-c", code], capture_output=True,
                   timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)


def _pending(folder):
    path = os.path.join(folder, crash_watch.PENDING_FILE)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class RealProcessEnd(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.folder = self._dir.name
        with open(os.path.join(self.folder, "echo.log"), "w", encoding="utf-8") as f:
            f.write("[2026-11-06 23:00:00] [Recorder] last line\n")

    def tearDown(self):
        self._dir.cleanup()

    def _next_run(self):
        watch = CrashWatch(self.folder, "10.0.0", boot_time=lambda: 0.0)
        return watch, watch._judge_previous()

    def test_segfault_is_reported_with_its_trace_and_log_tail(self):
        _run_child(self.folder, "native")
        _, verdict = self._next_run()
        self.assertEqual(verdict, "native_crash")
        report = _pending(self.folder)[0]
        self.assertEqual(report["kind"], "app_crashed")
        self.assertEqual(report["detail"]["cause"], "native_crash")
        self.assertEqual(report["detail"]["version"], "9.9.9")
        self.assertIn("Fatal", report["detail"]["native_trace"])
        self.assertIn("last line", report["detail"]["log_tail"])

    def test_a_killed_process_is_reported(self):
        _run_child(self.folder, "killed")
        _, verdict = self._next_run()
        self.assertEqual(verdict, "vanished")
        self.assertEqual(_pending(self.folder)[0]["detail"]["cause"], "vanished")

    def test_a_deliberate_exit_is_not_a_crash(self):
        _run_child(self.folder, "clean")
        _, verdict = self._next_run()
        self.assertEqual(verdict, "clean")
        self.assertEqual(_pending(self.folder), [])


class Classify(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(classify_previous(None, 0), "none")
        self.assertEqual(classify_previous({"exit": "update", "beat": 5}, 0), "clean")
        self.assertEqual(classify_previous({"beat": 100}, 200), "machine_restart")
        self.assertEqual(classify_previous({"beat": 300}, 200), "vanished")
        self.assertEqual(classify_previous({"beat": 300}, 200, "trace"), "native_crash")


class Reports(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.watch = CrashWatch(self._dir.name, "1.0", restart_fn=lambda why: None)

    def tearDown(self):
        self._dir.cleanup()

    def _boom(self):
        try:
            raise ValueError("dictated words must not be sent")
        except ValueError:
            return sys.exc_info()

    def test_refused_report_waits_and_is_sent_later(self):
        self.watch._queue("app_crashed", {"cause": "x"})
        self.watch._reporter = lambda kind, detail: False
        self.assertEqual(self.watch.flush(), 0)
        self.assertEqual(len(_pending(self._dir.name)), 1)
        self.watch._reporter = lambda kind, detail: True
        self.assertEqual(self.watch.flush(), 1)
        self.assertEqual(_pending(self._dir.name), [])

    def test_raising_reporter_keeps_the_report(self):
        self.watch._queue("app_crashed", {"cause": "x"})

        def _bad(kind, detail):
            raise OSError("offline")

        self.watch._reporter = _bad
        self.assertEqual(self.watch.flush(), 0)
        self.assertEqual(len(_pending(self._dir.name)), 1)

    def test_exception_summary_never_holds_the_message(self):
        summary = exception_summary(*self._boom())
        self.assertEqual(summary["exception"], "ValueError")
        self.assertNotIn("dictated", json.dumps(summary))
        self.assertIn("_boom", summary["frames"][-1])

    def test_same_error_reports_once_per_run(self):
        info = self._boom()
        self.watch.note_exception("ui_error", *info)
        self.watch.note_exception("ui_error", *info)
        self.assertEqual(len(_pending(self._dir.name)), 1)

    def test_restart_limit_stops_a_crash_loop(self):
        restarts = []
        self.watch._restart_fn = restarts.append
        for _ in range(crash_watch.MAX_RESTARTS_PER_HOUR + 2):
            self.watch._restart("fatal")
        self.assertEqual(len(restarts), crash_watch.MAX_RESTARTS_PER_HOUR)
        self.assertEqual(_pending(self._dir.name)[-1]["detail"]["cause"],
                         "restart_limit_reached")


class Hang(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.restarts = []
        self.watch = CrashWatch(self._dir.name, "1.0", restart_fn=self.restarts.append)
        self.addCleanup(self._dir.cleanup)

    def _kinds(self):
        return [p["kind"] for p in _pending(self._dir.name)]

    def test_short_wait_is_not_a_hang(self):
        self.watch._tk_beat = 100.0
        self.watch.check_hang(100.0 + crash_watch.HANG_REPORT_S - 1)
        self.assertEqual(self._kinds(), [])

    def test_hang_reports_once_with_stacks(self):
        self.watch._tk_beat = 100.0
        self.watch.check_hang(100.0 + crash_watch.HANG_REPORT_S + 1)
        self.watch.check_hang(100.0 + crash_watch.HANG_REPORT_S + 20)
        self.assertEqual(self._kinds(), ["ui_hang"])
        self.assertIn("File", _pending(self._dir.name)[0]["detail"]["stacks"])
        self.assertEqual(self.restarts, [])

    def test_long_hang_restarts_only_when_not_dictating(self):
        self.watch._tk_beat = 100.0
        self.watch.set_busy_check(lambda: True)
        self.watch.check_hang(100.0 + crash_watch.HANG_RESTART_S + 1)
        self.assertEqual(self.restarts, [])
        self.watch.set_busy_check(lambda: False)
        self.watch.check_hang(100.0 + crash_watch.HANG_RESTART_S + 2)
        self.assertEqual(self.restarts, ["hang"])

    def test_sleep_does_not_read_as_a_hang(self):
        self.watch._tk_beat = 100.0
        now = 100.0 + crash_watch.HANG_RESTART_S * 2
        self.watch._tick(now, gap=crash_watch.STALL_S + 1)
        self.assertEqual(self._kinds(), [])
        self.assertEqual(self.watch._tk_beat, now)


class UpdateGate(unittest.TestCase):
    def test_still_at_the_keyboard_waits(self):
        # 6 Nov 2026: 3 minutes after a dictation, typing, the app closed.
        self.assertFalse(safe_to_restart(True, 180, 5, 1500))

    def test_away_restarts(self):
        self.assertTrue(safe_to_restart(True, 700, 600, 1500))

    def test_never_during_or_right_after_a_dictation(self):
        self.assertFalse(safe_to_restart(False, 9999, 9999, 999999))
        self.assertFalse(safe_to_restart(True, 60, 9999, 999999))

    def test_an_update_still_lands_after_a_day(self):
        self.assertTrue(safe_to_restart(True, 180, 5, 24 * 3600))

    def test_gate_counts_from_first_ask(self):
        ticks = iter([10.0, 25.0])
        gate = RestartGate(clock=lambda: next(ticks))
        self.assertEqual(gate.waiting_s(), 0.0)
        self.assertEqual(gate.waiting_s(), 15.0)


class Celebration(unittest.TestCase):
    def test_every_update_popup_widget_gets_a_real_colour(self):
        # Canvas bg="" raised TclError, so the popup never showed on any update.
        src = open(os.path.join(ROOT, "app_window.py"), encoding="utf-8").read()
        body = src.split("def show_update_celebration", 1)[1].split("# ── Auth callbacks", 1)[0]
        self.assertNotIn('bg=""', body)

    def test_popup_builds_for_real(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display: {e}")
        self.addCleanup(root.destroy)
        root.withdraw()
        import app_window
        holder = app_window.AppWindow.__new__(app_window.AppWindow)
        holder._root = root
        holder.show_update_celebration("1.0.0", "1.0.1", "BrightLink Echo")
        root.update()
        tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertEqual(len(tops), 1)
        self.assertEqual(tops[0].winfo_children()[0].winfo_class(), "Canvas")


if __name__ == "__main__":
    unittest.main()
