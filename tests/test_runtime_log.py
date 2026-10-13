"""echo.log: the windowed exe's prints, kept locally, never the user's words."""

import base64
import io
import os
import re
import shutil
import sys
import tempfile
import threading
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


class AwkwardTextTests(unittest.TestCase):
    """Dictation is full of apostrophes. The old pattern ended the quoted
    span at the first one, so everything after "it's" went to disk."""

    SECRET = ("dentist", "Jason", "invoice", "worry", "tomorrow", "mine",
              "pay it", "said", "paid", "they're", "their")

    def assertHidden(self, out):
        for word in self.SECRET:
            self.assertNotIn(word, out)

    def test_contractions_do_not_end_the_redaction(self):
        for line in (
                "[App] Transcription: 'it's fine, don't worry about it'",
                "[App] Transcription (parakeet): 'I'll see the dentist, won't I'",
                "[AIRefiner] Refined via OpenRouter (punctuation): 'Jason's invoice isn't paid'",
                "[App] Discarding near-silence result 'it's fine' (peak=0.0010), no speech.",
                "[App] Sound-alike fix: 'they're fine' -> 'their fine'",
                "KeyError: \"it's mine\""):
            with self.subTest(line=line):
                self.assertHidden(redact(line))
        self.assertIn("(peak=0.0010)", redact(
            "[App] Discarding near-silence result 'it's fine' (peak=0.0010)"))

    def test_curly_and_nested_quotes(self):
        for line in (
                "[App] Transcription: \u2018it\u2019s fine, don\u2019t worry\u2019",
                "[App] Transcription: \u201cmeet Jason at the dentist\u201d",
                "[App] Transcription: 'he said \"don't\" to Jason'",
                "[App] Transcription: \"she said 'it's mine' and left tomorrow\"",
                "[App] Transcription: \u00abmeet Jason\u00bb"):
            with self.subTest(line=line):
                self.assertHidden(redact(line))

    def test_emoji_and_line_breaks(self):
        self.assertHidden(redact("[App] Transcription: 'see you tomorrow \U0001F60A it's fine'"))
        out = redact("[App] Transcription: 'Dear Jason,\nThanks for the invoice.\n"
                     "I'll pay it tomorrow.'\n")
        self.assertHidden(out)
        self.assertTrue(out.startswith("[App] Transcription: <"))

    def test_a_traceback_frame_keeps_its_line_number(self):
        out = redact('  File "C:\\Echo\\app.py", line 1950, in _transcribe\n'
                     "    print(f\"[App] got '{t}'\")\n")
        self.assertIn("line 1950, in _transcribe", out)

    def test_email_addresses_are_masked_whatever_the_tag(self):
        for line in ("[App] Signed in as jo.bloggs+echo@example.co.uk",
                     "[Recorder] odd jo@example.com"):
            self.assertNotIn("example", redact(line))

    def test_no_part_of_an_unusual_email_address_survives(self):
        # Issue #4: every character RFC 5322 allows in the local part, an
        # apostrophe included, so "o'" or "a#" never stays behind.
        for address in ("o'neil@example.com", "a#b@example.com",
                        "first!last@example.co.uk", "x%y&z@mail.example.org",
                        "tom{1}@example.com", "o’neil@example.com"):
            for tag in ("App", "Recorder"):
                out = redact(f"[{tag}] Signed in as {address}")
                self.assertEqual(out, f"[{tag}] Signed in as <email>", address)

    def test_a_quoted_email_still_hides_the_whole_quote(self):
        # Masking the address must never eat the quote mark that hides the
        # dictated words around it.
        out = redact("[App] got 'bob@example.com and see you at four'")
        self.assertNotIn("see you", out)
        self.assertNotIn("example", out)

    def test_setting_values_are_logged_by_size_only(self):
        self.assertEqual(runtime_log.safe_value(True), "True")
        self.assertEqual(runtime_log.safe_value(3), "3")
        self.assertEqual(runtime_log.safe_value(None), "None")
        self.assertEqual(runtime_log.safe_value("Ryan Murphy"), "<11 chars>")
        self.assertEqual(runtime_log.safe_value(["brb", "be right back"]),
                         "<list, 2 items>")
        self.assertEqual(runtime_log.safe_value({"a": 1}), "<dict, 1 items>")


class CallSiteTests(unittest.TestCase):
    """Structure first: no runtime module prints user text in quotes. The
    redaction above is only the safety net behind this."""

    USER_TEXT = re.compile(
        r"""(?<![fFrRbB])['"\u2018\u201c]\{(?:text|_text|transcribed_text|fast_text|accurate|"""
        r"""fixed|rescued|_streamed|new_text|result|preview|cleaned|_hf|_sc|"""
        r"""original|refined|clip\w*|selection)\b[^}]*\}""")

    def test_no_module_logs_dictated_text(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        found = []
        for name in sorted(os.listdir(root)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(root, name), encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if self.USER_TEXT.search(line):
                        found.append(f"{name}:{n}: {line.strip()}")
        self.assertEqual(found, [])


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

    def test_a_multi_line_dictation_is_redacted_whole(self):
        log = runtime_log._LogFile(self.path)
        print("[App] Transcription: 'Dear Jason,\nThanks for the invoice.\n"
              "I'll pay it tomorrow, it's fine.'", file=log)
        print("[App] Transcription: ‘it’s mine\nsaid Jason’ (3 words)", file=log)
        text = self.read()
        for word in ("Jason", "invoice", "pay it", "tomorrow", "mine", "said"):
            self.assertNotIn(word, text)
        self.assertIn("(3 words)", text)
        self.assertEqual(text.count("[App] Transcription: <"), 2)

    def test_two_threads_never_share_a_block(self):
        log = runtime_log._LogFile(self.path)
        log.write("[Recorder] Warm mic stream open ('Headset Mic')")
        other = threading.Thread(
            target=lambda: print("[App] Transcription: 'it's Jason'", file=log))
        other.start()
        other.join()
        log.write("\n")
        text = self.read()
        self.assertNotIn("Jason", text)
        self.assertIn("'Headset Mic'", text)

    def test_a_print_with_no_line_end_is_dropped_not_split(self):
        log = runtime_log._LogFile(self.path)
        log.write("[App] Transcription: 'it's " + "Jason " * 20000)
        log.write("more words'\n")
        print("[Recorder] next line", file=log)
        text = self.read()
        self.assertNotIn("Jason", text)
        self.assertNotIn("more words", text)
        self.assertIn("no line end dropped", text)
        self.assertIn("[Recorder] next line", text)

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
