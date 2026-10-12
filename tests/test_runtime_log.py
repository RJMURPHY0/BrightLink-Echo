"""echo.log: the windowed exe's prints, kept locally, never the user's words."""

import base64
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import runtime_log
from runtime_log import redact


def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


class RedactTests(unittest.TestCase):

    def test_dictated_text_never_reaches_the_log(self):
        for line in (
                "[App] Transcription (parakeet): 'meet at the dentist at four'",
                "[App] Discarding near-silence result 'thank you' (peak=0.0010)",
                "[App] Empty final pass; keeping streamed text 'send it to Jason'.",
                "[AIRefiner] got \"the refined words here\"",
                "KeyError: 'what I said'"):
            out = redact(line)
            for word in ("dentist", "thank you", "Jason", "refined words", "what I said"):
                self.assertNotIn(word, out)
        self.assertEqual(
            redact("[App] Transcription (parakeet): 'meet at four'"),
            "[App] Transcription (parakeet): <12 chars>")

    def test_device_and_hotkey_names_are_kept(self):
        line = "[Recorder] Warm mic stream open ('Headset Microphone (Jabra)', 48000 Hz)."
        self.assertEqual(redact(line), line)
        self.assertIn("'alt+b'", redact("[HotkeyManager] registered 'alt+b'"))

    def test_tokens_and_keys_are_masked_on_every_tag(self):
        jwt = ".".join(_b64(part) for part in ('{"alg":"HS256"}', '{"sub":"1234567890"}')) + ".c2lnbmF0dXJlLXZhbHVl"   # a fake JWT, built here so no token-shaped
        # literal sits in the source (the secret scanner blocks those)
        for line in (f"[Auth] Sign-up result: session=Session(access_token={jwt})",
                     f"[Recorder] odd {jwt}",
                     "[Auth] refresh_token=" + "abcdef" + "123456" + " kept",
                     "[Supabase] key sb_publishable_G96rQQGq8BEtutrsd",
                     "[AIRefiner] using sk-or-v1-0123456789abcdef"):
            out = redact(line)
            self.assertNotIn("eyJhbGci", out)
            self.assertNotIn("abcdef123456", out)
            self.assertNotIn("G96rQQ", out)
            self.assertNotIn("0123456789abcdef", out)


class LogFileTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "echo.log")

    def read(self, path=None):
        with open(path or self.path, encoding="utf-8") as f:
            return f.read()

    def test_whole_lines_are_stamped_and_redacted(self):
        log = runtime_log._LogFile(self.path)
        print("[App] Transcription: 'secret words'", file=log)
        log.write("[Recorder] partial ")
        self.assertNotIn("partial", self.read())
        log.write("line\n")
        text = self.read()
        self.assertNotIn("secret words", text)
        self.assertRegex(text, r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] \[App\] Transcription: <12 chars>\n")
        self.assertIn("[Recorder] partial line", text)

    def test_the_file_is_capped_with_one_previous_kept(self):
        log = runtime_log._LogFile(self.path, max_bytes=200)
        for i in range(60):
            print(f"[Recorder] line {i:03d}", file=log)
        self.assertLessEqual(os.path.getsize(self.path), 400)
        self.assertTrue(os.path.exists(self.path + ".1"))
        self.assertIn("line 059", self.read())

    def test_installs_only_without_a_console(self):
        with mock.patch.object(sys, "stdout", io.StringIO()), \
                mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertFalse(runtime_log.install(self.path))
        with mock.patch.object(sys, "stdout", None), \
                mock.patch.object(sys, "stderr", None):
            self.assertTrue(runtime_log.install(self.path))
            print("[Recorder] hello from a windowed exe")
            sys.stderr.write("Traceback: ValueError('typed words')\n")
            out, err = sys.stdout, sys.stderr
        self.assertIsInstance(out, runtime_log._LogFile)
        self.assertIs(out, err)
        text = self.read()
        self.assertIn("hello from a windowed exe", text)
        self.assertNotIn("typed words", text)

    def test_app_installs_it_first_thing_in_main(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "app.py"), encoding="utf-8").read()
        main = src[src.index("def main() -> None:"):]
        self.assertLess(main.index("runtime_log.install("), main.index("_main()"))


if __name__ == "__main__":
    unittest.main()
