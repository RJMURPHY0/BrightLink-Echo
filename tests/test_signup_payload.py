"""Create Account: the metadata it sends, and the form that collects it.

Echo used to sign up with email and password alone. One Supabase project sits
behind Echo, the CRM and Transcribe, and its shared `handle_new_user` trigger
reads `company_name` to name the person's organisation and to set
`is_personal` — which is how Super Admin decides whether to list them under a
company or under Users. Sending neither key filed every Echo signup as a
company-less workspace named after the email prefix, with no display name.

These tests pin both halves: the payload auth.py builds, and the form fields
login_window collects it from. They also pin that Google sign-in is only
HIDDEN — every line that implements it is still in the file, so restoring it
is one flag.
"""

import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import login_window as LW  # noqa: E402
from auth import AuthManager  # noqa: E402


class _FakeAuthClient:
    """Captures the dict handed to supabase's auth.sign_up."""

    def __init__(self):
        self.payload = None
        self.auth = self

    def sign_up(self, payload):
        self.payload = payload
        raise RuntimeError("stop here — the payload is all this test wants")


def _payload_for(**kwargs):
    mgr = AuthManager.__new__(AuthManager)
    client = _FakeAuthClient()
    mgr._get_client = lambda: client
    mgr.sign_up("a@b.com", "hunter2", **kwargs)
    return client.payload


class SignUpPayloadTests(unittest.TestCase):

    def test_a_named_company_is_forwarded(self):
        p = _payload_for(full_name="Ryan Murphy", company_name="Acme Ltd")
        self.assertEqual({"full_name": "Ryan Murphy",
                          "company_name": "Acme Ltd"},
                         p["options"]["data"])

    def test_a_blank_company_is_absent_not_empty(self):
        # The trigger tests `nullif(trim(...), '') IS NULL` to decide
        # is_personal. An empty string is still a value to anything reading
        # the metadata directly, so the key must not be there at all.
        p = _payload_for(full_name="Ryan Murphy", company_name="   ")
        self.assertEqual({"full_name": "Ryan Murphy"}, p["options"]["data"])
        self.assertNotIn("company_name", p["options"]["data"])

    def test_no_metadata_at_all_sends_no_options_key(self):
        p = _payload_for()
        self.assertNotIn("options", p)
        self.assertEqual({"email": "a@b.com", "password": "hunter2"}, p)

    def test_values_are_trimmed(self):
        p = _payload_for(full_name="  Ryan  ", company_name="  Acme  ")
        self.assertEqual({"full_name": "Ryan", "company_name": "Acme"},
                         p["options"]["data"])

    def test_email_and_password_still_travel_at_the_top_level(self):
        p = _payload_for(full_name="Ryan")
        self.assertEqual("a@b.com", p["email"])
        self.assertEqual("hunter2", p["password"])


class GoogleSignInTests(unittest.TestCase):

    def test_the_flag_is_off(self):
        self.assertFalse(LW.GOOGLE_SIGN_IN)

    def test_packing_is_guarded_by_the_flag(self):
        src = inspect.getsource(LW.LoginWindow._build_ui)
        self.assertIn("if GOOGLE_SIGN_IN:", src)

    def test_every_line_that_implements_it_is_still_here(self):
        # "Remember how to get it back" — the restoration must be the flag and
        # nothing else, so none of this may be deleted as dead code.
        for name in ("_sign_in_google", "_exchange_oauth_code"):
            self.assertTrue(hasattr(LW.LoginWindow, name),
                            f"{name} was removed; restoring Google now needs "
                            f"a rewrite rather than a flag flip")
        src = inspect.getsource(LW)
        self.assertIn("Continue with Google", src)
        self.assertIn("provider", src)


class _FakeAuth:
    last_email = ""
    is_authenticated = False
    user_email = None


_SHARED_ROOT = None


def _shared_root():
    """One Tk root for the module.

    A root per test is what the first draft did, and creating/destroying them
    in quick succession fails intermittently on Windows — the suite's other Tk
    tests share a root for the same reason.
    """
    global _SHARED_ROOT
    import tkinter as tk
    if _SHARED_ROOT is not None and _SHARED_ROOT.winfo_exists():
        return _SHARED_ROOT
    try:
        _SHARED_ROOT = tk.Tk()
    except Exception as e:                           # no window station (CI)
        raise unittest.SkipTest(f"Tk unavailable: {e}")
    _SHARED_ROOT.geometry(f"{LW.WINDOW_W}x{LW.WINDOW_H}")
    return _SHARED_ROOT


def tearDownModule():
    global _SHARED_ROOT
    if _SHARED_ROOT is not None:
        try:
            _SHARED_ROOT.destroy()
        except Exception:
            pass
        _SHARED_ROOT = None


def _form():
    import tkinter as tk
    root = _shared_root()
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True)
    heights = []
    ui = LW.LoginWindow(_FakeAuth(), on_success=lambda *a: None)
    ui.embed(frame, on_height_change=heights.append)
    root.update_idletasks()
    return frame, ui, heights


class SignUpFormTests(unittest.TestCase):

    def setUp(self):
        self.frame, self.ui, self.heights = _form()
        self.root = self.frame.winfo_toplevel()

    def tearDown(self):
        # Destroy only this test's subtree; the root is shared.
        try:
            self.frame.destroy()
        except Exception:
            pass

    @staticmethod
    def _packed(widget):
        return bool(widget.winfo_manager())

    def test_name_and_company_show_only_on_create_account(self):
        self.ui._switch("login")
        self.root.update_idletasks()
        self.assertFalse(self._packed(self.ui._name_section))
        self.assertFalse(self._packed(self.ui._company_section))

        self.ui._switch("signup")
        self.root.update_idletasks()
        self.assertTrue(self._packed(self.ui._name_section))
        self.assertTrue(self._packed(self.ui._company_section))

    def test_google_button_is_not_on_screen(self):
        self.assertFalse(self._packed(self.ui._google_btn))
        self.assertFalse(self._packed(self.ui._divider_frame))

    def test_the_forgot_link_still_packs_with_no_divider_to_sit_above(self):
        # pack(before=w) raises when w is unpacked, and the divider is
        # unpacked while Google is off. _link_anchor is what keeps this legal.
        self.ui._switch("login")
        self.root.update_idletasks()
        self.assertTrue(self._packed(self.ui._forgot_link))

    def test_each_mode_asks_for_a_height_that_fits_its_own_card(self):
        # The form must fit on THIS machine's screen. If it does not, the
        # monitor clamp silently truncates it and the Create Account button
        # goes off the bottom — which is exactly what the first draft of this
        # layout did on Ryan's laptop display (needed 725px, had 704px).
        cap = self.ui._max_height()
        for mode in ("login", "signup"):
            self.ui._switch(mode)
            self.root.update_idletasks()
            need = self.ui.required_height()
            wanted = self.ui.content_height()
            self.assertLessEqual(
                wanted, cap,
                f"{mode} does not fit this screen: wants {wanted}px, the "
                f"monitor allows {cap}px — the form will be clipped")
            self.assertGreaterEqual(
                need, wanted,
                f"{mode} would clip: window {need}px for {wanted}px of form")

    def test_the_card_is_sized_to_the_form_not_the_window(self):
        # The card used to stretch to fill the window, leaving an empty band
        # under "Forgot password?" once the page was taller than the form.
        for mode in ("login", "signup"):
            self.ui._switch(mode)
            self.root.update_idletasks()
            card_h = int(float(self.ui._card_cv.cget("height")))
            self.assertEqual(
                card_h,
                self.ui._holder.winfo_reqheight() + 2 * LW.LoginWindow._CARD_PAD,
                f"{mode}: card is not sized to its form")

    def test_sign_in_holds_the_hosts_height_and_signup_does_not_jump(self):
        # Embedded, the page keeps the dashboard's height (2026-09-25: at its
        # own 460px floor it read as a squashed window). Create Account fits
        # the same height, so switching modes never resizes the window.
        frame = __import__("tkinter").Frame(self.root)
        heights = []
        ui = LW.LoginWindow(_FakeAuth(), on_success=lambda *a: None)
        ui.embed(frame, on_height_change=heights.append, base_height=lambda: 670)
        try:
            self.root.update_idletasks()
            ui._switch("login")
            login_h = ui.required_height()
            ui._switch("signup")
            signup_h = ui.required_height()
            self.assertEqual(login_h, min(670, ui._max_height()))
            if ui._max_height() >= 670:
                self.assertEqual(signup_h, 670,
                                 "Create Account no longer fits the dashboard height")
        finally:
            frame.destroy()

    def test_a_status_message_grows_the_page_rather_than_clipping(self):
        self.ui._switch("signup")
        self.root.update_idletasks()
        before = self.ui.content_height()
        self.ui._set_status("Passwords do not match.", error=True)
        self.root.update_idletasks()
        self.assertGreater(self.ui.content_height(), before)
        self.assertGreaterEqual(self.ui.required_height(),
                                min(self.ui.content_height(), self.ui._max_height()))


if __name__ == "__main__":
    unittest.main()
