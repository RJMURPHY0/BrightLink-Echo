"""Session restore after a reboot, and the page-swap repaint.

Two shipped bugs are pinned here.

1. A cold boot starts the app before the network is up, so the restore overruns
   the wait. The old code abandoned the worker, returned False, started a SECOND
   restore against the same on-disk refresh token, and Supabase — which rotates
   refresh tokens — answered "Refresh Token Not Found". That text matched the
   auth-failure heuristic, the session file was deleted, and the user had to
   sign in again. Meanwhile the retry loop saw is_authenticated and returned
   WITHOUT promoting, leaving the login form up over a signed-in app.

2. The login->dashboard swap moves and resizes the window AFTER the atomic
   present, and RDW_UPDATENOW only validates Tk's update region (Tk draws on a
   later mainloop spin). Without a heal after the geometry change, the old
   page's pixels get blitted into the new position and stay there.

The restore tests below used to write into the user's REAL
%LOCALAPPDATA%\\FTC Whisper\\auth-restore.log. Every local test run appended a
block of fake incidents (a "DEFINITIVE auth failure — SESSION CLEARED", two
"IGNORED stale auth error" lines, "list index out of range", two "OK (late)")
that read exactly like a real sign-out, and cost a day of forensics on
2026-09-21. The whole module now runs against a throwaway folder: see
setUpModule and DiagnosticsIsolationTests.
"""
import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth
from auth import AuthManager, _is_definitive_auth_error

_REAL_RESTORE_LOG_PATH = auth._restore_log_path
_REAL_SESSION_PATH = auth._session_path
_SANDBOX = None


def setUpModule():
    # auth-restore.log is the ONE place a real reboot sign-out can be
    # diagnosed from, so no test may write to it, and no test may read,
    # rewrite or delete the user's real .session either.
    global _SANDBOX
    _SANDBOX = tempfile.mkdtemp(prefix="ftc_whisper_restore_tests_")
    auth._restore_log_path = lambda: os.path.join(_SANDBOX, "auth-restore.log")
    auth._session_path = lambda: os.path.join(_SANDBOX, ".session")


def tearDownModule():
    auth._restore_log_path = _REAL_RESTORE_LOG_PATH
    auth._session_path = _REAL_SESSION_PATH
    shutil.rmtree(_SANDBOX, ignore_errors=True)


def _sandbox_log_lines():
    try:
        with open(auth._restore_log_path(), encoding="utf-8") as f:
            return f.read().splitlines()
    except FileNotFoundError:
        return []


class ErrorClassifierTests(unittest.TestCase):
    def test_dead_tokens_are_auth_errors(self):
        for msg in ("Invalid Refresh Token: Refresh Token Not Found",
                    "invalid_grant", "JWT expired", "Unauthorized"):
            self.assertTrue(_is_definitive_auth_error(msg), msg)

    def test_network_failures_are_never_auth_errors(self):
        # These carry words like "not found" / "invalid" but mean the network
        # is down, not that the credentials are dead.
        for msg in ("[Errno 11001] getaddrinfo failed",
                    "ConnectError: All connection attempts failed",
                    "Read timed out",
                    "SSLError: certificate verify failed",
                    "Name or service not known",
                    "Max retries exceeded with url"):
            self.assertFalse(_is_definitive_auth_error(msg), msg)

    def test_empty_message_is_not_an_auth_error(self):
        self.assertFalse(_is_definitive_auth_error(""))
        self.assertFalse(_is_definitive_auth_error(None))


class _StubAuth(AuthManager):
    """AuthManager with the network and disk replaced."""

    def __init__(self, error=None, tokens=("at", "rt")):
        super().__init__("https://example.invalid", "key")
        self._error = error
        self._tokens = tokens
        self.cleared = False
        self.client_requests = 0

    def _clear_session(self):
        self.cleared = True
        self._user = None

    def _get_client(self):
        # Never build the real Supabase client: it costs a ~9s cold import and
        # points a live HTTP client at the network. A test that needs a client
        # supplies a fake one on the instance.
        self.client_requests += 1
        raise RuntimeError("stub: no real Supabase client in tests")


class _FakeClient:
    """A Supabase client whose set_session raises the given exception."""

    def __init__(self, exc):
        def _set_session(_at, _rt):
            raise exc
        self.auth = types.SimpleNamespace(set_session=_set_session)


class RestoreDoesNotDeleteGoodSessionsTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(
            os.environ.get("TEMP", "."), "ftc_whisper_test_session.bin")
        # Plain JSON — the legacy on-disk shape, which _restore_once parses via
        # its non-DPAPI fallback, so the test reaches the network step.
        with open(self.path, "wb") as f:
            f.write(b'{"access_token": "at", "refresh_token": "rt"}')
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))

    def test_network_failure_keeps_the_session_file(self):
        # The failure is raised at the SERVER step. This test used to raise it
        # from _dpapi_decrypt, where the plain-JSON fallback swallowed it; the
        # restore then built a real Supabase client and died on
        # set_session("at", ...) splitting a non-JWT ("list index out of
        # range"), so the network branch was never exercised at all.
        mgr = _StubAuth()
        client = _FakeClient(RuntimeError("[Errno 11001] getaddrinfo failed"))
        mgr._get_client = lambda: client
        self.assertFalse(mgr._restore_once(self.path))
        self.assertFalse(mgr.cleared)
        self.assertIn("RETRY: network/other error", _sandbox_log_lines()[-1])

    def test_unreadable_session_file_is_kept_without_contacting_the_server(self):
        with open(self.path, "wb") as f:
            f.write(b"\x00neither DPAPI nor JSON")
        mgr = _StubAuth()
        self.assertFalse(mgr._restore_once(self.path))
        self.assertFalse(mgr.cleared)
        self.assertEqual(0, mgr.client_requests)
        self.assertIn("session file unreadable", _sandbox_log_lines()[-1])

    def test_auth_error_is_ignored_when_already_signed_in(self):
        """A late-landing attempt already signed us in — a loser's rotation
        error must not delete the session it just refreshed."""
        mgr = _StubAuth()
        mgr._user = types.SimpleNamespace(id="u", email="a@b.c")
        mgr._get_client = lambda: (_ for _ in ()).throw(
            RuntimeError("Invalid Refresh Token: Refresh Token Not Found"))
        self.assertFalse(mgr._restore_once(self.path))
        self.assertFalse(mgr.cleared)

    def test_auth_error_is_ignored_when_the_file_was_refreshed_meanwhile(self):
        mgr = _StubAuth()

        def _rotated():
            with open(self.path, "wb") as f:
                f.write(b"fresher-bytes")
            raise RuntimeError("Refresh Token Not Found")

        mgr._get_client = lambda: _rotated()
        self.assertFalse(mgr._restore_once(self.path))
        self.assertFalse(mgr.cleared)

    def test_a_genuine_auth_error_still_clears(self):
        mgr = _StubAuth()
        mgr._get_client = lambda: (_ for _ in ()).throw(
            RuntimeError("Invalid Refresh Token: Refresh Token Not Found"))
        self.assertFalse(mgr._restore_once(self.path))
        self.assertTrue(mgr.cleared)


class DiagnosticsIsolationTests(unittest.TestCase):
    """Regression for 2026-09-21: the tests' fake restore outcomes landed in
    the user's real auth-restore.log and were read as a real sign-out."""

    def _assert_sandboxed(self, real, current):
        self.assertNotEqual(os.path.normcase(os.path.abspath(real)),
                            os.path.normcase(os.path.abspath(current)))
        self.assertTrue(os.path.normcase(os.path.abspath(current)).startswith(
            os.path.normcase(os.path.abspath(_SANDBOX))), current)

    def test_restore_outcomes_never_reach_the_users_real_log(self):
        self._assert_sandboxed(_REAL_RESTORE_LOG_PATH(), auth._restore_log_path())

    def test_restores_never_touch_the_users_real_session_file(self):
        # A non-stubbed _save_session or _clear_session writes or deletes
        # whatever _session_path() names.
        self._assert_sandboxed(_REAL_SESSION_PATH(), auth._session_path())


class LateRestorePromotesTests(unittest.TestCase):
    def setUp(self):
        # _session_path is a module global; restore it or later tests in
        # the suite read this test's temp file.
        self.addCleanup(setattr, auth, "_session_path", auth._session_path)

    def test_a_restore_that_lands_after_the_wait_fires_the_listener(self):
        import threading
        released = threading.Event()
        mgr = _StubAuth()
        fired = []
        mgr.set_restore_listener(lambda: fired.append(True))

        def _slow(_path):
            released.wait(5.0)
            mgr._user = types.SimpleNamespace(id="u", email="a@b.c")
            return True

        mgr._restore_once = _slow
        path = os.path.join(os.environ.get("TEMP", "."),
                            "ftc_whisper_test_session2.bin")
        with open(path, "wb") as f:
            f.write(b"x")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        auth._session_path = lambda: path

        self.assertFalse(mgr._load_saved_session(wait_seconds=0.05))
        self.assertEqual([], fired)          # nothing yet — still in flight
        self.assertTrue(mgr.restore_in_flight)
        released.set()
        mgr._restore_thread.join(5.0)
        self.assertEqual([True], fired)      # promoted late, not dropped

    def test_a_second_call_waits_instead_of_starting_a_rival_restore(self):
        import threading
        started = []
        gate = threading.Event()
        mgr = _StubAuth()

        def _slow(_path):
            started.append(1)
            gate.wait(5.0)
            mgr._user = types.SimpleNamespace(id="u", email="a@b.c")
            return True

        mgr._restore_once = _slow
        path = os.path.join(os.environ.get("TEMP", "."),
                            "ftc_whisper_test_session3.bin")
        with open(path, "wb") as f:
            f.write(b"x")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        auth._session_path = lambda: path

        mgr._load_saved_session(wait_seconds=0.05)
        # The retry loop fires again while the first attempt is STILL talking to
        # the server. Replaying the same (already-rotated) refresh token is what
        # produced "Refresh Token Not Found" and deleted a good session, so this
        # call must join the attempt in flight, not start a rival one.
        second = threading.Thread(
            target=lambda: mgr._load_saved_session(wait_seconds=5.0))
        second.start()
        threading.Event().wait(0.2)
        self.assertEqual(1, len(started))
        gate.set()
        second.join(5.0)
        mgr._restore_thread.join(5.0)
        self.assertEqual(1, len(started))
        self.assertTrue(mgr.is_authenticated)


class _FakeRoot:
    def __init__(self):
        self.after_calls = []
        self.geometry_calls = []

    def after(self, ms, fn=None, *a):
        self.after_calls.append((ms, fn))
        return f"job{len(self.after_calls)}"

    def after_cancel(self, _job):
        pass

    def winfo_screenheight(self):
        return 1080

    def winfo_screenwidth(self):
        return 1920


class PageSwapHealTests(unittest.TestCase):
    """_atomic_ui must repaint AFTER it applies the deferred geometry, and the
    Configure heal must fire on a MOVE as well as a resize (a page swap
    recentres the window, so two same-height pages only ever move)."""

    def test_atomic_ui_repaints_after_the_deferred_geometry(self):
        import inspect
        from app_window import AppWindow
        src = inspect.getsource(AppWindow._atomic_ui)
        geo_at = src.index("self._root.geometry(geo)")
        heal_at = src.index("self._repaint_all(erase=moved)")
        self.assertLess(geo_at, heal_at,
                        "the heal must come after the geometry change")

    def test_erase_is_reserved_for_swaps_that_moved_the_window(self):
        """Erasing a same-size swap flashes the whole window background for a
        frame. Only a move/resize exposes pixels no widget repaints over."""
        import inspect
        from app_window import AppWindow
        src = inspect.getsource(AppWindow._atomic_ui)
        self.assertIn("moved = bool(geo)", src)
        self.assertNotIn("self._repaint_all(erase=True)", src)

    def test_configure_heal_is_gated_on_geometry_not_size(self):
        import inspect
        from app_window import AppWindow
        src = inspect.getsource(AppWindow._on_root_configure)
        self.assertIn("_last_repaint_geom", src)
        self.assertIn("erase=True", src)

    def test_repaint_all_never_targets_the_desktop(self):
        import inspect
        from app_window import AppWindow
        src = inspect.getsource(AppWindow._repaint_all)
        # RedrawWindow(NULL) repaints the whole screen; _top_hwnd returns 0 on
        # failure, so the guard has to be there.
        self.assertIn("if not hwnd:", src)


class SplashRevealTests(unittest.TestCase):
    """The splash must not drop to the login form while a restore is running,
    and must promote (not just return) once the session is valid."""

    def _window(self, authenticated=False, saved=True, in_flight=False):
        from app_window import AppWindow
        w = AppWindow.__new__(AppWindow)
        w._root = _FakeRoot()
        w._auth = types.SimpleNamespace(
            is_authenticated=authenticated,
            has_saved_session=lambda: saved,
            restore_in_flight=in_flight,
        )
        w.calls = []
        w._promote_restored_session = lambda: w.calls.append("promote")
        w._reveal_login_now = lambda: w.calls.append("reveal")
        return w

    def test_in_flight_restore_reschedules_instead_of_revealing(self):
        w = self._window(in_flight=True)
        w._reveal_login_if_pending()
        self.assertEqual([], w.calls)
        self.assertTrue(w._root.after_calls)

    def test_idle_restore_keeps_the_splash(self):
        # A saved session still on disk means a restore is still viable (the
        # network is just slow/blackholed after a cold boot), so the splash
        # stays up and the check reschedules — it must NOT reveal the login
        # form. That flip is exactly what made a slow-network boot read as a
        # forced re-sign-in. The "Sign in manually" escape on the splash is the
        # deliberate way out for anyone who won't wait.
        w = self._window(in_flight=False, saved=True)
        w._reveal_login_if_pending()
        self.assertEqual([], w.calls)
        self.assertTrue(w._root.after_calls)

    def test_authenticated_promotes_rather_than_returning(self):
        w = self._window(authenticated=True)
        w._reveal_login_if_pending()
        self.assertEqual(["promote"], w.calls)

    def test_cleared_session_reveals_immediately(self):
        w = self._window(saved=False, in_flight=True)
        w._reveal_login_if_pending()
        self.assertEqual(["reveal"], w.calls)

    def test_retry_loop_promotes_when_already_authenticated(self):
        import inspect
        from app_window import AppWindow
        src = inspect.getsource(AppWindow._session_restore_retry_loop)
        head = src[:src.index("if not self._auth.has_saved_session()")]
        self.assertIn("_promote_restored_session", head,
                      "the is_authenticated early-return must promote first")

    def test_retry_loop_never_gives_up_while_a_session_file_exists(self):
        # The old 30-attempt budget expired after ~13 minutes. On a machine
        # whose network flaps in blackhole windows after a reboot (measured
        # live 2026-08-13), every burst attempt landed in a bad window and the
        # app then sat at the login form for the REST OF THE SESSION with a
        # perfectly valid session file on disk. The loop now retries forever
        # (steady once-a-minute after the burst); it exits only on success,
        # a cleared session file, or a manual sign-in.
        import inspect
        from app_window import AppWindow
        src = inspect.getsource(AppWindow._session_restore_retry_loop)
        self.assertIn("while True", src)
        self.assertIn("_RESTORE_STEADY_GAP", src)
        # The loop reveals the login form ONLY when the session file has been
        # cleared (a definitive auth failure), and that branch returns. There
        # is no attempt-count reveal that drops the user to the form while a
        # valid session still exists — the splash stays up instead (see
        # _reveal_login_if_pending), which is the whole point.
        reveals = src.count("_reveal_login_now")
        self.assertLessEqual(reveals, 1,
                             "only the file-cleared branch may reveal the form")
        if reveals:
            after = src[src.index("_reveal_login_now"):]
            self.assertIn("return", after[:80],
                          "the file-cleared reveal must terminate the loop")


if __name__ == "__main__":
    unittest.main()
