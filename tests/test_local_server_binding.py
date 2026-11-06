"""Hardening: the local server takes its port exclusively, serves requests on
threads, times idle sockets out and stays on 127.0.0.1 with its Host check."""
import http.client
import os
import socket
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_mod


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LocalServerBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls._patch = mock.patch.object(app_mod, "_LOCAL_PORT", cls.port)
        cls._patch.start()
        app_mod._start_local_server(mock.Mock(), "0.0.0.0-test")
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()

    def _get(self, path, host):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            c.request("GET", path, headers={"Host": host})
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    def test_ping_answers_for_the_expected_host(self):
        status, body = self._get("/ping", app_mod._LOCAL_HOSTS[0])
        self.assertEqual(status, 200)
        self.assertIn(b'"ok"', body)

    def test_wrong_host_is_still_refused(self):
        status, _ = self._get("/ping", "evil.example:%d" % self.port)
        self.assertEqual(status, 403)

    def test_an_idle_connection_does_not_block_other_requests(self):
        idle = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        try:
            status, _ = self._get("/ping", app_mod._LOCAL_HOSTS[0])
            self.assertEqual(status, 200)
        finally:
            idle.close()

    @unittest.skipUnless(sys.platform == "win32", "Windows port sharing")
    def test_another_process_cannot_share_the_port(self):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            with self.assertRaises(OSError):
                s.bind(("127.0.0.1", self.port))
        finally:
            s.close()

    def test_source_binds_loopback_only_and_sets_timeout(self):
        src = open(app_mod.__file__, encoding="utf-8").read()
        body = src[src.index("def _start_local_server"):src.index("def _ensure_single_instance")]
        self.assertIn('("127.0.0.1", _LOCAL_PORT)', body)
        self.assertIn("SO_EXCLUSIVEADDRUSE", body)
        self.assertIn("ThreadingMixIn", body)
        self.assertIn("_Handler.timeout", body)


if __name__ == "__main__":
    unittest.main()
