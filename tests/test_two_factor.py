"""Two-factor sign-in (2026-11-03).

The web app refuses an aal1 session from anyone with a verified second step,
so Echo must ask for the code after the password and keep the aal2 session it
earns. These tests pin, with a fake Supabase client and a fake web-app route:

* a password sign-in that owes the code is NOT signed in, hands its token to
  nobody, and saves the session so a restart comes back to the code page;
* each method finishes with Supabase's own challenge + verify, using the code
  typed (authenticator) or the TOTP the web app hands back (email, WhatsApp,
  text, backup), then refreshes so the database calls carry the aal2 token;
* a restored aal2 session opens straight away, a restored aal1 one asks again;
* "Use a different account" puts back whoever was signed in before;
* the code page in login_window swaps in for the form and calls the right
  AuthManager methods.

Runs against a throwaway folder: no test may touch the real .session or
auth-restore.log (see test_session_restore.py for why).
"""
import base64
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth  # noqa: E402
import mfa  # noqa: E402
from auth import AuthManager  # noqa: E402

_REAL_RESTORE_LOG_PATH = auth._restore_log_path
_REAL_SESSION_PATH = auth._session_path
_REAL_LAST_EMAIL_PATH = auth._last_email_path
_SANDBOX = None


def setUpModule():
    global _SANDBOX
    _SANDBOX = tempfile.mkdtemp(prefix="echo_two_factor_tests_")
    auth._restore_log_path = lambda: os.path.join(_SANDBOX, "auth-restore.log")
    auth._session_path = lambda: os.path.join(_SANDBOX, ".session")
    auth._last_email_path = lambda: os.path.join(_SANDBOX, "last-email.txt")


def tearDownModule():
    auth._restore_log_path = _REAL_RESTORE_LOG_PATH
    auth._session_path = _REAL_SESSION_PATH
    auth._last_email_path = _REAL_LAST_EMAIL_PATH
    shutil.rmtree(_SANDBOX, ignore_errors=True)


def _jwt(aal: str, amr=("password",)) -> str:
    def b64(d):
        raw = json.dumps(d).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    claims = {"aal": aal, "exp": 4102444800,
              "amr": [{"method": m} for m in amr]}
    return f"{b64({'alg': 'none'})}.{b64(claims)}.sig"


def _user(factors=()):
    return types.SimpleNamespace(
        id="11111111-2222", email="person@example.com",
        factors=[types.SimpleNamespace(id=f["id"], status=f.get("status", "verified"),
                                       friendly_name=f.get("name"),
                                       factor_type="totp")
                 for f in factors])


def _session(aal, user, rt="rt-1"):
    return types.SimpleNamespace(access_token=_jwt(aal), refresh_token=rt,
                                 user=user)


APP = {"id": "f-app", "name": "Phone"}
EMAIL = {"id": "f-email", "name": "bl-email"}
BACKUP = {"id": "f-backup", "name": "bl-backup"}


class _FakeMfa:
    def __init__(self, owner):
        self.owner = owner
        self.challenges = []
        self.verified = []

    def challenge(self, params):
        self.challenges.append(params["factor_id"])
        return types.SimpleNamespace(id=f"ch-{len(self.challenges)}")

    def verify(self, params):
        if params["code"] != self.owner.good_code:
            raise RuntimeError("Invalid TOTP code entered")
        self.verified.append((params["factor_id"], params["code"]))
        self.owner.current = _session("aal2", self.owner.user, rt="rt-aal2")


class _FakeAuth:
    """The bits of supabase-py's auth client AuthManager uses."""

    def __init__(self, user, password_aal="aal1"):
        self.user = user
        self.password_aal = password_aal
        self.current = None
        self.good_code = "123456"
        self.mfa = _FakeMfa(self)
        self.refreshes = 0
        self.listeners = []

    def on_auth_state_change(self, fn):
        self.listeners.append(fn)

    def sign_in_with_password(self, creds):
        self.current = _session(self.password_aal, self.user)
        return types.SimpleNamespace(user=self.user, session=self.current)

    def set_session(self, at, rt):
        self.current = types.SimpleNamespace(access_token=at, refresh_token=rt,
                                             user=self.user)
        return types.SimpleNamespace(user=self.user, session=self.current)

    def get_session(self):
        return self.current

    def refresh_session(self):
        self.refreshes += 1
        # A refresh keeps the session's assurance level.
        aal = mfa.token_aal(self.current.access_token)
        self.current = _session(aal, self.user, rt=f"rt-r{self.refreshes}")
        return types.SimpleNamespace(user=self.user, session=self.current)

    def sign_out(self, opts):
        self.current = None


def _manager(user, password_aal="aal1"):
    mgr = AuthManager("https://example.supabase.co", "anon")
    fake = _FakeAuth(user, password_aal)
    client = types.SimpleNamespace(auth=fake)
    mgr._client = client
    mgr._get_client = lambda: client
    return mgr, fake


def _saved_tokens():
    with open(auth._session_path(), "rb") as f:
        return json.loads(auth._dpapi_decrypt(f.read()).decode())


class TokenRulesTests(unittest.TestCase):

    def test_aal_is_read_from_the_token(self):
        self.assertEqual("aal2", mfa.token_aal(_jwt("aal2")))
        self.assertEqual("aal1", mfa.token_aal(_jwt("aal1")))
        self.assertEqual("aal1", mfa.token_aal("not-a-jwt"))

    def test_only_a_verified_factor_owes_the_step(self):
        self.assertFalse(mfa.owes_second_step(_user(), _jwt("aal1")))
        self.assertFalse(mfa.owes_second_step(
            _user([{"id": "x", "status": "unverified"}]), _jwt("aal1")))
        self.assertTrue(mfa.owes_second_step(_user([APP]), _jwt("aal1")))
        self.assertFalse(mfa.owes_second_step(_user([APP]), _jwt("aal2")))

    def test_kinds_match_the_web_app_names(self):
        self.assertEqual("email", mfa.kind_of("bl-email"))
        self.assertEqual("whatsapp", mfa.kind_of("bl-whatsapp"))
        self.assertEqual("sms", mfa.kind_of("bl-sms"))
        self.assertEqual("backup", mfa.kind_of("bl-backup"))
        self.assertEqual("browser", mfa.kind_of("bl-browser:Chrome on Windows|k"))
        self.assertEqual("app", mfa.kind_of("My phone"))
        self.assertEqual("app", mfa.kind_of(None))

    def test_browsers_are_never_offered_and_email_only_after_a_password(self):
        listed = [{"factorId": "b", "kind": "backup"},
                  {"factorId": "e", "kind": "email"},
                  {"factorId": "t", "kind": "browser"},
                  {"factorId": "a", "kind": "app"},
                  {"factorId": "w", "kind": "whatsapp"}]
        self.assertEqual(["a", "w", "e", "b"],
                         [m["factorId"] for m in mfa.usable_methods(listed, True)])
        self.assertEqual(["a", "w", "b"],
                         [m["factorId"] for m in mfa.usable_methods(listed, False)])

    def test_code_box_keeps_only_what_a_code_can_hold(self):
        self.assertEqual("123456", mfa.clean_code("app", " 123 456 789"))
        self.assertEqual("ABCD-EFGH", mfa.clean_code("backup", "abcd-efgh!x"))
        self.assertTrue(mfa.code_ready("app", "123456"))
        self.assertFalse(mfa.code_ready("app", "12345"))
        self.assertTrue(mfa.code_ready("backup", "ABCD-EFGH"))
        self.assertTrue(mfa.code_ready("backup", "ABCDEFGH"))
        self.assertFalse(mfa.code_ready("backup", "ABCD-EFG"))


class PasswordStepTests(unittest.TestCase):

    def setUp(self):
        for name in (".session", "last-email.txt"):
            try:
                os.remove(os.path.join(_SANDBOX, name))
            except FileNotFoundError:
                pass

    def test_no_factor_signs_in_as_before(self):
        mgr, _ = _manager(_user())
        ok, _msg = mgr.sign_in("person@example.com", "pw")
        self.assertTrue(ok)
        self.assertTrue(mgr.is_authenticated)
        self.assertFalse(mgr.needs_second_step)

    def test_a_factor_owes_the_code_and_is_not_signed_in(self):
        mgr, fake = _manager(_user([APP]))
        ok, _msg = mgr.sign_in("person@example.com", "pw")
        self.assertTrue(ok)
        self.assertTrue(mgr.needs_second_step)
        self.assertFalse(mgr.is_authenticated)
        self.assertEqual("person@example.com", mgr.pending_email)
        # The aal1 token goes to nobody (AI relay, voice training, reports).
        self.assertEqual("", mgr.access_token)
        # Saved, so closing the app on the code page comes back to it.
        self.assertEqual("aal1", mfa.token_aal(_saved_tokens()["access_token"]))

    def test_an_offline_stand_in_does_not_count_as_signed_in(self):
        # After a sign-out the app runs as an offline stand-in user, which
        # is_authenticated reads as signed in. A password that owes its code
        # must never ride on that.
        mgr, _ = _manager(_user([APP]))
        mgr.sign_in_offline()
        mgr.sign_in("person@example.com", "pw")
        self.assertFalse(mgr.is_authenticated)
        mgr.cancel_second_step()
        self.assertTrue(mgr.is_authenticated)
        self.assertEqual("local", mgr.user_id)
        self.assertFalse(mgr.needs_second_step)
        self.assertFalse(os.path.exists(auth._session_path()))


class VerifyTests(unittest.TestCase):

    def _pending(self, factors):
        mgr, fake = _manager(_user(factors))
        mgr.sign_in("person@example.com", "pw")
        self.assertTrue(mgr.needs_second_step)
        return mgr, fake

    def test_authenticator_code_goes_straight_to_supabase(self):
        mgr, fake = self._pending([APP])
        with mock.patch.object(mfa, "call") as call:
            ok, msg = mgr.verify_second_step(
                {"factorId": "f-app", "kind": "app"}, "123456")
        self.assertTrue(ok, msg)
        call.assert_not_called()
        self.assertEqual([("f-app", "123456")], fake.mfa.verified)
        self.assertTrue(mgr.is_authenticated)
        self.assertFalse(mgr.needs_second_step)
        # Refreshed after verify: supabase-py resets the database header on
        # MFA_CHALLENGE_VERIFIED, TOKEN_REFRESHED puts the aal2 token back.
        self.assertEqual(1, fake.refreshes)
        self.assertEqual("aal2", mfa.token_aal(mgr.access_token))
        self.assertEqual("aal2", mfa.token_aal(_saved_tokens()["access_token"]))

    def test_a_wrong_authenticator_code_keeps_the_step_open(self):
        mgr, fake = self._pending([APP])
        ok, msg = mgr.verify_second_step(
            {"factorId": "f-app", "kind": "app"}, "000000")
        self.assertFalse(ok)
        self.assertEqual(mfa.NOT_ACCEPTED, msg)
        self.assertTrue(mgr.needs_second_step)
        self.assertFalse(mgr.is_authenticated)

    def test_email_code_is_checked_by_the_web_app_then_supabase(self):
        mgr, fake = self._pending([EMAIL])
        calls = []

        def fake_call(action, token, body=None):
            calls.append((action, mfa.token_aal(token), body))
            return {"totp": "123456"}

        with mock.patch.object(mfa, "call", side_effect=fake_call):
            ok, msg = mgr.verify_second_step(
                {"factorId": "f-email", "kind": "email"}, "987654")
        self.assertTrue(ok, msg)
        # The web app gets the aal1 token and the typed code; Supabase gets
        # the TOTP it handed back.
        self.assertEqual([("verify", "aal1",
                           {"factorId": "f-email", "code": "987654"})], calls)
        self.assertEqual([("f-email", "123456")], fake.mfa.verified)
        self.assertTrue(mgr.is_authenticated)

    def test_backup_code_finishes_on_the_factor_the_web_app_names(self):
        mgr, fake = self._pending([APP, BACKUP])
        with mock.patch.object(mfa, "call", return_value={
                "factorId": "f-backup", "totp": "123456", "remaining": 2}) as call:
            ok, msg = mgr.verify_second_step(
                {"factorId": "f-backup", "kind": "backup"}, "ABCD-EFGH")
        self.assertTrue(ok)
        self.assertEqual("backup-use", call.call_args[0][0])
        self.assertEqual({"code": "ABCD-EFGH"}, call.call_args[0][2])
        self.assertEqual([("f-backup", "123456")], fake.mfa.verified)
        self.assertIn("2 backup codes left", msg)

    def test_a_web_app_refusal_is_shown_as_it_is(self):
        mgr, fake = self._pending([EMAIL])
        with mock.patch.object(mfa, "call", side_effect=mfa.MfaError(
                "That code is not right. Check it and try again.")):
            ok, msg = mgr.verify_second_step(
                {"factorId": "f-email", "kind": "email"}, "111111")
        self.assertFalse(ok)
        self.assertEqual("That code is not right. Check it and try again.", msg)
        self.assertEqual([], fake.mfa.verified)
        self.assertTrue(mgr.needs_second_step)

    def test_send_goes_to_the_web_app_with_the_factor(self):
        mgr, _ = self._pending([EMAIL])
        with mock.patch.object(mfa, "call", return_value={"sent": True}) as call:
            self.assertEqual((True, ""), mgr.send_second_step_code("f-email"))
        self.assertEqual(("send", {"factorId": "f-email"}),
                         (call.call_args[0][0], call.call_args[0][2]))


class ApprovalTests(unittest.TestCase):
    """Approve in the web app: verify once for every app (2026-11-03)."""

    CLAIM = "c" * 48

    def _pending(self, factors=(APP, BACKUP)):
        mgr, fake = _manager(_user(factors))
        mgr.sign_in("person@example.com", "pw")
        return mgr, fake

    def test_request_names_this_pc_and_returns_the_number(self):
        mgr, _ = self._pending()
        with mock.patch.dict(os.environ, {"COMPUTERNAME": "RYAN-LAPTOP"}), \
                mock.patch.object(mfa, "call", return_value={
                    "requestId": "r1", "claim": self.CLAIM, "number": 47,
                    "expiresInSeconds": 120}) as call:
            req = mgr.request_approval()
        action, token, body = call.call_args[0]
        self.assertEqual("approval-request", action)
        self.assertEqual("aal1", mfa.token_aal(token))
        self.assertEqual({"app": "echo", "device": "Echo on RYAN-LAPTOP"}, body)
        self.assertEqual(47, req["number"])
        self.assertEqual(120, req["expiresInSeconds"])

    def test_approved_finishes_on_the_factor_the_web_app_names(self):
        mgr, fake = self._pending()
        req = {"requestId": "r1", "claim": self.CLAIM}
        with mock.patch.object(mfa, "call", return_value={
                "status": "approved", "factorId": "f-backup",
                "totp": "123456"}) as call:
            self.assertEqual(("approved", ""), mgr.check_approval(req))
        self.assertEqual(("approval-check", {"requestId": "r1",
                                             "claim": self.CLAIM}),
                         (call.call_args[0][0], call.call_args[0][2]))
        self.assertEqual([("f-backup", "123456")], fake.mfa.verified)
        self.assertTrue(mgr.is_authenticated)
        self.assertEqual(1, fake.refreshes)
        self.assertEqual("aal2", mfa.token_aal(_saved_tokens()["access_token"]))

    def test_other_states_leave_the_step_open(self):
        mgr, fake = self._pending()
        for state in ("pending", "denied", "expired", "none"):
            with mock.patch.object(mfa, "call", return_value={"status": state}):
                self.assertEqual((state, ""),
                                 mgr.check_approval({"requestId": "r", "claim": "c"}))
        self.assertEqual([], fake.mfa.verified)
        self.assertTrue(mgr.needs_second_step)

    def test_an_approved_code_that_supabase_refuses_reports_failed(self):
        mgr, _ = self._pending()
        with mock.patch.object(mfa, "call", return_value={
                "status": "approved", "factorId": "f-backup", "totp": "000000"}):
            status, msg = mgr.check_approval({"requestId": "r", "claim": "c"})
        self.assertEqual("failed", status)
        self.assertEqual(mfa.NOT_ACCEPTED, msg)
        self.assertTrue(mgr.needs_second_step)

    def test_the_claim_is_never_written_down(self):
        mgr, _ = self._pending()
        with mock.patch.object(mfa, "call", return_value={
                "requestId": "r1", "claim": self.CLAIM, "number": 47,
                "expiresInSeconds": 120}):
            mgr.request_approval()
        with mock.patch.object(mfa, "call", return_value={
                "status": "approved", "factorId": "f-backup", "totp": "123456"}):
            mgr.check_approval({"requestId": "r1", "claim": self.CLAIM})
        for name in os.listdir(_SANDBOX):
            with open(os.path.join(_SANDBOX, name), "rb") as f:
                raw = f.read()
            self.assertNotIn(self.CLAIM.encode(), raw, name)

    def test_server_refusal_codes_reach_the_caller(self):
        import io
        import urllib.error
        err = urllib.error.HTTPError(
            "https://x", 403, "Forbidden", {},
            io.BytesIO(b'{"error":"Approving is switched off.","code":"sharing_off"}'))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(mfa.MfaError) as cm:
                mfa.call("approval-request", _jwt("aal1"), {})
        self.assertEqual("sharing_off", cm.exception.code)
        self.assertEqual(403, cm.exception.status)
        self.assertEqual("Approving is switched off.", str(cm.exception))
        self.assertIn(cm.exception.code, mfa.APPROVAL_UNAVAILABLE)

    def test_which_refusals_hide_the_option(self):
        E = mfa.MfaError
        self.assertTrue(mfa.approval_unavailable(E("x", code="sharing_off", status=403)))
        self.assertTrue(mfa.approval_unavailable(E("x", code="no_server_factor", status=400)))
        # A web app without approvals yet answers "Unknown action".
        self.assertTrue(mfa.approval_unavailable(E("Unknown action", status=400)))
        self.assertFalse(mfa.approval_unavailable(E("x", code="rate_limited", status=429)))
        self.assertFalse(mfa.approval_unavailable(E(mfa.NO_CONNECTION)))
        self.assertFalse(mfa.approval_unavailable(E("boom", status=500)))

    def test_no_connection_has_no_status(self):
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("down")):
            with self.assertRaises(mfa.MfaError) as cm:
                mfa.call("approval-check", _jwt("aal1"), {})
        self.assertEqual(0, cm.exception.status)
        self.assertEqual(mfa.NO_CONNECTION, str(cm.exception))


class MethodsTests(unittest.TestCase):

    def test_methods_come_from_the_web_app_filtered_and_ordered(self):
        mgr, _ = _manager(_user([APP, EMAIL]))
        mgr.sign_in("person@example.com", "pw")
        listed = {"methods": [{"factorId": "f-email", "kind": "email"},
                              {"factorId": "f-b", "kind": "browser"},
                              {"factorId": "f-app", "kind": "app"}],
                  "emailMayFinish": True}
        with mock.patch.object(mfa, "call", return_value=listed):
            got = mgr.second_step_methods()
        self.assertEqual(["f-app", "f-email"],
                         [m["factorId"] for m in got["methods"]])

    def test_an_unreachable_web_app_still_offers_the_authenticator(self):
        mgr, _ = _manager(_user([APP, EMAIL]))
        mgr.sign_in("person@example.com", "pw")
        with mock.patch.object(mfa, "call",
                               side_effect=mfa.MfaError(mfa.NO_CONNECTION)):
            got = mgr.second_step_methods()
        self.assertEqual([("f-app", "app")],
                         [(m["factorId"], m["kind"]) for m in got["methods"]])

    def test_an_unreachable_web_app_with_no_authenticator_says_so(self):
        mgr, _ = _manager(_user([EMAIL]))
        mgr.sign_in("person@example.com", "pw")
        with mock.patch.object(mfa, "call",
                               side_effect=mfa.MfaError(mfa.NO_CONNECTION)):
            with self.assertRaises(mfa.MfaError) as cm:
                mgr.second_step_methods()
        self.assertEqual(mfa.NO_CONNECTION, str(cm.exception))

    def test_two_factor_removed_elsewhere_opens_the_app(self):
        mgr, fake = _manager(_user([APP]))
        mgr.sign_in("person@example.com", "pw")
        fake.user = _user()   # the factor was removed in the web app
        with mock.patch.object(mfa, "call",
                               return_value={"methods": [], "emailMayFinish": True}):
            got = mgr.second_step_methods()
        self.assertTrue(got["done"])
        self.assertTrue(mgr.is_authenticated)


class RestoreTests(unittest.TestCase):

    def _write_session(self, aal):
        mgr = AuthManager.__new__(AuthManager)
        mgr._save_session(types.SimpleNamespace(access_token=_jwt(aal),
                                                refresh_token="rt"))

    def test_a_saved_aal2_session_opens_without_a_code(self):
        self._write_session("aal2")
        mgr, _ = _manager(_user([APP]))
        self.assertTrue(mgr.try_restore_session(wait_seconds=5))
        self.assertTrue(mgr.is_authenticated)
        self.assertFalse(mgr.needs_second_step)
        self.assertTrue(mgr.access_token)

    def test_a_saved_aal1_session_goes_back_to_the_code(self):
        self._write_session("aal1")
        mgr, _ = _manager(_user([APP]))
        # True: there is a session, and the caller must look at
        # needs_second_step before opening anything.
        self.assertTrue(mgr.try_restore_session(wait_seconds=5))
        self.assertFalse(mgr.is_authenticated)
        self.assertTrue(mgr.needs_second_step)
        self.assertEqual("", mgr.access_token)
        self.assertTrue(mgr.has_saved_session())

    def test_a_refreshed_aal2_session_stays_aal2(self):
        mgr, fake = _manager(_user([APP]))
        mgr.sign_in("person@example.com", "pw")
        mgr.verify_second_step({"factorId": "f-app", "kind": "app"}, "123456")
        fake.refresh_session()
        self.assertEqual("aal2", mfa.token_aal(mgr.access_token))


class CodePageTests(unittest.TestCase):
    """The page itself, with work run inline instead of on a thread."""

    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        try:
            cls.root = tk.Tk()
        except tk.TclError as e:
            raise unittest.SkipTest(f"no display: {e}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def _page(self, auth_obj):
        import tkinter as tk
        import login_window as LW
        frame = tk.Frame(self.root)
        frame.pack()
        done = []
        lw = LW.LoginWindow(auth_obj, on_success=lambda a: done.append(a))
        lw.embed(frame)
        def inline(work, cb):
            # Same contract as the real one: an exception is the result.
            try:
                result = work()
            except Exception as e:
                result = e
            cb(result)
        lw._in_background = inline
        # Short timers (focus, the hand-over) run at once; the once-a-second
        # resend countdown is left alone.
        lw._root.after = lambda ms, fn=None, *a: (
            fn(*a) if fn and ms < 1000 else None)
        return lw, done

    def _fake_auth(self, methods):
        a = mock.MagicMock()
        a.last_email = "person@example.com"
        a.needs_second_step = True
        a.is_authenticated = False
        a.second_step_methods.return_value = {"methods": methods}
        a.send_second_step_code.return_value = (True, "")
        # Typed codes only unless a test turns approvals on.
        a.request_approval.side_effect = mfa.MfaError(
            "needs backup codes", code="no_server_factor", status=400)
        return a

    def _approving(self, methods=None):
        a = self._fake_auth(methods or [{"factorId": "f-app", "kind": "app"}])
        a.request_approval.side_effect = None
        a.request_approval.return_value = {
            "requestId": "r1", "claim": "secret-claim", "number": 47,
            "expiresInSeconds": 120}
        a.check_approval.return_value = ("pending", "")
        return a

    def test_approval_is_offered_first_with_the_number(self):
        a = self._approving()
        lw, _ = self._page(a)
        lw.show_second_step()
        a.request_approval.assert_called_once()
        self.assertEqual("pack", lw._approve_view.winfo_manager())
        self.assertEqual("47", lw._approve_number.cget("text"))
        self.assertIn("pick this number", lw._step_prompt.cget("text"))

    def test_approved_signs_in_and_hands_over(self):
        a = self._approving()
        lw, done = self._page(a)
        lw.show_second_step()

        def approved(request):
            self.assertEqual("secret-claim", request["claim"])
            a.is_authenticated = True
            a.needs_second_step = False
            return "approved", ""
        a.check_approval.side_effect = approved
        lw._poll_approval(lw._approval_gen)
        self.assertEqual([a], done)
        self.assertIsNone(lw._approval)

    def test_pending_keeps_waiting_and_denied_offers_it_again(self):
        a = self._approving()
        lw, done = self._page(a)
        lw.show_second_step()
        lw._poll_approval(lw._approval_gen)
        self.assertIsNotNone(lw._approval)     # still waiting
        self.assertEqual("", lw._approve_again_btn.winfo_manager())
        a.check_approval.return_value = ("denied", "")
        lw._poll_approval(lw._approval_gen)
        self.assertIsNone(lw._approval)        # claim forgotten
        self.assertEqual("pack", lw._approve_again_btn.winfo_manager())
        self.assertIn("turned down", lw._step_status.cget("text"))
        self.assertEqual([], done)
        lw._start_approval()                   # Ask again
        self.assertEqual(2, a.request_approval.call_count)

    def test_switched_off_hides_approval_and_keeps_typed_codes(self):
        a = self._approving([{"factorId": "f-app", "kind": "app"},
                             {"factorId": "f-b", "kind": "backup"}])
        a.request_approval.side_effect = mfa.MfaError(
            "switched off", code="sharing_off", status=403)
        lw, _ = self._page(a)
        lw.show_second_step()
        self.assertEqual("pack", lw._code_view.winfo_manager())
        self.assertEqual("", lw._step_status.winfo_manager())   # no fuss
        lw._show_picker()
        self.assertEqual(2, len(lw._pick_list.winfo_children()))

    def test_rate_limited_shows_why_and_keeps_the_option(self):
        a = self._approving()
        a.request_approval.side_effect = mfa.MfaError(
            "Too many sign-in requests.", code="rate_limited", status=429)
        lw, _ = self._page(a)
        lw.show_second_step()
        self.assertEqual("pack", lw._code_view.winfo_manager())
        self.assertEqual("Too many sign-in requests.",
                         lw._step_status.cget("text"))
        lw._show_picker()
        self.assertEqual(2, len(lw._pick_list.winfo_children()))

    def test_type_a_code_instead_stops_asking(self):
        a = self._approving()
        lw, _ = self._page(a)
        lw.show_second_step()
        gen = lw._approval_gen
        lw._approval_to_code()
        self.assertIsNone(lw._approval)
        self.assertEqual("pack", lw._code_view.winfo_manager())
        lw._poll_approval(gen)                 # a late poll does nothing
        a.check_approval.assert_not_called()

    def test_offline_methods_skip_approval(self):
        a = self._approving()
        a.second_step_methods.return_value = {
            "methods": [{"factorId": "f-app", "kind": "app"}], "offline": True}
        lw, _ = self._page(a)
        lw.show_second_step()
        a.request_approval.assert_not_called()
        self.assertEqual("pack", lw._code_view.winfo_manager())

    def test_password_result_swaps_the_form_for_the_code_page(self):
        a = self._fake_auth([{"factorId": "f-app", "kind": "app"}])
        lw, _ = self._page(a)
        lw._handle_result(True, "Enter your two-factor code.")
        self.assertTrue(lw._step_active)
        self.assertEqual("", lw._card.winfo_manager())
        self.assertEqual("pack", lw._step.winfo_manager())
        self.assertEqual("pack", lw._code_view.winfo_manager())
        a.send_second_step_code.assert_not_called()

    def test_a_sending_method_sends_its_code_when_chosen(self):
        a = self._fake_auth([{"factorId": "f-sms", "kind": "sms",
                              "destination": "+44 ••• 123"}])
        lw, _ = self._page(a)
        lw.show_second_step()
        a.send_second_step_code.assert_called_once_with("f-sms")
        self.assertIn("+44 ••• 123", lw._step_prompt.cget("text"))

    def test_verify_signs_in_and_hands_over(self):
        a = self._fake_auth([{"factorId": "f-app", "kind": "app"}])
        lw, done = self._page(a)
        lw.show_second_step()
        lw._code_var.set("12 34 56")
        self.assertEqual("123456", lw._code_var.get())

        def ok(method, code):
            a.is_authenticated = True
            a.needs_second_step = False
            return True, ""
        a.verify_second_step.side_effect = ok
        lw._submit()   # Enter on the code page means Verify
        a.verify_second_step.assert_called_once_with(
            {"factorId": "f-app", "kind": "app"}, "123456")
        self.assertEqual([a], done)
        self.assertFalse(lw._step_active)

    def test_use_a_different_account_cancels_and_shows_the_form(self):
        a = self._fake_auth([{"factorId": "f-app", "kind": "app"}])
        lw, _ = self._page(a)
        lw.show_second_step()
        lw._use_other_account()
        a.cancel_second_step.assert_called_once()
        self.assertFalse(lw._step_active)
        self.assertEqual("pack", lw._card.winfo_manager())

    def test_another_way_lists_every_method(self):
        a = self._fake_auth([{"factorId": "f-app", "kind": "app"},
                             {"factorId": "f-b", "kind": "backup"}])
        lw, _ = self._page(a)
        lw.show_second_step()
        lw._show_picker()
        self.assertEqual(2, len(lw._pick_list.winfo_children()))
        lw._choose({"factorId": "f-b", "kind": "backup"})
        self.assertEqual("Backup code", lw._code_label.cget("text"))


if __name__ == "__main__":
    unittest.main()
