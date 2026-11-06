"""Hardening: every offered Parakeet version is pinned to a commit and hashes."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asr_engine


class ModelPinTests(unittest.TestCase):
    def test_both_versions_have_a_full_commit_pin(self):
        for v in ("v2", "v3"):
            self.assertRegex(asr_engine._PINNED_REVISION[v], r"^[0-9a-f]{40}$", v)

    def test_download_url_uses_the_pinned_commit(self):
        url = asr_engine._hf_base("v3")
        self.assertIn(asr_engine._PINNED_REVISION["v3"], url)
        self.assertNotIn("/resolve/main", url)

    def test_v3_pins_cover_every_downloaded_file(self):
        pins = asr_engine._PINNED_FILES["v3"]
        self.assertEqual(set(pins), set(asr_engine._MODEL_FILES))
        for name, (size, digest) in pins.items():
            self.assertGreater(size, 0, name)
            self.assertRegex(digest, r"^[0-9a-f]{64}$", name)

    def test_size_check_is_exact_for_v3(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            with open(p, "wb") as f:
                f.write(b"x" * 97)
            self.assertTrue(asr_engine._size_ok(p, "config.json", "v3"))
            with open(p, "wb") as f:
                f.write(b"x" * 98)
            self.assertFalse(asr_engine._size_ok(p, "config.json", "v3"))


if __name__ == "__main__":
    unittest.main()
