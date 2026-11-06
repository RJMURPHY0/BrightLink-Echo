"""Hardening: voice training uploads need this machine's own flag as well as the
account's consent. The flag is seeded once from the consent a person already
has, and afterwards only the Settings toggle changes it."""
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice_training
from voice_training import VoiceTrainer


class _Flag:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, v):
        self.value = v


def _trainer(flag):
    return VoiceTrainer(lambda: "tok", local_flag=flag.get, set_local_flag=flag.set)


def _refresh(trainer, server_value):
    done = threading.Event()
    got = []
    with mock.patch.object(voice_training, "fetch_consent", return_value=server_value):
        trainer.refresh_consent(callback=lambda v: (got.append(v), done.set()))
        assert done.wait(3)
    return got[0]


class LocalFlagTests(unittest.TestCase):
    def test_server_consent_alone_does_not_enable_uploads(self):
        flag = _Flag(False)
        t = _trainer(flag)
        shown = _refresh(t, True)
        self.assertFalse(t.enabled)
        self.assertFalse(shown)            # the toggle shows what Echo will do
        self.assertIs(flag.value, False)   # a server answer never flips it later

    def test_both_on_enables(self):
        flag = _Flag(True)
        t = _trainer(flag)
        self.assertTrue(_refresh(t, True))
        self.assertTrue(t.enabled)

    def test_first_run_seeds_on_for_someone_who_opted_in(self):
        flag = _Flag(None)
        t = _trainer(flag)
        self.assertTrue(_refresh(t, True))
        self.assertIs(flag.value, True)
        self.assertTrue(t.enabled)

    def test_first_run_seeds_off_for_someone_who_did_not(self):
        flag = _Flag(None)
        t = _trainer(flag)
        _refresh(t, False)
        self.assertIs(flag.value, False)
        self.assertFalse(t.enabled)

    def test_unreachable_server_seeds_nothing_and_uploads_nothing(self):
        flag = _Flag(None)
        t = _trainer(flag)
        self.assertIsNone(_refresh(t, None))
        self.assertIsNone(flag.value)
        self.assertFalse(t.enabled)

    def test_toggle_sets_the_flag(self):
        flag = _Flag(False)
        t = _trainer(flag)
        done = threading.Event()
        with mock.patch.object(voice_training, "push_consent", return_value=True):
            t.set_consent(True, callback=lambda ok: done.set())
            self.assertTrue(done.wait(3))
        self.assertIs(flag.value, True)
        self.assertTrue(t.enabled)

    def test_failed_toggle_restores_the_flag(self):
        flag = _Flag(False)
        t = _trainer(flag)
        done = threading.Event()
        with mock.patch.object(voice_training, "push_consent", return_value=False):
            t.set_consent(True, callback=lambda ok: done.set())
            self.assertTrue(done.wait(3))
        self.assertIs(flag.value, False)
        self.assertFalse(t.enabled)

    def test_offer_does_not_upload_without_the_flag(self):
        flag = _Flag(False)
        t = _trainer(flag)
        t._consent = True
        with mock.patch.object(voice_training.audio_store, "find") as find:
            t.offer("2026-01-01T00:00:00")
        find.assert_not_called()

    def test_without_accessors_behaviour_is_unchanged(self):
        t = VoiceTrainer(lambda: "tok")
        t._consent = True
        self.assertTrue(t.enabled)


class ConfigFieldTests(unittest.TestCase):
    def test_default_is_unset(self):
        from config import Config
        self.assertIsNone(Config().voice_training_local)


if __name__ == "__main__":
    unittest.main()
