"""Hardening: a leftover stored account password is deleted when config loads,
whatever the project URL, and the rest of the settings are kept."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config


class LegacyPasswordTests(unittest.TestCase):
    def _load(self, data):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        cfg = Config.load(path)
        with open(path, encoding="utf-8") as f:
            return cfg, json.load(f)

    def test_password_removed_for_a_current_project_url(self):
        cfg, on_disk = self._load({"supabase_url": "https://example.test",
                                   "supabase_email": "a@example.test",
                                   "supabase_password": "not-a-real-password",
                                   "hotkey": "alt+7"})
        self.assertEqual(cfg.supabase_password, "")
        self.assertEqual(on_disk.get("supabase_password", ""), "")
        self.assertEqual(cfg.hotkey, "alt+7")
        self.assertEqual(cfg.supabase_email, "a@example.test")

    def test_no_password_leaves_the_file_alone(self):
        cfg, on_disk = self._load({"hotkey": "alt+8"})
        self.assertEqual(cfg.supabase_password, "")
        self.assertEqual(cfg.hotkey, "alt+8")


if __name__ == "__main__":
    unittest.main()
