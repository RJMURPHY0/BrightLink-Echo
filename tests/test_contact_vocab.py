"""The CRM vocabulary comes from the names the user actually deals with.

Before 2026-10-12 fetch_contact_vocab read the first contacts rows RLS
returned: 150 scraped US forklift dealers for Ryan, none of whom he dictates.
It now asks echo_vocab_terms (ranked by the user's own activity) first and
only falls back to the plain read when that function is unavailable.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase_client import SupabaseLogger


class _Rows:
    def __init__(self, data=None, error=None):
        self.data, self.error = data, error

    def select(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        if self.error:
            raise self.error
        return types.SimpleNamespace(data=self.data)


class _Client:
    def __init__(self, ranked=None, rpc_error=None, contacts=()):
        self.ranked, self.rpc_error, self.contacts = ranked, rpc_error, list(contacts)
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return _Rows(self.ranked, self.rpc_error)

    def table(self, name):
        self.calls.append((name, None))
        return _Rows(self.contacts)


def _logger(client):
    log = SupabaseLogger("https://example.supabase.co", "anon-key")
    log.set_client(client)
    log.set_user("user-a")
    return log


class ContactVocabTests(unittest.TestCase):

    def test_ranked_names_come_first_and_alone(self):
        client = _Client(ranked=[{"term": "Jason Griffin", "kind": "colleague"},
                                 {"term": " Uniserve  Group ", "kind": "company"},
                                 {"term": "Al", "kind": "person"}])
        self.assertEqual(["Jason Griffin", "Uniserve Group"],
                         _logger(client).fetch_contact_vocab())
        self.assertEqual([("echo_vocab_terms", {"p_limit": 150})], client.calls)

    def test_falls_back_to_contacts_when_the_function_is_missing(self):
        client = _Client(rpc_error=RuntimeError("PGRST202 function not found"),
                         contacts=[{"first_name": "Gary", "last_name": "Cobbing",
                                    "company": "Uniserve Group"}])
        self.assertEqual(["Gary Cobbing", "Uniserve Group"],
                         _logger(client).fetch_contact_vocab())

    def test_an_empty_ranking_falls_back_too(self):
        client = _Client(ranked=[], contacts=[{"first_name": "Gary",
                                               "last_name": "Cobbing", "company": ""}])
        self.assertEqual(["Gary Cobbing"], _logger(client).fetch_contact_vocab())


if __name__ == "__main__":
    unittest.main()
