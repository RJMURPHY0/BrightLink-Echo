"""Cloud Sync: opt-in (default OFF) sync of everything personal between PCs.

Asked for 2026-09-29: off by default for everyone, opt in and out in
Settings, and when on it carries "pretty much everything" to the user's other
PCs; turning it off offers to delete what is in the cloud. Daily usage counts
stay outside it (BrightLink Home reads them).

The default-off tests are the ones that matter most: before v1.7.4 history
text, vocabulary and snippets were uploaded for every signed-in user with no
switch, so a regression here silently uploads what someone said.
"""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audio_store
import cloud_sync
import supabase_client
from cloud_sync import merge_phrases, merge_settings, missing_from_cloud
from supabase_client import SupabaseLogger


def _logger(sync=False, user="user-a"):
    log = SupabaseLogger("https://x.supabase.co", "anon")
    log._client = object()
    log.set_user(user)
    log.set_sync_enabled(sync)
    return log


class TempHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        hist = os.path.join(self.tmp, "history.json")
        stones = os.path.join(self.tmp, "history-tombstones.json")
        for target, value in ((supabase_client, "_local_history_path"),
                              (supabase_client, "_tombstones_path")):
            p = mock.patch.object(target, value,
                                  (lambda h=hist: h) if value == "_local_history_path"
                                  else (lambda s=stones: s))
            p.start()
            self.addCleanup(p.stop)
        self.hist = hist

    def read(self):
        with open(self.hist, encoding="utf-8") as f:
            return json.load(f)


# ── Off by default ───────────────────────────────────────────────────────────

class DefaultOffTests(TempHistory):

    def test_the_setting_is_off_by_default(self):
        import config
        self.assertFalse(config.Config().cloud_sync)
        self.assertFalse(SupabaseLogger("https://x", "k").sync_enabled)

    def test_a_dictation_is_saved_here_but_not_uploaded(self):
        log = _logger(sync=False)
        sent = []
        log._run = sent.append
        log.log_transcription("what I said", created_at="2026-09-29T10:00:00+00:00")
        self.assertEqual(sent, [])
        self.assertEqual(self.read()[0]["transcribed_text"], "what I said")

    def test_refinements_are_not_uploaded(self):
        log = _logger(sync=False)
        sent = []
        log._run = sent.append
        log.log_refinement("a", "b", "replace")
        self.assertEqual(sent, [])

    def test_history_is_not_pulled_down(self):
        log = _logger(sync=False)
        with mock.patch.object(log, "_fetch_remote_history",
                               side_effect=AssertionError("fetched")):
            log.refresh_history(user_id="user-a")
            log.refresh_history_async()

    def test_vocabulary_and_snippets_neither_push_nor_pull(self):
        log = _logger(sync=False)
        with mock.patch.object(log, "_get_client",
                               side_effect=AssertionError("network")):
            log.push_library("vocabulary", [{"id": "1", "term": "Vercel"}])
            self.assertEqual(log.fetch_library("snippets"), [])

    def test_everything_is_uploaded_when_the_user_turns_it_on(self):
        log = _logger(sync=True)
        sent = []
        log._run = sent.append
        log.log_transcription("hello", created_at="2026-09-29T10:00:00+00:00")
        self.assertEqual(sent[0]["transcribed_text"], "hello")
        self.assertEqual(sent[0]["user_id"], "user-a")

    def test_signed_out_is_never_active(self):
        log = _logger(sync=True, user=None)
        self.assertFalse(log.sync_active)

    def test_app_hands_the_saved_choice_to_the_logger(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "app.py"), encoding="utf-8").read()
        self.assertIn('self.db.set_sync_enabled(bool(getattr(config, "cloud_sync", False)))',
                      src)


class UsageCountsStayOnTests(unittest.TestCase):
    """Decided 2026-09-29: word counts and seconds spoken keep reaching the
    BrightLink account (Home dashboards read them); they hold no words."""

    def test_stats_still_get_a_client_with_sync_off(self):
        import stats
        db = types.SimpleNamespace(is_enabled=True, sync_enabled=False,
                                   _get_client=lambda: "client")
        self.assertEqual(stats.StatsStore(db=db)._client_or_none(), "client")

    def test_delete_my_data_leaves_the_usage_counts_alone(self):
        client = _FakeClient()
        log = _logger(sync=False)
        log._client = client
        log.delete_cloud_data()
        self.assertNotIn("user_daily_stats", client.deleted)


class DiagnosticsTests(unittest.TestCase):

    def _wire(self, sync):
        import app as app_mod
        a = app_mod.WhisperFlowApp.__new__(app_mod.WhisperFlowApp)
        a.db = types.SimpleNamespace(sync_enabled=sync)
        seen = []
        a._log_error_event = lambda ev, detail, **kw: seen.append(detail)
        a._wire_hallucination_reporter()
        import hallucination
        self.addCleanup(hallucination.set_reporter, None)
        hallucination.report("transcribe_repetition",
                             {"words": 9, "sample": "what I actually said"})
        return seen[0]

    def test_a_text_sample_never_leaves_with_sync_off(self):
        self.assertEqual(self._wire(False), {"words": 9})

    def test_the_sample_is_kept_when_the_user_chose_cloud_sync(self):
        self.assertEqual(self._wire(True)["sample"], "what I actually said")


# ── Merge rules ──────────────────────────────────────────────────────────────

DEFAULTS = {"auto_lists": True, "sound_feedback": True, "end_punctuation": "smart"}


class SettingsMergeTests(unittest.TestCase):

    def test_the_newer_change_wins_either_way(self):
        local = {"auto_lists": False}
        vals, stamps, apply_here = merge_settings(
            local, {"auto_lists": "2026-09-29T10:00:00+00:00"},
            {"values": {"auto_lists": True},
             "stamps": {"auto_lists": "2026-09-29T11:00:00+00:00"}}, DEFAULTS)
        self.assertEqual(apply_here, {"auto_lists": True})
        vals, stamps, apply_here = merge_settings(
            local, {"auto_lists": "2026-09-29T12:00:00+00:00"},
            {"values": {"auto_lists": True},
             "stamps": {"auto_lists": "2026-09-29T11:00:00+00:00"}}, DEFAULTS)
        self.assertEqual(apply_here, {})
        self.assertFalse(vals["auto_lists"])

    def test_with_no_history_a_chosen_value_beats_the_default(self):
        # The old PC turned sounds off long before Cloud Sync existed (no
        # stamp); the new laptop is on the default. The choice must travel.
        vals, _s, apply_here = merge_settings(
            {"sound_feedback": True}, {},
            {"values": {"sound_feedback": False}, "stamps": {}}, DEFAULTS)
        self.assertEqual(apply_here, {"sound_feedback": False})
        # ...and the other way round the laptop keeps its own chosen value.
        vals, _s, apply_here = merge_settings(
            {"sound_feedback": False}, {},
            {"values": {"sound_feedback": True}, "stamps": {}}, DEFAULTS)
        self.assertEqual(apply_here, {})
        self.assertFalse(vals["sound_feedback"])

    def test_first_sync_with_an_empty_cloud_uploads_everything_local(self):
        vals, _s, apply_here = merge_settings(
            {"auto_lists": True, "end_punctuation": "never"}, {}, None, DEFAULTS)
        self.assertEqual(vals, {"auto_lists": True, "end_punctuation": "never"})
        self.assertEqual(apply_here, {})

    def test_machine_settings_never_travel(self):
        for key in ("input_device", "hotkey", "popup_height", "start_with_windows",
                    "whisper_model", "anthropic_api_key", "cloud_sync"):
            self.assertNotIn(key, cloud_sync.SYNCED_SETTINGS)
        vals, _s, apply_here = merge_settings(
            {}, {}, {"values": {"input_device": "USB mic"}}, DEFAULTS)
        self.assertNotIn("input_device", vals)
        self.assertNotIn("input_device", apply_here)


class PhraseMergeTests(unittest.TestCase):

    def test_counts_merge_by_max_and_phrases_union(self):
        a = {"phrases": [{"phrase": "push to main", "count": 4,
                          "learned_at": "2026-09-01"}],
             "candidates": {"lead finder": [2, "2026-09-02"]}}
        b = {"phrases": [{"phrase": "push to main", "count": 9,
                          "learned_at": "2026-09-05"},
                         {"phrase": "brightlink", "count": 5, "learned_at": "2026-09-03"}],
             "candidates": {"lead finder": [3, "2026-09-01"]}}
        m = merge_phrases(a, b)
        by = {p["phrase"]: p for p in m["phrases"]}
        self.assertEqual(by["push to main"]["count"], 9)
        self.assertEqual(by["push to main"]["learned_at"], "2026-09-01")
        self.assertIn("brightlink", by)
        self.assertEqual(m["candidates"]["lead finder"], [3, "2026-09-02"])

    def test_a_forgotten_phrase_is_not_handed_back_by_another_pc(self):
        here = {"phrases": [], "forgotten": {"push it": "2026-09-29T10:00:00"}}
        there = {"phrases": [{"phrase": "push it", "count": 8,
                              "learned_at": "2026-09-20T00:00:00"}],
                 "candidates": {"push it": [3, "x"]}}
        m = merge_phrases(here, there)
        self.assertEqual(m["phrases"], [])
        self.assertNotIn("push it", m["candidates"])

    def test_a_phrase_learned_again_after_forgetting_survives(self):
        here = {"forgotten": {"push it": "2026-09-01T00:00:00"}}
        there = {"phrases": [{"phrase": "push it", "count": 3,
                              "learned_at": "2026-09-20T00:00:00"}]}
        self.assertEqual(len(merge_phrases(here, there)["phrases"]), 1)

    def test_store_round_trip_and_forget_is_remembered(self):
        import phrase_learning
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        s = phrase_learning.PhraseStore("a@b.c", directory=d)
        s.replace_with({"phrases": [{"phrase": "lead finder", "count": 4,
                                     "learned_at": "2026-09-01"}]})
        self.assertEqual(s.phrase_texts(), ["lead finder"])
        s.forget("lead finder")
        snap = s.snapshot()
        self.assertEqual(snap["phrases"], [])
        self.assertIn("lead finder", snap["forgotten"])


class HistoryIdentityTests(unittest.TestCase):

    def test_rows_already_in_the_cloud_are_not_uploaded_again(self):
        local = [{"transcribed_text": "a", "created_at": "2026-09-29T10:00:00.123456+00:00"},
                 {"transcribed_text": "b", "created_at": "2026-09-29T10:01:00+00:00"}]
        remote = [{"transcribed_text": "a", "created_at": "2026-09-29T10:00:00.123456+00:00"}]
        self.assertEqual([r["transcribed_text"] for r in missing_from_cloud(local, remote)],
                         ["b"])

    def test_old_builds_two_timestamps_still_match(self):
        local = [{"transcribed_text": "a", "created_at": "2026-09-29T10:00:00+00:00"}]
        remote = [{"transcribed_text": "a", "created_at": "2026-09-29T10:00:04+00:00"}]
        self.assertEqual(missing_from_cloud(local, remote), [])

    def test_recording_names_ignore_how_the_time_was_written(self):
        k = audio_store.canonical_key
        self.assertEqual(k("2026-09-29T18:23:47.843200+00:00"),
                         k("2026-09-29T18:23:47.8432+00:00"))
        self.assertEqual(k("2026-09-29T18:23:47+00:00"), k("2026-09-29T18:23:47Z"))
        self.assertEqual(k("2026-09-29T19:23:47+01:00"), k("2026-09-29T18:23:47+00:00"))


class PersistHistoryTests(TempHistory):

    def test_cloud_rows_are_written_for_this_account_once(self):
        log = _logger(sync=True)
        log.log_transcription("mine here", created_at="2026-09-29T09:00:00+00:00")
        rows = [{"transcribed_text": "from old pc", "created_at": "2026-09-28T09:00:00+00:00",
                 "app_name": "Outlook"},
                {"transcribed_text": "mine here", "created_at": "2026-09-29T09:00:00+00:00"}]
        self.assertEqual(log.persist_history_rows(rows), 1)
        self.assertEqual(log.persist_history_rows(rows), 0)
        saved = self.read()
        self.assertEqual([r["transcribed_text"] for r in saved],
                         ["mine here", "from old pc"])
        self.assertTrue(all(r["user_id"] == "user-a" for r in saved))

    def test_a_row_deleted_here_is_not_brought_back(self):
        log = _logger(sync=True)
        item = {"transcribed_text": "gone", "created_at": "2026-09-28T09:00:00+00:00"}
        log.delete_transcription(item)
        self.assertEqual(log.persist_history_rows([item]), 0)


# ── The sync run and delete-my-data ──────────────────────────────────────────

class _Q:
    def __init__(self, client, table):
        self.c, self.t, self.op = client, table, "select"

    def delete(self):
        self.op = "delete"
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        if self.op == "delete":
            self.c.deleted.append(self.t)
            if self.t not in self.c.refuse:
                self.c.rows[self.t] = []
        return types.SimpleNamespace(data=list(self.c.rows.get(self.t, [])))


class _Bucket:
    def __init__(self, c):
        self.c = c

    def list(self, _path, _opts=None):
        return [{"name": n} for n in self.c.objects]

    def remove(self, names):
        for n in names:
            self.c.objects.discard(n.split("/", 1)[1])


class _FakeClient:
    def __init__(self, refuse=()):
        self.deleted, self.refuse = [], set(refuse)
        self.rows = {t: [{"user_id": "user-a"}] for t in
                     ("transcriptions", "user_vocabulary", "user_snippets",
                      "echo_user_state", "user_daily_stats")}
        self.objects = {"20260929100000000000.wav"}
        self.storage = types.SimpleNamespace(from_=lambda _b: _Bucket(self))

    def table(self, t):
        return _Q(self, t)


class DeleteCloudDataTests(unittest.TestCase):

    def test_deletes_every_personal_part_and_the_recordings(self):
        client = _FakeClient()
        log = _logger(sync=False)
        log._client = client
        result = log.delete_cloud_data()
        self.assertTrue(all(result.values()), result)
        self.assertEqual(client.objects, set())
        self.assertEqual(set(client.deleted),
                         {"transcriptions", "user_vocabulary", "user_snippets",
                          "echo_user_state"})

    def test_a_refused_delete_is_reported_not_claimed(self):
        client = _FakeClient(refuse=("transcriptions",))
        log = _logger(sync=False)
        log._client = client
        result = log.delete_cloud_data()
        self.assertFalse(result["history"])
        self.assertTrue(result["vocabulary"])

    def test_turning_sync_off_is_not_turned_back_on_by_deleting(self):
        log = _logger(sync=False)
        log._client = _FakeClient()
        log.delete_cloud_data()
        self.assertFalse(log.sync_enabled)


class _FakeDb:
    def __init__(self, active=True):
        self.active = active
        self.sync = False
        self.state = {}
        self.pushed = {}
        self.uploaded_rows = []
        self.persisted = []
        self.audio_up, self.audio_down = [], []
        self.remote_audio = {audio_store.canonical_key("2026-09-28T09:00:00+00:00")}
        self.local = [{"transcribed_text": "laptop row",
                       "created_at": "2026-09-29T09:00:00+00:00"},
                      {"transcribed_text": "old pc row",
                       "created_at": "2026-09-28T09:00:00+00:00"}]

    def set_sync_enabled(self, on):
        self.sync = on

    @property
    def sync_active(self):
        return self.active and self.sync

    def fetch_state(self, key):
        return self.state.get(key), True

    def push_state(self, key, data):
        self.pushed[key] = data
        return True

    def remote_history_index(self):
        return [{"transcribed_text": "old pc row",
                 "created_at": "2026-09-28T09:00:00+00:00"}]

    def owned_local_history(self, limit=200):
        return self.local

    def upload_history_rows(self, rows):
        self.uploaded_rows.extend(rows)
        return len(rows)

    def fetch_remote_history_rows(self, limit=200):
        return [{"transcribed_text": "old pc row", "created_at": "2026-09-28T09:00:00+00:00"}]

    def persist_history_rows(self, rows):
        self.persisted.extend(rows)
        return len(rows)

    def list_synced_audio(self):
        return set(self.remote_audio)

    def upload_audio(self, key, path):
        self.audio_up.append(key)
        return True

    def download_audio(self, key, dest):
        self.audio_down.append(key)
        return True


class SyncRunTests(unittest.TestCase):

    def _sync(self, db, cfg=None, store=None):
        applied, statuses = {}, []
        cfg = cfg or types.SimpleNamespace(cloud_sync=True, sync_stamps={},
                                           save_async=lambda: None,
                                           auto_lists=True, sound_feedback=True)
        cs = cloud_sync.CloudSync(
            db, None, cfg, phrase_store=lambda: store,
            apply_setting=lambda k, v: applied.__setitem__(k, v),
            on_status=lambda t, k: statuses.append((t, k)))
        return cs, applied, statuses

    def test_a_full_sync_moves_every_part(self):
        db = _FakeDb()
        db.state["settings"] = {"values": {"sound_feedback": False}, "stamps": {}}
        cs, applied, statuses = self._sync(db)
        db.set_sync_enabled(True)
        laptop_clip = audio_store.canonical_key("2026-09-29T09:00:00+00:00")
        with mock.patch.object(audio_store, "find",
                               lambda c: "x.wav" if c.startswith("2026-09-29") else None), \
                mock.patch.object(audio_store, "prune", lambda: None):
            cs._full_sync()
        self.assertEqual(applied, {"sound_feedback": False})
        self.assertEqual(db.pushed["settings"]["values"]["sound_feedback"], False)
        self.assertEqual([r["transcribed_text"] for r in db.uploaded_rows], ["laptop row"])
        self.assertEqual(len(db.persisted), 1)
        self.assertEqual(db.audio_up, [laptop_clip])
        self.assertEqual(db.audio_down,
                         [audio_store.canonical_key("2026-09-28T09:00:00+00:00")])
        self.assertEqual(statuses[-1][1], "ok")

    def test_nothing_happens_while_it_is_off(self):
        db = _FakeDb()
        cfg = types.SimpleNamespace(cloud_sync=False, sync_stamps={},
                                    save_async=lambda: None)
        cs, applied, statuses = self._sync(db, cfg)
        cs._full_sync()
        self.assertEqual((db.pushed, db.uploaded_rows, db.audio_up), ({}, [], []))
        self.assertEqual(statuses[-1][1], "off")

    def test_signed_out_says_so_and_does_nothing(self):
        db = _FakeDb(active=False)
        cs, applied, statuses = self._sync(db)
        cs._full_sync()
        self.assertEqual(db.pushed, {})
        self.assertEqual(statuses[-1][1], "signed_out")

    def test_a_clip_is_uploaded_only_when_on(self):
        db = _FakeDb()
        cs, _a, _s = self._sync(db)
        db.set_sync_enabled(False)
        with mock.patch.object(cloud_sync.threading, "Thread",
                               side_effect=AssertionError("spawned")):
            cs._config.cloud_sync = False
            cs.upload_clip("2026-09-29T09:00:00+00:00")


class SettingsCopyTests(unittest.TestCase):

    def test_the_card_line_is_one_short_sentence(self):
        from app_window import AppWindow
        self.assertLessEqual(len(AppWindow._CLOUD_SYNC_DESC), 90)
        self.assertIn("recordings", AppWindow._CLOUD_SYNC_DESC)


if __name__ == "__main__":
    unittest.main()
