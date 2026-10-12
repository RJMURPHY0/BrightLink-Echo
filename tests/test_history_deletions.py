"""Deleted history stays deleted on every PC (issue #2).

Up to v1.8.9 a delete lived only in the deleting PC's tombstone file, which
also kept the deleted words. Another PC with Cloud Sync re-uploaded the row,
and once the 30-day purge dropped the stone the first PC downloaded it back.
Now stones go to echo_history_deletions (supabase/history_deletions.sql):
the cloud rows go at once, every PC pulls the stones and erases its copy, and
the server refuses re-uploads, including from old versions.

FakeServer below plays the SQL's part (RPCs, the BEFORE INSERT trigger, the
storage policy) with its own implementation of the match rule, so the client
is tested against the rule, not against itself.
"""

import contextlib
import datetime
import hashlib
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
from supabase_client import StoneIndex, SupabaseLogger, text_sha256

UID = "user-a"


def _t(iso):
    dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _key(iso):
    return _t(iso).astimezone(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")


# ── The server, as the migration defines it ──────────────────────────────────

class FakeServer:
    def __init__(self):
        self.rows = []          # transcriptions: {id, user_id, transcribed_text, created_at}
        self.stones = []        # echo_history_deletions
        self.objects = {}       # echo-sync-audio: "uid/key.wav" -> bytes
        self.identities = set()
        self.next_row = 1
        self.next_stone = 1
        self.rpc_calls = []

    # echo_history_row_deleted
    def deleted(self, user, created, text):
        t = _t(created)
        for s in self.stones:
            if s["user_id"] != user:
                continue
            st = _t(s["created_at"])
            if s["kind"] == "before" and st >= t:
                return True
            if (s["kind"] == "row" and abs((st - t).total_seconds()) <= 10
                    and (st == t or s["text_sha256"] == _sha(text or ""))):
                return True
        return False

    def audio_deleted(self, user, name):
        folder, _, file = name.partition("/")
        key = file[:-4] if file.endswith(".wav") else file
        if folder != user:
            return False
        for s in self.stones:
            if s["user_id"] != user:
                continue
            if s["kind"] == "row" and s["audio_key"] == key:
                return True
            if (s["kind"] == "before" and len(key) == 20 and key.isdigit()
                    and s["audio_key"] >= key):
                return True
        return False

    def insert_rows(self, user, payload):
        for p in payload if isinstance(payload, list) else [payload]:
            if self.deleted(p.get("user_id"), p["created_at"], p.get("transcribed_text")):
                continue            # BEFORE INSERT trigger returns NULL
            self.rows.append(dict(p, id=self.next_row))
            self.next_row += 1

    def add_stone(self, user, kind, created_at, sha=None, deleted_at=None):
        now = datetime.datetime.now(datetime.timezone.utc)
        if kind == "before":
            created_at = min(_t(created_at), now).isoformat()
            sha = None
        ident = (user, kind, _t(created_at), sha)
        if ident in self.identities:
            return 0
        self.identities.add(ident)
        self.stones.append({"id": self.next_stone, "user_id": user, "kind": kind,
                            "created_at": created_at, "text_sha256": sha,
                            "audio_key": _key(created_at),
                            "deleted_at": (deleted_at or now).isoformat()})
        self.next_stone += 1
        return 1

    def rpc(self, user, name, params):
        self.rpc_calls.append((name, params))
        if name == "echo_history_delete":
            if params.get("p_before"):
                self.add_stone(user, "before", params["p_before"])
            for r in params.get("p_rows") or []:
                h = (r.get("text_sha256") or "").lower()
                self.add_stone(user, "row", r["created_at"],
                               h if len(h) == 64 else None)
            self.rows = [r for r in self.rows
                         if not (r["user_id"] == user and self.deleted(
                             user, r["created_at"], r.get("transcribed_text")))]
            return {"ok": True}
        if name == "echo_history_deletions_page":
            mine = sorted((s for s in self.stones
                           if s["user_id"] == user and s["id"] > params["p_after_id"]),
                          key=lambda s: s["id"])
            return [{k: v for k, v in s.items() if k != "user_id"}
                    for s in mine[:min(params["p_limit"], 500)]]
        raise AssertionError(f"unknown rpc {name}")

    def client(self, user):
        return _Client(self, user)


class _Result:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return types.SimpleNamespace(data=self.data)


class _Table:
    def __init__(self, server, user, name):
        assert name == "transcriptions", name
        self.s, self.user, self.op = server, user, "select"
        self.filters, self.payload, self.window = {}, None, None
        self.desc = False

    def select(self, *_a, **_k):
        return self

    def insert(self, payload, **_k):
        self.op, self.payload = "insert", payload
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def order(self, _col, desc=False):
        self.desc = desc
        return self

    def range(self, a, b):
        self.window = (a, b + 1)
        return self

    def limit(self, n):
        self.window = (0, n)
        return self

    def execute(self):
        if self.op == "insert":
            self.s.insert_rows(self.user, self.payload)
            return types.SimpleNamespace(data=[])
        rows = [dict(r) for r in self.s.rows
                if all(r.get(k) == v for k, v in self.filters.items())]
        rows.sort(key=lambda r: _t(r["created_at"]), reverse=self.desc)
        if self.window:
            rows = rows[self.window[0]:self.window[1]]
        return types.SimpleNamespace(data=rows)


class _Bucket:
    def __init__(self, server, user):
        self.s, self.user = server, user

    def list(self, folder, opts=None):
        opts = opts or {}
        names = sorted(n.split("/", 1)[1] for n in self.s.objects
                       if n.startswith(folder + "/"))
        start = opts.get("offset", 0)
        return [{"name": n} for n in names[start:start + opts.get("limit", 100)]]

    def upload(self, name, data, _opts=None):
        if self.s.audio_deleted(self.user, name):
            raise RuntimeError("new row violates row-level security policy")
        self.s.objects[name] = data

    def download(self, name):
        return self.s.objects[name]

    def remove(self, names):
        for n in names:
            self.s.objects.pop(n, None)
        return []


class _Client:
    def __init__(self, server, user):
        self.s, self.user = server, user
        self.storage = types.SimpleNamespace(from_=lambda _b: _Bucket(server, user))

    def table(self, name):
        return _Table(self.s, self.user, name)

    def rpc(self, name, params):
        return _Result(self.s.rpc(self.user, name, params))


# ── One PC: its own history, stones, cursor and recordings folder ────────────

class PC:
    def __init__(self, root, name, server, sync=True):
        self.dir = os.path.join(root, name)
        os.makedirs(os.path.join(self.dir, "audio"), exist_ok=True)
        self.server = server
        self.log = SupabaseLogger("https://x.supabase.co", "anon")
        self.log._client = server.client(UID)
        self.log.set_sync_enabled(sync)
        with self.here():
            self.log.set_user(UID)
        # Tests drive flushes themselves: no background thread racing the
        # per-PC file patches.
        self.log._flush_deletions_soon = lambda: None

    @contextlib.contextmanager
    def here(self):
        hist = os.path.join(self.dir, "history.json")
        with mock.patch.object(supabase_client, "_local_history_path", lambda: hist), \
                mock.patch.object(audio_store, "audio_dir",
                                  lambda: os.path.join(self.dir, "audio")):
            yield

    def add(self, text, created_at, clip=True):
        with self.here():
            self.log._append_local(text, created_at=created_at, user_id=UID)
            if clip:
                with open(audio_store.path_for(created_at), "wb") as f:
                    f.write(b"RIFF")

    def texts(self):
        with self.here():
            return [r["transcribed_text"] for r in self.log._fetch_local(200, user_id=UID)]

    def has_clip(self, created_at):
        with self.here():
            return audio_store.find(created_at) is not None

    def stones_file(self):
        with open(os.path.join(self.dir, "history-tombstones.json"), encoding="utf-8") as f:
            return f.read()

    def sync(self):
        cs = cloud_sync.CloudSync(
            self.log, None, types.SimpleNamespace(cloud_sync=True, sync_stamps={},
                                                  save_async=lambda: None),
            on_status=lambda *_a: None)
        with self.here(), mock.patch.object(audio_store, "prune", lambda: None):
            return cs._step_history(), cs._step_audio()


X = ("meet at the dentist at four", "2026-10-01T09:00:00.123456+00:00")
Y = ("send the invoice to Jason", "2026-10-01T09:30:00.654321+00:00")


class TwoPCTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.server = FakeServer()
        self.a = PC(self.root, "a", self.server)
        self.b = PC(self.root, "b", self.server)
        # Both PCs hold X and Y, and so does the cloud.
        for pc in (self.a, self.b):
            pc.add(*X)
            pc.add(*Y)
        self.a.sync()
        self.b.sync()
        self.assertEqual(sorted(r["transcribed_text"] for r in self.server.rows),
                         sorted([X[0], Y[0]]))
        self.assertEqual(len(self.server.objects), 2)

    def _delete_x_on_a(self):
        with self.a.here():
            self.a.log.delete_transcription(
                {"transcribed_text": X[0], "created_at": X[1]})
            self.assertTrue(self.a.log.flush_deletions())

    def test_a_delete_leaves_the_cloud_at_once(self):
        self._delete_x_on_a()
        self.assertEqual([r["transcribed_text"] for r in self.server.rows], [Y[0]])
        self.assertNotIn(f"{UID}/{_key(X[1])}.wav", self.server.objects)
        self.assertEqual(self.a.texts(), [Y[0]])
        self.assertFalse(self.a.has_clip(X[1]))

    def test_the_other_pc_erases_it_and_never_uploads_it_again(self):
        self._delete_x_on_a()
        for _ in range(3):
            self.assertEqual(self.b.sync(), (True, True))
        self.assertEqual(self.b.texts(), [Y[0]])
        self.assertFalse(self.b.has_clip(X[1]))
        self.assertEqual([r["transcribed_text"] for r in self.server.rows], [Y[0]])
        self.assertNotIn(f"{UID}/{_key(X[1])}.wav", self.server.objects)

    def test_the_deleting_pc_never_gets_it_back(self):
        self._delete_x_on_a()
        self.b.sync()
        for _ in range(3):
            self.a.sync()
        self.assertEqual(self.a.texts(), [Y[0]])
        # No grace period left to expire: the stone is still there.
        self.assertIn(_sha(X[0]), self.a.stones_file())

    def test_an_old_version_cannot_resurrect_the_row_or_recording(self):
        self._delete_x_on_a()
        # v1.8.9 on B: uploads its local copy the old way.
        old = self.server.client(UID)
        old.table("transcriptions").insert(
            [{"transcribed_text": X[0], "created_at": X[1], "user_id": UID},
             {"transcribed_text": "new on old pc", "created_at": "2026-10-12T11:00:00+00:00",
              "user_id": UID}]).execute()
        # ...and the same row with the other timestamp builds before v1.8 sent.
        old.table("transcriptions").insert(
            {"transcribed_text": X[0], "created_at": "2026-10-01T09:00:04+00:00",
             "user_id": UID}).execute()
        self.assertEqual(sorted(r["transcribed_text"] for r in self.server.rows),
                         sorted([Y[0], "new on old pc"]))
        with self.assertRaises(RuntimeError):
            old.storage.from_("echo-sync-audio").upload(
                f"{UID}/{_key(X[1])}.wav", b"RIFF", {"upsert": "true"})
        self.a.sync()
        self.assertNotIn(X[0], self.a.texts())

    def test_clear_reaches_every_pc_and_keeps_later_dictations(self):
        with self.a.here():
            self.a.log.clear_history()
            self.assertTrue(self.a.log.flush_deletions())
        self.assertEqual(self.server.rows, [])
        self.assertEqual(self.server.objects, {})
        later = ("after the clear", "2099-01-01T00:00:00+00:00")
        self.b.add(*later, clip=False)
        self.b.sync()
        self.assertEqual(self.b.texts(), [later[0]])
        self.assertFalse(self.b.has_clip(X[1]))
        self.assertEqual([r["transcribed_text"] for r in self.server.rows], [later[0]])

    def test_a_retried_row_with_new_text_is_still_deleted(self):
        # Retry transcription rewrote X's text on B; the time is the identity.
        with self.b.here():
            self.b.log.update_transcription(
                {"transcribed_text": X[0], "created_at": X[1]}, "edited words")
        self._delete_x_on_a()
        self.b.sync()
        self.assertNotIn("edited words", self.b.texts())

    def test_a_delete_with_sync_off_waits_and_goes_up_when_turned_on(self):
        self.a.log.set_sync_enabled(False)
        self.server.rpc_calls.clear()
        with self.a.here():
            self.a.log.delete_transcription(
                {"transcribed_text": X[0], "created_at": X[1]})
            self.assertFalse(self.a.log.flush_deletions())
        self.assertEqual(self.server.rpc_calls, [])
        self.assertEqual(len(self.server.rows), 2)
        self.a.log.set_sync_enabled(True)
        self.a.sync()
        self.assertEqual([r["transcribed_text"] for r in self.server.rows], [Y[0]])

    def test_a_queued_flush_never_runs_on_the_next_accounts_session(self):
        import threading
        with self.a.here():
            self.a.log.clear_history()
            self.server.rpc_calls.clear()
            self.a.log._flush_lock.acquire()
            result = []
            t = threading.Thread(target=lambda: result.append(
                self.a.log.flush_deletions()))
            t.start()
            # The flush captured user-a and waits; meanwhile user-b signs in.
            self.a.log.set_user("user-b")
            self.a.log._flush_lock.release()
            t.join(5)
        self.assertEqual(result, [False])
        self.assertEqual(self.server.rpc_calls, [])
        self.assertEqual(len(self.server.rows), 2)

    def test_a_legacy_copy_with_its_own_time_loses_its_recording_too(self):
        # A build before v1.8 stamped the local row and the cloud row 4 s
        # apart; the recording was synced under the local time.
        local_t, cloud_t = "2026-09-20T08:00:00+00:00", "2026-09-20T08:00:04+00:00"
        self.a.add("legacy words", local_t)
        self.server.rows.append({"id": 99, "user_id": UID, "transcribed_text": "legacy words",
                                 "created_at": cloud_t})
        self.server.objects[f"{UID}/{_key(local_t)}.wav"] = b"RIFF"
        with self.a.here():
            # History shows the cloud copy; that is the item deleted.
            self.a.log.delete_transcription(
                {"transcribed_text": "legacy words", "created_at": cloud_t})
            self.assertTrue(self.a.log.flush_deletions())
        self.assertFalse(self.a.has_clip(local_t))
        self.assertNotIn("legacy words", self.a.texts())
        self.assertNotIn(f"{UID}/{_key(local_t)}.wav", self.server.objects)
        self.assertTrue(self.server.audio_deleted(UID, f"{UID}/{_key(local_t)}.wav"))

    def test_a_clip_whose_row_aged_out_here_is_still_erased(self):
        # B keeps recordings longer than history: X's row is gone from B's
        # history.json, its clip is not. Another account's clip stays.
        other = "2026-09-25T10:00:00.111111+00:00"
        with self.b.here():
            path = supabase_client._local_history_path()
            with open(path, encoding="utf-8") as f:
                rows = [r for r in json.load(f) if r["transcribed_text"] != X[0]]
            rows.append({"transcribed_text": "someone else", "created_at": other,
                         "user_id": "user-b"})
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f)
            with open(audio_store.path_for(other), "wb") as f:
                f.write(b"RIFF")
        self.assertTrue(self.b.has_clip(X[1]))
        with self.a.here():
            self.a.log.clear_history()
            self.assertTrue(self.a.log.flush_deletions())
        self.b.sync()
        self.assertFalse(self.b.has_clip(X[1]))
        self.assertFalse(self.b.has_clip(Y[1]))
        self.assertTrue(self.b.has_clip(other))

    def test_a_failed_send_stays_pending_and_is_retried(self):
        with self.a.here():
            self.a.log.delete_transcription(
                {"transcribed_text": X[0], "created_at": X[1]})
            real = self.server.rpc
            self.server.rpc = mock.Mock(side_effect=RuntimeError("offline"))
            self.assertFalse(self.a.log.flush_deletions())
            self.assertTrue(json.loads(self.a.stones_file())[0]["pending"])
            self.server.rpc = real
            self.assertTrue(self.a.log.flush_deletions())
            self.assertFalse(json.loads(self.a.stones_file())[0]["pending"])
        self.assertEqual(len(self.server.rows), 1)


class StoneTests(unittest.TestCase):

    def test_the_hash_matches_postgres(self):
        # encode(sha256(convert_to('dryrun row A','UTF8')),'hex') on the live
        # project began e0010a; to_char(... 'YYYYMMDDHH24MISSUS') gave this key.
        self.assertTrue(text_sha256("dryrun row A").startswith("e0010a"))
        self.assertEqual(audio_store.canonical_key("2026-10-12T10:00:00.123456+00:00"),
                         "20261012100000123456")

    def test_match_rule(self):
        idx = StoneIndex([
            {"kind": "row", "created_at": X[1], "text_sha256": _sha(X[0])},
            {"kind": "before", "created_at": "2026-09-30T12:00:00+00:00"},
        ])
        self.assertTrue(idx.hides({"transcribed_text": "other", "created_at": X[1]}))
        self.assertTrue(idx.hides({"transcribed_text": X[0],
                                   "created_at": "2026-10-01T09:00:09+00:00"}))
        self.assertFalse(idx.hides({"transcribed_text": X[0],
                                    "created_at": "2026-10-01T09:00:11+00:00"}))
        self.assertFalse(idx.hides({"transcribed_text": "other",
                                    "created_at": "2026-10-01T09:00:04+00:00"}))
        self.assertTrue(idx.hides({"transcribed_text": "old",
                                   "created_at": "2026-09-30T00:00:00Z"}))
        self.assertTrue(idx.hides_audio_key(_key(X[1])))
        self.assertTrue(idx.hides_audio_key("20260930000000000000"))
        self.assertFalse(idx.hides_audio_key("20260930130000000000"))
        self.assertFalse(idx.hides_audio_key("20261013000000000000"))
        self.assertFalse(idx.hides_audio_key("2026"))


class LocalStoneTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.server = FakeServer()
        self.pc = PC(self.root, "a", self.server, sync=False)
        self.path = os.path.join(self.pc.dir, "history-tombstones.json")

    def test_a_stone_never_holds_the_words(self):
        self.pc.add(*X)
        with self.pc.here():
            self.pc.log.delete_transcription({"transcribed_text": X[0], "created_at": X[1]})
        self.assertNotIn(X[0], self.pc.stones_file())
        self.assertNotIn("dentist", self.pc.stones_file())

    def test_old_stones_lose_their_words_and_go_up_as_pending(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([{"id": 7, "text": X[0], "created_at": X[1], "user_id": UID,
                        "purge_after": "2026-11-11T00:00:00+00:00"},
                       {"all_before": "2026-10-01T00:00:00+00:00", "user_id": UID,
                        "purge_after": "2026-10-31T00:00:00+00:00"},
                       {"text": "signed out", "created_at": "2026-10-02T00:00:00+00:00",
                        "purge_after": "2026-11-01T00:00:00+00:00"}], f)
        with self.pc.here():
            hidden = self.pc.log._filter_tombstoned(
                [{"transcribed_text": X[0], "created_at": X[1]},
                 {"transcribed_text": "kept", "created_at": "2026-10-12T12:00:00+00:00"}],
                UID)
        self.assertEqual([r["transcribed_text"] for r in hidden], ["kept"])
        saved = json.loads(self.pc.stones_file())
        self.assertNotIn(X[0], self.pc.stones_file())
        self.assertNotIn("signed out", self.pc.stones_file())
        self.assertEqual([(s["kind"], s["pending"]) for s in saved],
                         [("row", True), ("before", True), ("row", False)])
        # On the first sync they reach the server.
        self.server.rows.append({"id": 1, "user_id": UID, "transcribed_text": X[0],
                                 "created_at": X[1]})
        self.pc.log.set_sync_enabled(True)
        with self.pc.here():
            self.assertTrue(self.pc.log.flush_deletions())
        self.assertEqual(self.server.rows, [])

    def test_the_cursor_pages_and_rereads_unsettled_stones(self):
        old = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
        for i in range(1200):
            self.server.add_stone(UID, "row", (old + datetime.timedelta(seconds=30 * i)).isoformat(),
                                  _sha(f"t{i}"), deleted_at=old + datetime.timedelta(seconds=i))
        # The newest three were written moments ago.
        now = datetime.datetime.now(datetime.timezone.utc)
        for s in self.server.stones[-3:]:
            s["deleted_at"] = now.isoformat()
        self.pc.log.set_sync_enabled(True)
        with self.pc.here():
            self.assertTrue(self.pc.log.pull_deletions())
            pages = [c for c in self.server.rpc_calls
                     if c[0] == "echo_history_deletions_page"]
            self.assertEqual([p[1]["p_after_id"] for p in pages], [0, 500, 1000])
            self.assertEqual(len(json.loads(self.pc.stones_file())), 1200)
            self.assertEqual(self.pc.log._load_cursor(UID), 1197)
            self.server.rpc_calls.clear()
            self.assertTrue(self.pc.log.pull_deletions())
            self.assertEqual(self.server.rpc_calls[0][1]["p_after_id"], 1197)
            self.assertEqual(len(json.loads(self.pc.stones_file())), 1200)

    def test_the_cursor_stays_when_the_stones_could_not_be_saved(self):
        old = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
        self.server.add_stone(UID, "row", old.isoformat(), _sha("x"), deleted_at=old)
        self.server.add_stone(UID, "row", (old + datetime.timedelta(hours=1)).isoformat(),
                              _sha("y"), deleted_at=old + datetime.timedelta(hours=1))
        self.pc.log.set_sync_enabled(True)
        with self.pc.here(), mock.patch.object(self.pc.log, "_save_tombstones",
                                               return_value=False):
            self.assertFalse(self.pc.log.pull_deletions())
            self.assertEqual(self.pc.log._load_cursor(UID), 0)


if __name__ == "__main__":
    unittest.main()
