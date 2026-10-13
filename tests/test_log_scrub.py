"""Logs written by v1.8.12 and earlier are scrubbed once per install.

Those builds redacted echo.log line by line and ended a quoted span at the
first apostrophe, so dictated words could survive in it; auth-restore.log held
the full email address. runtime_log.scrub_old_logs() rewrites both."""

import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import runtime_log

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STAMP = "[2026-10-01 09:15:42] "
_OLD_QUOTED = re.compile(r"'[^'\n]*'|\"[^\"\n]*\"")


def _old_redact(line):
    """What v1.8.11 and v1.8.12 did to each line before writing it."""
    m = runtime_log._TAG.match(line)
    if not (m and m.group(1) in runtime_log._KEEP_QUOTES):
        line = _OLD_QUOTED.sub(lambda q: f"<{len(q.group(0)) - 2} chars>", line)
    return line


def _old_log(*prints):
    """An echo.log as the old writer left it: every line stamped and
    redacted on its own."""
    return "".join(f"{_STAMP}{_old_redact(line)}\n"
                   for p in prints for line in p.split("\n"))


SECRET_WORDS = ("Jason", "dentist", "invoice", "tomorrow", "worry", "mine",
                "s fine", "Ryan Murphy", "jo.bloggs", "example.com", "pay it")

OLD_PRINTS = (
    "[Recorder] Warm mic stream open ('Headset Microphone (Jabra)', 48000 Hz).",
    "[App] Transcription: 'it's fine, don't worry about it'",
    "[App] Transcription (parakeet): 'Dear Jason,\nThanks for the invoice.\n"
    "I'll pay it tomorrow.'",
    "[App] Transcription: \u2018it\u2019s mine, said Jason\u2019",
    "[App] Transcription: \u201cmeet Jason at the dentist\u201d",
    "[App] Signed in as jo.bloggs+echo@example.com",
    "[App] Email sign-off name: Ryan Murphy",
    "[App] Discarding near-silence result 'it's fine' (peak=0.0010), no speech.",
    "Traceback (most recent call last):\n"
    "  File \"C:\\Echo\\app.py\", line 1950, in _transcribe\n"
    "    print(f\"[App] got '{t}'\")\n"
    "KeyError: 'it's mine, Jason'",
    "[App] Transcription: 'Dear Jason,\nsee you tomorrow at the dentist",
    "[App] Couldn't open the mic",
    "[HotkeyManager] registered 'alt+b'",
)


class _Base(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.local = os.path.join(self.dir, "BrightLink Echo")
        self.legacy = os.path.join(self.dir, "FTC Whisper")
        os.makedirs(self.local)
        patcher = mock.patch.object(runtime_log, "_installed", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def scrub(self, **kw):
        return runtime_log.scrub_old_logs(
            (self.local, self.legacy), self.local, **kw)

    def assertClean(self, text):
        for word in SECRET_WORDS:
            self.assertNotIn(word, text)


class EchoLogScrubTests(_Base):

    def test_old_dictation_and_emails_are_scrubbed(self):
        path = os.path.join(self.local, "echo.log")
        old = _old_log(*OLD_PRINTS)
        # The old redaction really did leave these on disk.
        for leaked in ("s fine, don", "Dear Jason,", "Thanks for the invoice.",
                       "jo.bloggs", "Ryan Murphy", "it\u2019s mine"):
            self.assertIn(leaked, old)
        self.write(path, old)

        result = self.scrub()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["rewritten"], 1)
        text = self.read(path)
        self.assertClean(text)
        # Diagnostics survive.
        self.assertIn("('Headset Microphone (Jabra)', 48000 Hz)", text)
        self.assertIn("[HotkeyManager] registered 'alt+b'", text)
        self.assertIn("(peak=0.0010), no speech.", text)
        self.assertIn("line 1950, in _transcribe", text)
        self.assertIn("Traceback (most recent call last):", text)
        self.assertIn("[App] Couldn't open the mic", text)
        self.assertIn("[App] Signed in as <email>", text)
        self.assertIn("[App] Email sign-off name: <11 chars>", text)
        # Every line keeps a stamp and the file ends with a line end.
        self.assertTrue(all(l.startswith(_STAMP) for l in text.splitlines()))
        self.assertTrue(text.endswith("\n"))

    def test_rotated_and_legacy_folder_logs_are_scrubbed_too(self):
        os.makedirs(self.legacy)
        paths = (os.path.join(self.local, "echo.log.1"),
                 os.path.join(self.legacy, "echo.log"),
                 os.path.join(self.legacy, "echo.log.1"))
        for p in paths:
            self.write(p, _old_log(*OLD_PRINTS))
        result = self.scrub()
        self.assertEqual(result["rewritten"], 3)
        for p in paths:
            self.assertClean(self.read(p))

    def test_a_missing_legacy_folder_is_never_created(self):
        self.write(os.path.join(self.local, "echo.log"), _old_log(*OLD_PRINTS))
        self.scrub()
        self.assertFalse(os.path.exists(self.legacy))

    def test_lines_written_by_this_version_stay_readable(self):
        path = os.path.join(self.local, "echo.log")
        log = runtime_log._LogFile(path)
        print("[App] Transcription: 'it's Jason'", file=log)
        print("[App] Transcription (parakeet): 12 chars", file=log)
        print("[Recorder] Warm mic stream open ('Headset Mic', 48000 Hz).", file=log)
        before = self.read(path)
        self.scrub()
        after = self.read(path)
        self.assertNotIn("Jason", after)
        self.assertEqual(after, before)

    def test_the_marker_stops_a_second_pass(self):
        path = os.path.join(self.local, "echo.log")
        self.write(path, _old_log(*OLD_PRINTS))
        self.assertFalse(self.scrub()["skipped"])
        self.assertTrue(os.path.isfile(
            os.path.join(self.local, runtime_log.SCRUB_MARKER)))
        # Anything there now was written by a scrubbing build; leave it be.
        self.write(path, "[2026-10-02 10:00:00] [App] it's left alone\n")
        with mock.patch.object(runtime_log, "scrub_echo_log") as job:
            result = self.scrub()
        self.assertTrue(result["skipped"])
        job.assert_not_called()
        self.assertEqual(self.read(path), "[2026-10-02 10:00:00] [App] it's left alone\n")

    def test_a_failure_does_not_raise_and_retries_next_launch(self):
        path = os.path.join(self.local, "echo.log")
        old = _old_log(*OLD_PRINTS)
        self.write(path, old)
        boom = PermissionError(13, "denied", "C:\\Users\\jo.bloggs\\echo.log")
        with mock.patch.object(runtime_log, "scrub_echo_log", side_effect=boom):
            result = self.scrub()
        self.assertEqual(result["errors"], ["PermissionError"])
        self.assertFalse(os.path.exists(
            os.path.join(self.local, runtime_log.SCRUB_MARKER)))
        self.assertEqual(self.read(path), old)
        # Next launch it works.
        self.assertEqual(self.scrub()["errors"], [])
        self.assertClean(self.read(path))

    def test_a_failure_mid_rewrite_leaves_the_original_and_no_temp_file(self):
        path = os.path.join(self.local, "echo.log")
        old = _old_log(*OLD_PRINTS)
        self.write(path, old)
        with mock.patch.object(runtime_log, "_scrub_old_block",
                               side_effect=MemoryError()):
            result = self.scrub()
        self.assertEqual(result["errors"], ["MemoryError"])
        self.assertEqual(self.read(path), old)
        self.assertEqual(sorted(os.listdir(self.local)), ["echo.log"])

    def test_bad_arguments_do_not_raise(self):
        result = runtime_log.scrub_old_logs(None, self.local)
        self.assertTrue(result["errors"])

    def test_a_leftover_temp_file_is_removed(self):
        tmp = os.path.join(self.local, "echo.log.scrub-tmp")
        self.write(tmp, "half done")
        self.scrub()
        self.assertFalse(os.path.exists(tmp))

    def test_an_oversized_log_is_deleted_not_rewritten(self):
        path = os.path.join(self.local, "echo.log")
        self.write(path, _old_log(*OLD_PRINTS) * 50)
        with mock.patch.object(runtime_log, "_SCRUB_MAX_BYTES", 1024):
            result = self.scrub()
        self.assertEqual(result["deleted"], 1)
        self.assertFalse(os.path.exists(path))

    def test_a_large_log_is_streamed(self):
        path = os.path.join(self.local, "echo.log")
        chunk = _old_log(*OLD_PRINTS)
        with open(path, "w", encoding="utf-8") as f:
            for _ in range(1000):
                f.write(chunk)
        size = os.path.getsize(path)
        self.assertGreater(size, 800_000)
        import tracemalloc
        tracemalloc.start()
        try:
            self.assertEqual(self.scrub()["errors"], [])
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, size // 4)     # never the whole file in memory
        text = self.read(path)
        self.assertClean(text)
        self.assertLess(os.path.getsize(path), size)

    def test_a_block_with_no_line_end_for_too_long_is_dropped(self):
        path = os.path.join(self.local, "echo.log")
        lines = ["[App] Transcription: 'Dear Jason,"] + ["it's the invoice"] * 6000
        self.write(path, "".join(f"{_STAMP}{l}\n" for l in lines)
                   + f"{_STAMP}[Recorder] next\n")
        self.scrub()
        text = self.read(path)
        self.assertClean(text)
        self.assertIn("chars in one block dropped", text)
        self.assertIn("[Recorder] next", text)


class AlongsideTheLiveWriterTests(_Base):

    def test_a_line_printed_during_the_scrub_is_kept(self):
        path = os.path.join(self.local, "echo.log")
        self.write(path, _old_log(*OLD_PRINTS))
        log = runtime_log._LogFile(path)
        real = runtime_log._scrub_old_block
        fired = []

        def block(text, kind):
            if not fired:
                fired.append(1)
                t = threading.Thread(
                    target=lambda: print("[Recorder] printed meanwhile", file=log))
                t.start()
                t.join()
            return real(text, kind)

        with mock.patch.object(runtime_log, "_installed", log), \
                mock.patch.object(runtime_log, "_scrub_old_block", side_effect=block):
            result = self.scrub()
        self.assertEqual(result["errors"], [])
        text = self.read(path)
        self.assertClean(text)
        self.assertIn("[Recorder] printed meanwhile", text)
        self.assertTrue(text.endswith("[Recorder] printed meanwhile\n"))

    def test_a_log_trimmed_during_the_scrub_is_left_for_next_launch(self):
        path = os.path.join(self.local, "auth-restore.log")
        self.write(path, "[2026-10-01 08:00:02] OK: restored session for jo@example.com\n" * 50)
        lock = threading.Lock()
        real = runtime_log.mask_identifiers
        fired = []

        def mask(text):
            if not fired:
                fired.append(1)
                with lock:   # what auth._restore_log's size cap does
                    self.write(path, "...trimmed...\n")
            return real(text)

        with mock.patch.object(runtime_log, "mask_identifiers", side_effect=mask):
            result = self.scrub(restore_lock=lock)
        self.assertEqual(result["errors"], ["_ChangedMeanwhile"])
        self.assertEqual(self.read(path), "...trimmed...\n")
        self.assertFalse(os.path.exists(
            os.path.join(self.local, runtime_log.SCRUB_MARKER)))
        self.assertFalse(any(n.endswith(".scrub-tmp") for n in os.listdir(self.local)))
        self.assertEqual(self.scrub(restore_lock=lock)["errors"], [])


class RestoreLogTests(_Base):

    def test_old_auth_restore_log_has_emails_masked(self):
        path = os.path.join(self.local, "auth-restore.log")
        self.write(path, (
            "[2026-10-01 08:00:01] --- boot: returning user ---\n"
            "[2026-10-01 08:00:02] OK: restored session for jo.bloggs@example.com\n"
            "[2026-10-01 08:00:03] MANUAL sign-in succeeded for pat.smith@example.org\n"
            "[2026-10-01 08:00:04] RETRY: network/other error, session kept: "
            "refresh_token=FAKE_TEST_TOKEN rejected\n"))
        result = self.scrub()
        self.assertEqual(result["errors"], [])
        text = self.read(path)
        self.assertNotIn("jo.bloggs", text)
        self.assertNotIn("pat.smith", text)
        self.assertNotIn("FAKE_TEST_TOKEN", text)
        self.assertIn("OK: restored session for j***@example.com", text)
        self.assertIn("MANUAL sign-in succeeded for p***@example.org", text)
        self.assertIn("--- boot: returning user ---", text)
        self.assertEqual(len(text.splitlines()), 4)

    def test_mask_email(self):
        self.assertEqual(runtime_log.mask_email("jo.bloggs@example.co.uk"),
                         "j***@example.co.uk")
        self.assertEqual(runtime_log.mask_email(""), "<none>")
        self.assertEqual(runtime_log.mask_email(None), "<none>")
        self.assertEqual(runtime_log.mask_email("not-an-email"), "<email>")


class AuthWritesTests(unittest.TestCase):

    def setUp(self):
        import auth
        self.auth = auth
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "auth-restore.log")
        patcher = mock.patch.object(auth, "_restore_log_path", lambda: self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_restore_log_never_holds_a_full_email(self):
        user = SimpleNamespace(id="3f1c9e2a-1111-2222-3333-444455556666",
                               email="jo.bloggs@example.com")
        self.auth._restore_log(f"OK: restored session for {self.auth._who(user)}")
        self.auth._restore_log("RETRY: error for jo.bloggs@example.com")
        with open(self.path, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("jo.bloggs", text)
        self.assertIn("user 3f1c9e2a (j***@example.com)", text)

    def test_who_falls_back_to_the_typed_email(self):
        self.assertEqual(self.auth._who(SimpleNamespace(id=None, email=None),
                                        "ann@example.org"),
                         "user ? (a***@example.org)")

    def test_no_print_or_restore_log_names_a_raw_email(self):
        with open(os.path.join(_ROOT, "auth.py"), encoding="utf-8") as f:
            src = f.read()
        calls = re.findall(r"(?:print|_restore_log)\((?:[^()]|\([^()]*\))*\)", src)
        bad = [c for c in calls
               if re.search(r"\{(?:[\w.]*\.)?email(?:\s+or\s+email)?\}", c)]
        self.assertEqual(bad, [])


class AppWiringTests(unittest.TestCase):

    def test_scrub_starts_after_the_single_instance_guard(self):
        with open(os.path.join(_ROOT, "app.py"), encoding="utf-8") as f:
            src = f.read()
        main = src[src.index("def _main() -> None:"):]
        guard = main.index("_ensure_single_instance()")
        scrub = main.index("target=_scrub_old_logs")
        self.assertLess(guard, scrub)
        self.assertLess(scrub, main.index("WhisperFlowApp(auth, config)"))

    def test_scrub_entry_point_never_raises(self):
        import app
        with mock.patch.object(app.runtime_log, "scrub_old_logs",
                               side_effect=RuntimeError("x")), \
                mock.patch("builtins.print") as out:
            app._scrub_old_logs()
        self.assertIn("RuntimeError", out.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
