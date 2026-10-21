"""Refresh-token rotation survives a restart, and Echo's sign-out stays local.

Supabase rotates refresh tokens: every refresh hands back a new one and the old
one stops working. These tests drive the REAL supabase_auth client against a
fake token server that rotates the same way, so they prove the token on disk
after a restore or a background refresh is the one the server still honours.

The "Refresh Token Not Found" sign-outs of 2026-10-20/21 were not rotation:
the auth logs show POST /logout?scope=global from app.brightlink.io for the
same user shortly before each failed boot. A global logout deletes EVERY
session the user has, Echo's included, in all three apps that share the
Supabase project. Echo's own sign-out did the same to the CRM and Notetaker,
so it must send scope=local.
"""
import base64
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from urllib.parse import parse_qs

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth
from auth import AuthManager
from supabase_auth import SyncGoTrueClient

_REAL_RESTORE_LOG_PATH = auth._restore_log_path
_REAL_SESSION_PATH = auth._session_path
_SANDBOX = None

_USER_ID = "00000000-0000-0000-0000-000000000001"


def setUpModule():
    # Never touch the user's real session file or auth-restore.log.
    global _SANDBOX
    _SANDBOX = tempfile.mkdtemp(prefix="echo_rotation_tests_")
    auth._restore_log_path = lambda: os.path.join(_SANDBOX, "auth-restore.log")
    auth._session_path = lambda: os.path.join(_SANDBOX, ".session")


def tearDownModule():
    auth._restore_log_path = _REAL_RESTORE_LOG_PATH
    auth._session_path = _REAL_SESSION_PATH
    shutil.rmtree(_SANDBOX, ignore_errors=True)


def _b64(obj) -> str:
    raw = json.dumps(obj).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwt(exp: int, n: int) -> str:
    return ".".join((_b64({"alg": "HS256", "typ": "JWT"}),
                     _b64({"sub": _USER_ID, "exp": exp, "n": n}),
                     "sig"))


def _user():
    return {"id": _USER_ID, "aud": "authenticated", "role": "authenticated",
            "email": "tester@example.com", "app_metadata": {},
            "user_metadata": {}, "created_at": "2026-01-01T00:00:00Z"}


class _RotatingTokenServer:
    """Minimal GoTrue: one session, refresh tokens are single use."""

    def __init__(self):
        self.lock = threading.Lock()
        self.counter = 0
        self.live_refresh = None
        self.live_access = set()
        self.logout_scopes = []
        self.logout_seen = threading.Event()

    def issue(self, expired: bool = False):
        with self.lock:
            self.counter += 1
            n = self.counter
            exp = int(time.time()) + (-60 if expired else 3600)
            at = _jwt(exp, n)
            rt = f"rt-{n}"
            self.live_refresh = rt
            self.live_access.add(at)
            return at, rt

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/token"):
            body = json.loads(request.content or b"{}")
            with self.lock:
                ok = body.get("refresh_token") == self.live_refresh
            if not ok:
                return httpx.Response(400, json={
                    "code": 400, "error_code": "refresh_token_not_found",
                    "msg": "Invalid Refresh Token: Refresh Token Not Found"})
            at, rt = self.issue()
            return httpx.Response(200, json={
                "access_token": at, "refresh_token": rt, "token_type": "bearer",
                "expires_in": 3600, "expires_at": int(time.time()) + 3600,
                "user": _user()})
        if path.endswith("/user"):
            return httpx.Response(200, json=_user())
        if path.endswith("/logout"):
            scope = parse_qs(request.url.query.decode()).get("scope", [""])[0]
            self.logout_scopes.append(scope)
            if scope == "global":
                with self.lock:
                    self.live_refresh = None
            self.logout_seen.set()
            return httpx.Response(204)
        return httpx.Response(404, json={"msg": f"unexpected {path}"})


def _manager(server: _RotatingTokenServer) -> AuthManager:
    """An AuthManager wired to the real supabase_auth client and the fake
    server, with Echo's own token-refresh listener attached."""
    mgr = AuthManager("https://example.supabase.co", "anon")
    gotrue = SyncGoTrueClient(
        url="https://example.supabase.co/auth/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(server.handler)),
        auto_refresh_token=False,
        persist_session=True,
    )
    mgr._client = types.SimpleNamespace(auth=gotrue)
    mgr._attach_auth_listener(mgr._client)
    return mgr


def _saved_refresh_token() -> str:
    with open(auth._session_path(), "rb") as f:
        return json.loads(auth._dpapi_decrypt(f.read()).decode())["refresh_token"]


class RefreshTokenRotationTests(unittest.TestCase):
    def setUp(self):
        try:
            os.remove(auth._session_path())
        except FileNotFoundError:
            pass
        self.server = _RotatingTokenServer()
        at, rt = self.server.issue(expired=True)
        types_session = types.SimpleNamespace(access_token=at, refresh_token=rt)
        AuthManager("https://example.supabase.co", "anon")._save_session(types_session)

    def test_restore_saves_the_rotated_token(self):
        mgr = _manager(self.server)
        self.assertTrue(mgr._restore_once(auth._session_path()))
        self.assertEqual(_saved_refresh_token(), self.server.live_refresh)

    def test_background_refresh_saves_the_rotated_token(self):
        mgr = _manager(self.server)
        self.assertTrue(mgr._restore_once(auth._session_path()))
        # What the SDK's auto-refresh timer does an hour into the session.
        mgr._client.auth.refresh_session()
        self.assertEqual(_saved_refresh_token(), self.server.live_refresh)

    def test_session_survives_restart_after_rotations(self):
        first = _manager(self.server)
        self.assertTrue(first._restore_once(auth._session_path()))
        first._client.auth.refresh_session()
        first._client.auth.refresh_session()

        restarted = _manager(self.server)
        self.assertTrue(restarted._restore_once(auth._session_path()))
        self.assertTrue(restarted.is_authenticated)
        self.assertTrue(os.path.exists(auth._session_path()))

    def test_global_logout_elsewhere_is_what_kills_the_saved_session(self):
        # Reproduces the 2026-10-21 incident: another app signs the same user
        # out with scope=global, and the next Echo boot is refused.
        mgr = _manager(self.server)
        self.assertTrue(mgr._restore_once(auth._session_path()))
        with self.server.lock:
            self.server.live_refresh = None  # what /logout?scope=global does
        # Next boot is hours later: the saved access token has expired, so
        # set_session must spend the saved refresh token.
        mgr._save_session(types.SimpleNamespace(
            access_token=_jwt(int(time.time()) - 60, 0),
            refresh_token=_saved_refresh_token()))

        restarted = _manager(self.server)
        self.assertFalse(restarted._restore_once(auth._session_path()))
        self.assertFalse(os.path.exists(auth._session_path()))


class SignOutScopeTests(unittest.TestCase):
    def test_echo_sign_out_only_ends_its_own_session(self):
        server = _RotatingTokenServer()
        at, rt = server.issue()
        mgr = _manager(server)
        mgr._client.auth.set_session(at, rt)
        mgr._user = types.SimpleNamespace(id=_USER_ID, email="")

        mgr.sign_out()

        self.assertTrue(server.logout_seen.wait(5), "sign-out never reached the server")
        self.assertEqual(server.logout_scopes, ["local"])


if __name__ == "__main__":
    unittest.main()
