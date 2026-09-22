"""Email layout.

Asked for directly: dictating into Outlook or Gmail, "Hi John, thanks for your
email ... Kind regards, Ryan" should land with the greeting, the sign-off and
the name each on their own line, and nothing anywhere else should change.

This changes the SHAPE of what the user said, so both directions are pinned:
the layout cases, and the text that must come back byte-identical (a body-only
press, a sentence that merely starts with "Morning", a reply of "Thanks.",
thanking the recipient by name). The app gate is pinned too, because a
greeting typed into Slack or Teams must stay on one line.
"""

import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import email_format
from email_format import format_email as fmt, format_signoff, is_email_app

ME = "Ryan Murphy"


class LayoutTests(unittest.TestCase):
    def test_the_reported_shape(self):
        self.assertEqual(
            fmt("Hi John, thanks for your email. I'll have a look at the quote "
                "and get back to you tomorrow. Kind regards, Ryan.", ME),
            "Hi John,\n\nThanks for your email. I'll have a look at the quote "
            "and get back to you tomorrow.\n\nKind regards,\nRyan")

    def test_no_punctuation_after_the_greeting(self):
        self.assertEqual(fmt("Hi John thanks for your email. Kind regards Ryan"),
                         "Hi John,\n\nThanks for your email.\n\nKind regards,\nRyan")

    def test_a_sentence_starter_is_not_part_of_the_name(self):
        self.assertEqual(fmt("Hi John I wanted to check the invoice.", ME),
                         "Hi John,\n\nI wanted to check the invoice.")

    def test_greeting_forms(self):
        cases = {
            "Hello, I want to ask about the quote.":
                "Hello,\n\nI want to ask about the quote.",
            "Morning all, quick update on the job.":
                "Morning all,\n\nQuick update on the job.",
            "Good morning, John. Hope you're well.":
                "Good morning, John,\n\nHope you're well.",
            "Dear Mr. Smith, please find attached.":
                "Dear Mr. Smith,\n\nPlease find attached.",
            "Dear Sir or Madam, I am writing to complain.":
                "Dear Sir or Madam,\n\nI am writing to complain.",
            "Hi John and Sarah, see below.":
                "Hi John and Sarah,\n\nSee below.",
            "Hi there how are you doing":
                "Hi there,\n\nHow are you doing",
            "Hi, Thanks for getting back to me.":
                "Hi,\n\nThanks for getting back to me.",
        }
        for src, want in cases.items():
            with self.subTest(src=src):
                self.assertEqual(fmt(src), want)

    def test_just_the_greeting_leaves_the_caret_on_the_body_line(self):
        self.assertEqual(fmt("Hi John."), "Hi John,\n\n")
        self.assertEqual(fmt("Hey John"), "Hey John,\n\n")

    def test_sign_off_forms(self):
        cases = {
            "Can you send the invoice? Thanks.":
                "Can you send the invoice?\n\nThanks",
            "I am writing to complain. Yours faithfully, Ryan Murphy.":
                "I am writing to complain.\n\nYours faithfully,\nRyan Murphy",
            "Please find attached. Many thanks, Ryan":
                "Please find attached.\n\nMany thanks,\nRyan",
            "Quick one. Cheers!": "Quick one.\n\nCheers!",
            "See below. Speak soon.": "See below.\n\nSpeak soon",
            "Kind regards, Ryan.": "Kind regards,\nRyan",
        }
        for src, want in cases.items():
            with self.subTest(src=src):
                self.assertEqual(fmt(src, ME), want)

    def test_sign_off_after_a_comma_closes_the_sentence(self):
        self.assertEqual(
            fmt("Hi John, hope you're well, kind regards, Ryan."),
            "Hi John,\n\nHope you're well.\n\nKind regards,\nRyan")
        self.assertEqual(fmt("Let me know, thanks, Ryan.", ME),
                         "Let me know.\n\nThanks,\nRyan")

    def test_existing_paragraphs_are_kept(self):
        self.assertEqual(
            fmt("Hi John,\n\nThanks for this.\n\nSecond point.\n\nKind regards, Ryan"),
            "Hi John,\n\nThanks for this.\n\nSecond point.\n\nKind regards,\nRyan")

    def test_greeting_straight_into_sign_off(self):
        self.assertEqual(fmt("Hi John, kind regards, Ryan"),
                         "Hi John,\n\nKind regards,\nRyan")

    def test_sign_off_run_straight_on_from_the_body(self):
        # Reported 2026-09-22 (BrightLink inbox): no pause before "kind
        # regards", so the engine wrote no punctuation for the lead to find.
        self.assertEqual(
            fmt("Hi John, thanks for getting back to me so soon and I just "
                "wanted to say thank you kind regards Ryan", ME),
            "Hi John,\n\nThanks for getting back to me so soon and I just "
            "wanted to say thank you.\n\nKind regards,\nRyan")
        self.assertEqual(fmt("we'll sort it next week kind regards Ryan", ME),
                         "We'll sort it next week.\n\nKind regards,\nRyan")
        self.assertEqual(fmt("thanks for this yours sincerely Ryan Murphy", ME),
                         "Thanks for this.\n\nYours sincerely,\nRyan Murphy")

    def test_any_close_run_on_before_the_senders_own_name(self):
        # Nobody thanks themselves, so "cheers Ryan" from Ryan is a signature.
        self.assertEqual(fmt("see you then cheers Ryan", ME),
                         "See you then.\n\nCheers,\nRyan")


class LeftAloneTests(unittest.TestCase):
    """Byte-identical: the worse regression is rewriting text that was fine."""

    def test_no_greeting_and_no_sign_off(self):
        for src in ("Can you send the updated quote over by Friday?",
                    "Morning meeting moved to three.",
                    "Hello world this is a test.",
                    "Hi-res photos are attached.",
                    "Hey Monday works for me.",
                    "That was the best",
                    "This is a normal sentence about the best."):
            with self.subTest(src=src):
                self.assertEqual(fmt(src, ME), src)

    def test_lower_case_names_are_not_guessed(self):
        self.assertEqual(fmt("hi john thanks for your email"),
                         "hi john thanks for your email")

    def test_a_whole_reply_of_thanks_stays(self):
        self.assertEqual(fmt("Thanks.", ME), "Thanks.")
        self.assertEqual(fmt("Thank you!", ME), "Thank you!")

    def test_thanks_inside_the_last_sentence_is_not_a_sign_off(self):
        self.assertEqual(fmt("Let me know, thanks.", ME), "Let me know, thanks.")
        self.assertEqual(fmt("Thanks for your help today.", ME),
                         "Thanks for your help today.")

    def test_thanking_the_recipient_by_name_is_not_a_signature(self):
        # Sender known: John is not Ryan, so John is being thanked.
        self.assertEqual(
            fmt("Hi John, can you send it over? Thanks John.", ME),
            "Hi John,\n\nCan you send it over? Thanks John.")
        # Sender unknown: John is the greeting's addressee.
        self.assertEqual(
            fmt("Hi John, can you send it over? Thanks John."),
            "Hi John,\n\nCan you send it over? Thanks John.")
        self.assertEqual(fmt("Thanks John."), "Thanks John.")

    def test_run_on_sign_off_that_is_part_of_the_sentence(self):
        for src in ("please give him my kind regards",
                    "I wish you all the best",
                    "I mean it sincerely",
                    "I just wanted to say thanks Ryan",
                    "sent with kind regards Ryan",
                    "sign it off kind regards Ryan",
                    "end the email with kind regards Ryan",
                    "Can you send it over thanks John"):
            with self.subTest(src=src):
                self.assertEqual(fmt(src, ME), src)
        # Unknown sender: a run-on "cheers John" could be either, so it stays.
        self.assertEqual(fmt("see you then cheers John"),
                         "see you then cheers John")

    def test_best_needs_a_name(self):
        self.assertEqual(fmt("That's the best."), "That's the best.")

    def test_empty(self):
        self.assertEqual(fmt(""), "")
        self.assertEqual(fmt("   "), "   ")

    def test_already_laid_out_is_stable(self):
        once = fmt("Hi John, thanks. Kind regards, Ryan.", ME)
        self.assertEqual(fmt(once, ME), once)


class AnyAppSignOffTests(unittest.TestCase):
    """Asked for 2026-09-22: "kind regards ... Ryan" goes on its own lines
    wherever it is dictated, because nobody says it except to close a
    message. Only that close moves; the greeting and body stay as spoken."""

    def test_regards_close_with_a_name_moves(self):
        self.assertEqual(
            format_signoff("Hi John, thanks for getting back to me and I just "
                           "wanted to say thank you kind regards Ryan", ME),
            "Hi John, thanks for getting back to me and I just wanted to say "
            "thank you.\n\nKind regards,\nRyan")
        self.assertEqual(format_signoff("Thanks. Best regards, Ryan.", ME),
                         "Thanks.\n\nBest regards,\nRyan")
        self.assertEqual(format_signoff("Kind regards Ryan", ME),
                         "Kind regards,\nRyan")

    def test_everything_else_is_byte_identical(self):
        for src in ("Hi John, thanks for your email.",
                    "Can you send it over? Thanks, John.",
                    "see you then cheers Ryan",
                    "Speak soon, Ryan",
                    "That's great. Kind regards.",
                    "please give him my kind regards",
                    "sign it off kind regards Ryan",
                    "I wish you all the best, John",
                    "Please pass on my best wishes, John."):
            with self.subTest(src=src):
                self.assertEqual(format_signoff(src, ME), src)

    def test_stable(self):
        once = format_signoff("thanks for this kind regards Ryan", ME)
        self.assertEqual(format_signoff(once, ME), once)


class WordsKeptTests(unittest.TestCase):
    """Only line breaks, the punctuation beside them and one capital move."""

    SAMPLES = (
        "Hi John, thanks for your email. I'll look. Kind regards, Ryan.",
        "Dear Sir or Madam, I am writing to complain. Yours faithfully, Ryan.",
        "Morning all, quick update on the job. Cheers, Ryan.",
        "Hi John, hope you're well, kind regards, Ryan.",
        "Let me know, thanks, Ryan.",
        "Hi John.",
        "Hi John, I just wanted to say thank you kind regards Ryan",
    )

    def test_same_words_in_the_same_order(self):
        for src in self.SAMPLES:
            with self.subTest(src=src):
                out = fmt(src, ME)
                self.assertEqual(re.findall(r"[a-z']+", src.lower()),
                                 re.findall(r"[a-z']+", out.lower()))
                self.assertEqual(
                    re.findall(r"[a-z']+", src.lower()),
                    re.findall(r"[a-z']+", format_signoff(src, ME).lower()))


class EmailAppTests(unittest.TestCase):
    def test_desktop_clients(self):
        for exe in (r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
                    r"C:\Program Files\WindowsApps\Microsoft.OutlookForWindows\olk.exe",
                    r"C:\Program Files\Mozilla Thunderbird\thunderbird.exe"):
            with self.subTest(exe=exe):
                self.assertTrue(is_email_app(exe, ""))

    def test_webmail_tabs(self):
        edge = "Microsoft" + chr(0x200b) + " Edge"
        for exe, title in (
                ("chrome.exe", "Inbox (3) - ryan@gmail.com - Gmail - Google Chrome"),
                ("chrome.exe", "Inbox (3) - ryan@gmail.com - Gmail"),  # web app
                ("msedge.exe", "Inbox - x@gmail.com - Gmail and 3 more pages"
                               " - Personal - " + edge),
                ("msedge.exe", "Mail - Ryan Murphy - Outlook - Work - " + edge),
                ("firefox.exe", "Re: Quote - ryan@x.com - Gmail \u2014 Mozilla Firefox")):
            with self.subTest(title=title):
                self.assertTrue(is_email_app("C:\\x\\" + exe, title))

    def test_brightlink_inbox_and_send_email_modal(self):
        # The CRM names its tab "<page> | <brand>"; the brand half is the
        # customer's profile name, so only the page half is matched.
        edge = "Microsoft" + chr(0x200b) + " Edge"
        for exe, title in (
                ("chrome.exe", "Inbox | BrightLink - Google Chrome"),
                ("chrome.exe", "New email | BrightLink - Google Chrome"),
                ("chrome.exe", "Inbox | FTC Safety Solutions - Google Chrome"),
                ("chrome.exe", "Inbox | BrightLink"),          # app window
                ("msedge.exe", "Inbox | BrightLink - Personal - " + edge)):
            with self.subTest(title=title):
                self.assertTrue(is_email_app("C:\\x\\" + exe, title))
        for exe, title in (
                ("chrome.exe", "Home | BrightLink - Google Chrome"),
                ("chrome.exe", "CRM | BrightLink - Google Chrome"),
                ("chrome.exe", "Inbox | BrightLink - Google Search - Google Chrome"),
                ("chrome.exe", "Inbox | x | y - Google Chrome"),
                ("chrome.exe", "Inbox - Google Chrome"),
                ("slack.exe", "Inbox | BrightLink")):
            with self.subTest(title=title):
                self.assertFalse(is_email_app("C:\\x\\" + exe, title))

    def test_search_and_help_pages_about_email_are_not_email(self):
        # Asked for explicitly: Google Search must never get the layout, even
        # when the query itself looks like a Gmail title.
        edge = "Microsoft" + chr(0x200b) + " Edge"
        for exe, title in (
                ("chrome.exe", "Gmail - Google Search - Google Chrome"),
                ("chrome.exe", "hi john - Google Search - Google Chrome"),
                ("chrome.exe", "Google - Google Chrome"),
                ("chrome.exe", "sign in - Gmail - Google Search - Google Chrome"),
                ("chrome.exe", "inbox - Outlook - Google Search - Google Chrome"),
                ("msedge.exe", "sign in - Gmail - Search and 3 more pages"
                               " - Personal - " + edge),
                ("msedge.exe", "inbox - Outlook - Search - " + edge),
                ("firefox.exe", "inbox - Gmail at DuckDuckGo - Mozilla Firefox"),
                ("chrome.exe", "x - Gmail - Yahoo Search Results - Google Chrome"),
                ("chrome.exe", "Create filters - Gmail Help - Google Chrome"),
                ("chrome.exe", "Gmail - Google Chrome"),       # no inbox before it
                ("chrome.exe", "Outlook - Wikipedia - Google Chrome"),
                ("chrome.exe", "Google Docs - Google Chrome"),
                ("chrome.exe", "Echo Request - Google Chrome")):
            with self.subTest(title=title):
                self.assertFalse(is_email_app("C:\\x\\" + exe, title))

    def test_everything_else(self):
        for exe, title in (
                ("chrome.exe", "How to fix Outlook - Google Search - Google Chrome"),
                ("chrome.exe", "gmail - Google Search - Google Chrome"),
                ("chrome.exe", "Claude - Google Chrome"),
                ("winword.exe", "Notes - Outlook - Word"),
                ("slack.exe", "Gmail - Slack"),
                ("ms-teams.exe", "Chat | Microsoft Teams"),
                ("", "")):
            with self.subTest(exe=exe, title=title):
                self.assertFalse(is_email_app("C:\\x\\" + exe if exe else "",
                                              title))


class WiringTests(unittest.TestCase):
    """Once, on the whole utterance, at app.py's post-processing point; only
    for a dictation that started in an email client; never under Live Typing;
    before the user libraries so a snippet body is never re-shaped."""

    def _src(self, name):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), name)
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_applied_in_app_not_in_an_engine(self):
        self.assertIn("format_email(transcribed_text", self._src("app.py"))
        for engine in ("asr_engine.py", "transcriber.py", "stream_session.py"):
            self.assertNotIn("email_format", self._src(engine))

    def test_gated_on_setting_email_client_and_live_typing(self):
        app = self._src("app.py")
        gate = app[app.index("def _email_layout_on"):]
        gate = gate[:gate.index("def _load_sender_name")]
        for need in ('"email_format", True', '"live_inject", False',
                     "self._recording_email"):
            self.assertIn(need, gate)
        use = app[app.index("_email_ctx = self._email_layout_on()"):]
        self.assertLess(use.index("_email_ctx"),
                        use.index("format_email(transcribed_text"))

    def test_email_client_is_read_at_record_start(self):
        # The browser title follows the active tab; read it with the app
        # identity on the hotkey thread, not at release.
        app = self._src("app.py")
        state = app[app.index("def _on_state_change"):]
        self.assertIn("self._recording_email = self._is_email_window(", state)

    def test_order_lists_then_email_then_user_libraries(self):
        app = self._src("app.py")
        self.assertLess(app.index("format_lists(transcribed_text)"),
                        app.index("format_email(transcribed_text"))
        self.assertLess(app.index("format_email(transcribed_text"),
                        app.index("self._apply_user_libraries(transcribed_text,"))

    def test_whisper_upgrade_gets_the_same_layout(self):
        app = self._src("app.py")
        self.assertIn("accurate = format_email(accurate", app)
        self.assertIn("accurate = format_signoff(accurate", app)

    def test_any_app_sign_off_only_where_the_email_layout_is_not(self):
        app = self._src("app.py")
        self.assertIn(
            "_signoff_ctx = not _email_ctx and self._signoff_layout_on()", app)
        gate = app[app.index("def _signoff_layout_on"):]
        gate = gate[:gate.index("def _load_sender_name")]
        for need in ('"email_format", True', '"live_inject", False'):
            self.assertIn(need, gate)
        self.assertLess(app.index("format_signoff(transcribed_text"),
                        app.index("self._apply_user_libraries(transcribed_text,"))

    def test_default_on_and_in_settings(self):
        self.assertIn("email_format: bool = True", self._src("config.py"))
        self.assertIn('_toggle_card("email_format"', self._src("app_window.py"))


class RefinerInteractionTests(unittest.TestCase):
    """context_fix runs in the background and its result is offered unasked.
    A pass that joined the sign-off back onto the body keeps every word, so
    only a structural guard catches it."""

    def _refiner(self, returns):
        import ai_refiner
        r = ai_refiner.AIRefiner.__new__(ai_refiner.AIRefiner)
        r.refine = lambda text, mode=None: returns
        return r

    def test_context_fix_refuses_a_result_that_moved_a_line_break(self):
        laid = "Hi John,\n\nThanks for your email, I'll look.\n\nKind regards,\nRyan"
        flat = "Hi John, thanks for your email, I'll look. Kind regards, Ryan"
        self.assertEqual(self._refiner(flat).context_fix(laid), laid)

    def test_a_real_correction_with_the_same_lines_is_kept(self):
        laid = "Hi John,\n\nThanks for the male, I'll look.\n\nKind regards,\nRyan"
        fixed = "Hi John,\n\nThanks for the mail, I'll look.\n\nKind regards,\nRyan"
        self.assertEqual(self._refiner(fixed).context_fix(laid), fixed)

    def test_crlf_counts_the_same_as_lf(self):
        import ai_refiner
        self.assertEqual(ai_refiner._line_count("a\r\n\r\nb"),
                         ai_refiner._line_count("a\n\nb"))


class CorpusRegressionTests(unittest.TestCase):
    """Every real stored transcript, as if it had been dictated into an email.
    Whatever changes must keep every word in order."""

    def _load(self):
        path = os.path.join(os.environ.get("APPDATA", ""), "FTC Whisper",
                            "history.json")
        if not os.path.exists(path):
            self.skipTest("no local history.json corpus on this machine")
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        return [t for t in (r.get("transcribed_text", "") for r in rows)
                if t and t.strip()]

    def test_no_word_is_lost_added_or_moved(self):
        for text in self._load():
            for out in (fmt(text, ME), format_signoff(text, ME)):
                if out == text:
                    continue
                self.assertEqual(re.findall(r"[a-z']+", text.lower()),
                                 re.findall(r"[a-z']+", out.lower()),
                                 f"words changed: {text[:80]!r}")

    def test_any_app_rule_only_moves_a_named_close(self):
        # The any-app rule runs on every dictation in every app, so over the
        # real corpus it may only ever produce "...<blank line><close>,<Name>".
        for text in self._load():
            out = format_signoff(text, ME)
            if out != text:
                self.assertRegex(out, r"\n\n[A-Z][a-z ]+,\n[A-Z][\w' -]*$")

    def test_only_greeting_or_sign_off_shapes_change(self):
        offenders = []
        for text in self._load():
            out = fmt(text, ME)
            if out == text:
                continue
            if (email_format._split_greeting(text)
                    or email_format._SIGNOFF_RE.search(text)):
                continue
            offenders.append(text[:120])
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
