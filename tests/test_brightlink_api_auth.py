"""A 401 checks the session once without treating a network outage as logout."""

import io
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brightlink_api import RetryingSupabaseClient, call_with_auth_retry
import ai_refiner


def _unauthorised():
    return urllib.error.HTTPError(
        "https://app.brightlink.io/api/whisper/ai", 401, "Unauthorised",
        {}, io.BytesIO(b""))


class BrightLinkAuthRetryTests(unittest.TestCase):
    def test_401_then_dead_refresh_signs_out(self):
        auth = mock.Mock()
        auth.refresh_session.side_effect = ValueError(
            "Invalid Refresh Token: Refresh Token Not Found")
        ended = mock.Mock()
        operation = mock.Mock(side_effect=_unauthorised())

        with self.assertRaises(urllib.error.HTTPError):
            call_with_auth_retry(operation, auth, ended)

        operation.assert_called_once()
        auth.refresh_session.assert_called_once()
        ended.assert_called_once()

    def test_401_then_network_error_keeps_session(self):
        auth = mock.Mock()
        auth.refresh_session.side_effect = OSError(
            "Connection timeout: refresh token not found")
        ended = mock.Mock()
        operation = mock.Mock(side_effect=_unauthorised())

        with self.assertRaises(urllib.error.HTTPError):
            call_with_auth_retry(operation, auth, ended)

        operation.assert_called_once()
        auth.refresh_session.assert_called_once()
        ended.assert_not_called()

    def test_401_then_refresh_ok_retries_once(self):
        auth = mock.Mock()
        ended = mock.Mock()
        operation = mock.Mock(side_effect=[_unauthorised(), "done"])

        self.assertEqual(call_with_auth_retry(operation, auth, ended), "done")
        self.assertEqual(operation.call_count, 2)
        auth.refresh_session.assert_called_once()
        ended.assert_not_called()

    def test_supabase_query_uses_the_shared_retry(self):
        auth = mock.Mock()
        ended = mock.Mock()
        query = mock.Mock()
        query.execute.side_effect = [_unauthorised(), "saved"]
        client = mock.Mock()
        client.table.return_value = query

        wrapped = RetryingSupabaseClient(client, auth, ended)
        self.assertEqual(wrapped.table("echo_user_state").execute(), "saved")
        self.assertEqual(query.execute.call_count, 2)
        auth.refresh_session.assert_called_once()
        ended.assert_not_called()

    def test_server_error_does_not_refresh_or_sign_out(self):
        auth = mock.Mock()
        ended = mock.Mock()
        failure = urllib.error.HTTPError(
            "https://app.brightlink.io/api/whisper/ai", 503, "Unavailable",
            {}, io.BytesIO(b""))
        with self.assertRaises(urllib.error.HTTPError):
            call_with_auth_retry(mock.Mock(side_effect=failure), auth, ended)
        auth.refresh_session.assert_not_called()
        ended.assert_not_called()

    def test_relay_retry_sends_the_new_token(self):
        token = ["old-token"]
        auth = mock.Mock()
        auth.refresh_session.side_effect = lambda: token.__setitem__(0, "new-token")
        ended = mock.Mock()
        refiner = ai_refiner.AIRefiner(
            token_provider=lambda: token[0], auth_manager=auth,
            on_session_expired=ended)
        headers = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"text":"done"}'

        def urlopen(request, timeout):
            headers.append(request.get_header("Authorization"))
            if len(headers) == 1:
                raise _unauthorised()
            return Response()

        with mock.patch.object(ai_refiner.urllib.request, "urlopen", urlopen):
            self.assertEqual(refiner._relay_chat("system", "user", 32, 0), "done")
        self.assertEqual(headers, ["Bearer old-token", "Bearer new-token"])
        auth.refresh_session.assert_called_once()
        ended.assert_not_called()


if __name__ == "__main__":
    unittest.main()
