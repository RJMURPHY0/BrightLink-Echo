"""The signed-in client, once shared, is never replaced by an anonymous one.

Seen 2026-10-12 in the API logs: after an auto sign-in Echo's reads went out
signed in, then every write (usage stats, diagnostics, update reports) went
out with only the publishable key and was refused with 401 until restart.
A startup call had started building an anonymous client before sign-in and
finished after set_client(), overwriting the shared signed-in client.
"""

import os
import sys
import threading
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase_client import SupabaseLogger


class SharedClientTests(unittest.TestCase):

    def test_a_slow_anonymous_build_never_overwrites_the_signed_in_client(self):
        log = SupabaseLogger("https://example.supabase.co", "anon-key")
        building = threading.Event()
        release = threading.Event()
        anonymous = object()

        def slow_create_client(_url, _key):
            building.set()
            release.wait(5)
            return anonymous

        fake_module = types.SimpleNamespace(create_client=slow_create_client)
        got = []
        with mock.patch.dict(sys.modules, {"supabase": fake_module}):
            t = threading.Thread(target=lambda: got.append(log._get_client()))
            t.start()
            self.assertTrue(building.wait(5))
            signed_in = object()
            log.set_client(signed_in)          # sign-in lands mid-build
            release.set()
            t.join(5)
        self.assertIs(log._get_client(), signed_in)
        self.assertIs(got[0], signed_in)

    def test_before_sign_in_an_anonymous_client_is_built_once(self):
        log = SupabaseLogger("https://example.supabase.co", "anon-key")
        made = []
        fake_module = types.SimpleNamespace(
            create_client=lambda u, k: made.append(object()) or made[-1])
        with mock.patch.dict(sys.modules, {"supabase": fake_module}):
            first = log._get_client()
            self.assertIs(log._get_client(), first)
        self.assertEqual(len(made), 1)


if __name__ == "__main__":
    unittest.main()
