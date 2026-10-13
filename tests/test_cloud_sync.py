"""Cloud Sync: opt-in (default OFF) sync of everything personal between PCs.

Asked for 2026-09-29: off by default for everyone, opt in and out in
Settings, and when on it carries "pretty much everything" to the user's other
PCs; turning it off offers to delete what is in the cloud. Daily usage counts
stay outside it (BrightLink Home reads them).

The default-off tests are the ones that matter most: before v1.8.0 history
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

    session_checks = 0

    def ensure_session(self):
        self.session_checks += 1
        return True

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

    # Deleted history: nothing pending, nothing deleted elsewhere by default.
    deleted_keys = frozenset()
    removed_audio = None

    def flush_deletions(self):
        return True

    def pull_deletions(self):
        return True

    def tombstoned_audio_keys(self, keys):
        return {k for k in keys if k in self.deleted_keys}

    def remove_synced_audio(self, keys):
        self.removed_audio = set(keys)
        self.remote_audio -= set(keys)
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

    def test_a_deleted_recording_is_removed_from_the_cloud_never_downloaded(self):
        db = _FakeDb()
        db.set_sync_enabled(True)
        gone = audio_store.canonical_key("2026-09-28T09:00:00+00:00")
        db.deleted_keys = {gone}
        db.local = [r for r in db.local if r["transcribed_text"] != "old pc row"]
        cs, _a, _s = self._sync(db)
        with mock.patch.object(audio_store, "find", lambda c: None):
            self.assertTrue(cs._step_audio())
        self.assertEqual(db.removed_audio, {gone})
        self.assertEqual(db.audio_down, [])

    def test_history_pulls_other_pcs_deletes_before_uploading(self):
        db = _FakeDb()
        db.set_sync_enabled(True)
        order = []
        db.flush_deletions = lambda: order.append("flush") or True
        db.pull_deletions = lambda: order.append("pull") or True
        real_up = db.upload_history_rows
        db.upload_history_rows = lambda rows: order.append("upload") or real_up(rows)
        cs, _a, _s = self._sync(db)
        self.assertTrue(cs._step_history())
        self.assertEqual(order, ["flush", "pull", "upload"])

    def test_no_upload_when_the_deletes_could_not_be_fetched(self):
        db = _FakeDb()
        db.set_sync_enabled(True)
        db.pull_deletions = lambda: False
        cs, _a, _s = self._sync(db)
        self.assertFalse(cs._step_history())
        self.assertEqual(db.uploaded_rows, [])

    def test_a_clip_is_uploaded_only_when_on(self):
        db = _FakeDb()
        cs, _a, _s = self._sync(db)
        db.set_sync_enabled(False)
        with mock.patch.object(cloud_sync.threading, "Thread",
                               side_effect=AssertionError("spawned")):
            cs._config.cloud_sync = False
            cs.upload_clip("2026-09-29T09:00:00+00:00")


class _RecordingClient(_FakeClient):
    """A signed-in client that notes the order of auth and table calls."""

    def __init__(self, calls, refresh_error=None):
        super().__init__()
        self.calls = calls
        self.refresh_error = refresh_error
        self.auth = types.SimpleNamespace(get_session=self._get_session)

    def _get_session(self):
        self.calls.append("get_session")
        if self.refresh_error:
            raise self.refresh_error
        return types.SimpleNamespace(access_token="fresh")

    def table(self, t):
        self.calls.append(f"table:{t}")
        return super().table(t)


class _InlineThread:
    """threading.Thread stand-in that runs its target at start()."""

    def __init__(self, target=None, daemon=None, name=None, **_k):
        self._target = target

    def start(self):
        self._target()


class _FakeTimer:
    made = []

    def __init__(self, interval, fn):
        self.interval, self.fn, self.daemon = interval, fn, False
        self.cancelled = False
        _FakeTimer.made.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


class SessionRefreshTests(TempHistory):
    """After sleep the access token can be expired when the timer fires:
    every step then got a 401 (JWT expired, PGRST303) for 15 minutes."""

    def _cloud_sync(self, log):
        cfg = types.SimpleNamespace(cloud_sync=True, sync_stamps={},
                                    save_async=lambda: None)
        return cloud_sync.CloudSync(log, None, cfg)

    def test_the_session_is_refreshed_before_the_first_table_call(self):
        calls = []
        log = _logger(sync=True)
        log._client = _RecordingClient(calls)
        cs = self._cloud_sync(log)
        with mock.patch.object(audio_store, "find", lambda c: None), \
                mock.patch.object(audio_store, "prune", lambda: None), \
                mock.patch.object(cloud_sync.threading, "Timer", _FakeTimer):
            cs._full_sync()
        tables = [i for i, c in enumerate(calls) if c.startswith("table:")]
        self.assertTrue(tables, calls)
        self.assertEqual(calls[0], "get_session")
        self.assertLess(calls.index("get_session"), tables[0])

    def test_a_failed_refresh_is_logged_without_the_token_and_never_raises(self):
        calls = []
        log = _logger(sync=True)
        log._client = _RecordingClient(
            calls, refresh_error=RuntimeError("Invalid Refresh Token: Already Used"))
        with mock.patch("builtins.print") as printed:
            self.assertFalse(log.ensure_session())
        text = " ".join(str(a) for c in printed.call_args_list for a in c.args)
        self.assertIn("session refresh failed", text)
        self.assertIn("RuntimeError", text)

    def test_no_client_is_built_just_to_refresh(self):
        log = SupabaseLogger("https://x.supabase.co", "anon")
        self.assertFalse(log.ensure_session())
        self.assertIsNone(log._client)

    def test_a_clip_upload_refreshes_the_session_first(self):
        calls = []
        db = _FakeDb()
        db.set_sync_enabled(True)
        db.ensure_session = lambda: calls.append("ensure") or True
        db.upload_audio = lambda key, path: calls.append("upload") or True
        cs = self._cloud_sync(db)
        with mock.patch.object(cloud_sync.threading, "Thread", _InlineThread), \
                mock.patch.object(audio_store, "find", lambda c: "x.wav"):
            cs.upload_clip("2026-09-29T09:00:00+00:00")
        self.assertEqual(calls, ["ensure", "upload"])


class EarlyRetryTests(unittest.TestCase):

    def setUp(self):
        _FakeTimer.made = []
        for target, name, value in ((cloud_sync.threading, "Timer", _FakeTimer),
                                    (cloud_sync.threading, "Thread", _InlineThread),
                                    (audio_store, "find", lambda c: None),
                                    (audio_store, "prune", lambda: None)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.db = _FakeDb()
        self.db.set_sync_enabled(True)
        self.cs = cloud_sync.CloudSync(
            self.db, None, types.SimpleNamespace(cloud_sync=True, sync_stamps={},
                                                 save_async=lambda: None))

    def fail_recordings(self, on=True):
        self.db.list_synced_audio = (lambda: None) if on else (lambda: set())

    def test_a_failed_run_schedules_exactly_one_early_retry(self):
        self.fail_recordings()
        self.cs.sync_now()
        self.assertEqual([t.interval for t in _FakeTimer.made],
                         [cloud_sync.RETRY_SECONDS])
        # Another failure while that retry is pending adds no second one.
        self.cs.sync_now()
        self.assertEqual(len(_FakeTimer.made), 1)

    def test_a_failed_retry_waits_for_the_regular_timer(self):
        self.fail_recordings()
        self.cs.sync_now()
        _FakeTimer.made[0].fn()          # the retry fires, and fails again
        self.assertEqual(self.db.session_checks, 2)
        self.assertEqual(len(_FakeTimer.made), 1)
        # The next ordinary run that fails gets its own one retry.
        self.cs.sync_now()
        self.assertEqual(len(_FakeTimer.made), 2)

    def test_a_good_run_schedules_nothing(self):
        self.fail_recordings(False)
        self.cs.sync_now()
        self.assertEqual(_FakeTimer.made, [])

    def test_turning_sync_off_cancels_a_pending_retry(self):
        self.fail_recordings()
        self.cs.sync_now()
        self.cs._config.cloud_sync = False
        self.cs.set_enabled(False)
        self.assertTrue(_FakeTimer.made[0].cancelled)
        _FakeTimer.made[0].fn()
        self.assertEqual(self.db.session_checks, 1)


class SettingsCopyTests(unittest.TestCase):

    def test_the_card_line_is_one_short_sentence(self):
        from app_window import AppWindow
        self.assertLessEqual(len(AppWindow._CLOUD_SYNC_DESC), 90)
        self.assertIn("recordings", AppWindow._CLOUD_SYNC_DESC)


if __name__ == "__main__":
    unittest.main()
