"""
Supabase integration for BrightLink Echo.
Logs transcriptions and AI refinements. All calls are fire-and-forget
on a background thread — a Supabase outage will never block the app.
"""

import json
import brand
import data_paths
import os
import threading
import datetime
from queue import Queue, Full
from typing import Callable, Optional

# Table name in Supabase
_TABLE = "transcriptions"

_HISTORY_SELECT_SHAPES = (
    "id, transcribed_text, refined_text, created_at, app_name, app_exe",
    "transcribed_text, refined_text, created_at, app_name, app_exe",
    "transcribed_text, refined_text, created_at",
)
_CURRENT_USER = object()

# Provenance stamped on each LOCAL history record (never the remote row), so a
# feedback report can name the engine and model that produced the text.
_META_KEYS = ("engine", "model", "language", "app_version")

# Feedback reports: rows land in echo_feedback, the opt-in recording in this
# private bucket under the user's own folder (RLS: insert own, super admin reads).
_FEEDBACK_TABLE = "echo_feedback"
_FEEDBACK_BUCKET = "echo-feedback-audio"
_FEEDBACK_AUDIO_MAX = 25 * 1024 * 1024

# Cloud Sync (opt-in): settings and learned phrases as one jsonb row each,
# recordings in a private bucket under the user's own folder. Created by
# supabase/cloud_sync.sql (applied through the BrightLink repo's migrations).
_STATE_TABLE = "echo_user_state"
_SYNC_BUCKET = "echo-sync-audio"
_SYNC_AUDIO_MAX = 25 * 1024 * 1024

_local_history_lock = threading.Lock()


def _is_missing_column_error(exc, *column_names: str) -> bool:
    """True only for a confirmed Postgres/PostgREST missing-column response."""
    code = str(getattr(exc, "code", "") or "")
    parts = [str(exc), str(getattr(exc, "message", "") or "")]
    text = " ".join(parts).casefold()
    missing = (
        code in {"42703", "PGRST204"}
        or ("column" in text and (
            "does not exist" in text or "schema cache" in text
        ))
    )
    if not missing:
        return False
    return not column_names or any(name.casefold() in text for name in column_names)


def _local_history_path() -> str:
    folder = data_paths.roaming_dir()
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "history.json")


def _tombstones_path() -> str:
    return os.path.join(os.path.dirname(_local_history_path()),
                        "history-tombstones.json")


# Days a deleted transcription stays in Supabase before the actual remote
# delete happens (deletes are immediate in the UI, deferred remotely).
_TOMBSTONE_GRACE_DAYS = 30


class SupabaseLogger:
    def __init__(self, url: str, key: str):
        self._url = url
        self._key = key
        self._client = None
        self._enabled = bool(url and key)
        self._user_id: Optional[str] = None
        self._write_queue: Queue[dict] = Queue(maxsize=200)
        self._worker_started = False
        self._worker_lock = threading.Lock()
        # History is local-first: callers can paint this cache immediately while
        # a remote refresh runs. Every cache bucket is account-scoped so a slow
        # response from one sign-in can never leak into the next account.
        self._history_lock = threading.RLock()
        self._history_cache: dict[Optional[str], list] = {}
        self._history_listeners: set[Callable[[list], None]] = set()
        self._history_refreshing: set[str] = set()
        # Once a select shape succeeds, reuse it for the life of this client.
        # Legacy schemas otherwise cost two guaranteed 400 responses per click.
        self._history_select_cols: Optional[str] = None
        self._app_columns_supported: Optional[bool] = None
        # Cloud Sync (Settings > Account). OFF until the user turns it on:
        # nothing the user dictated, typed or recorded is uploaded or pulled
        # down while it is off. Before v1.8.0 this all ran for every signed-in
        # user with no switch; it is now opt-in on each PC.
        self._sync_enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def set_sync_enabled(self, on: bool) -> None:
        self._sync_enabled = bool(on)

    @property
    def sync_enabled(self) -> bool:
        """The user's Cloud Sync choice on this PC."""
        return self._sync_enabled

    @property
    def sync_active(self) -> bool:
        """Cloud Sync is on AND there is an account to sync with."""
        return bool(self._enabled and self._sync_enabled
                    and self._history_owner())

    def set_user(self, user_id: Optional[str]) -> None:
        """Set the authenticated user ID to include in all log entries."""
        self._user_id = user_id
        items = self.get_cached_history(200)
        with self._history_lock:
            listeners = tuple(self._history_listeners)
        for callback in listeners:
            try:
                callback([dict(r) for r in items])
            except Exception as exc:
                print(f"[History] Listener failed: {exc}")

    def set_client(self, client) -> None:
        """Share an already-authenticated Supabase client (bypasses RLS)."""
        self._client = client
        with self._history_lock:
            self._history_select_cols = None
            self._app_columns_supported = None

    def _get_client(self):
        if self._client is None:
            from supabase import create_client

            self._client = create_client(self._url, self._key)
        return self._client

    # ------------------------------------------------------------------
    # Public API — all fire-and-forget
    # ------------------------------------------------------------------

    def log_transcription(self, text: str, app_name: str = "",
                          app_exe: str = "", created_at: str = "",
                          meta: Optional[dict] = None) -> None:
        """Save a new transcription record (with the app it was injected into).
        The caller may mint created_at itself (app.py does, so the saved audio
        clip and the history row share one identity). `meta` (engine, model,
        language, app_version) is kept on the LOCAL record only, for feedback
        reports; the remote transcriptions row is unchanged."""
        owner = self._history_owner()
        # One timestamp is the durable local/remote identity. Previously the two
        # calls to now() differed, forcing fuzzy timestamp matching forever.
        created_at = created_at or datetime.datetime.now(
            datetime.timezone.utc).isoformat()
        record = self._append_local(
            text, app_name=app_name, app_exe=app_exe,
            created_at=created_at, user_id=owner, meta=meta,
        )
        self._remember_local_record(owner, record)
        if not self._enabled or not self._sync_enabled:
            return
        payload = {
            "transcribed_text": text,
            "created_at": created_at,
        }
        if app_name:
            payload["app_name"] = app_name
        if app_exe:
            payload["app_exe"] = app_exe
        if owner:
            payload["user_id"] = owner
        self._run(payload)

    def log_refinement(self, original: str, refined: str, mode: str,
                       app_name: str = "", app_exe: str = "") -> None:
        """Insert a refinement record (Cloud Sync only)."""
        if not self._enabled or not self._sync_enabled:
            return
        payload = {
            "transcribed_text": original,
            "refined_text": refined,
            "refinement_mode": mode,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        if app_name:
            payload["app_name"] = app_name
        if app_exe:
            payload["app_exe"] = app_exe
        owner = self._history_owner()
        if owner:
            payload["user_id"] = owner
        self._run(payload)

    def log_update_event(self, stage: str, from_version: str = "",
                         to_version: str = "", ok=None, detail: str = "") -> None:
        """Fire-and-forget: record an auto-update outcome to the update_events
        table so update success/failure can be monitored across the whole fleet
        (which devices update vs. get stuck). Best-effort — a missing table, RLS
        block, or outage is swallowed and never affects the update itself.

        stage ∈ {"download_start","download_ok","download_fail","swap_started",
                 "manual_fallback_browser","announced"}.
        """
        if not self._enabled:
            return
        payload = {
            "stage": stage,
            "from_version": from_version,
            "to_version": to_version,
            "ok": ok,
            "detail": (detail or "")[:500],
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        if self._user_id and self._user_id != "local":
            payload["user_id"] = self._user_id

        def _insert():
            try:
                self._get_client().table("update_events").insert(payload).execute()
                print(f"[Supabase] update_event: {stage} ok={ok}")
            except Exception as e:
                print(f"[Supabase] update_event log failed (non-fatal): {e}")

        threading.Thread(target=_insert, daemon=True,
                         name="supabase-update-log").start()

    def log_error_event(self, event_type: str, detail=None, app_name: str = "",
                        app_exe: str = "", window_class: str = "",
                        app_version: str = "",
                        transcription_created_at: str = "") -> None:
        """Fire-and-forget: record a client-side reliability failure to the
        error_events table — a transcription that never landed in the target
        app, a silent mic, an evidence-based mic switch, an empty result. This
        feeds the super-admin error log so failures across the fleet are
        visible instead of dying in a console nobody sees. Best-effort — a
        missing table, RLS block, or outage is swallowed.

        event_type ∈ {"inject_failed","inject_false_success","mic_silent",
                      "mic_switched","transcribe_empty","memory_pressure"}.
        detail: dict → stored as jsonb; anything else → {"message": str}.
        transcription_created_at links the event to its transcriptions row.
        """
        if not self._enabled:
            return
        payload = {
            "event_type": event_type,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        if isinstance(detail, dict):
            payload["detail"] = detail
        elif detail:
            payload["detail"] = {"message": str(detail)[:500]}
        if app_name:
            payload["app_name"] = app_name
        if app_exe:
            payload["app_exe"] = app_exe
        if window_class:
            payload["window_class"] = window_class
        if app_version:
            payload["app_version"] = app_version
        if transcription_created_at:
            payload["transcription_created_at"] = transcription_created_at
        if self._user_id and self._user_id != "local":
            payload["user_id"] = self._user_id

        def _insert():
            try:
                self._get_client().table("error_events").insert(payload).execute()
                print(f"[Supabase] error_event: {event_type}")
            except Exception as e:
                print(f"[Supabase] error_event log failed (non-fatal): {e}")

        threading.Thread(target=_insert, daemon=True,
                         name="supabase-error-log").start()

    # ------------------------------------------------------------------
    # Feedback reports (History → flag)
    # ------------------------------------------------------------------

    @property
    def can_send_feedback(self) -> bool:
        """A report needs a signed-in account: RLS only accepts your own rows."""
        return bool(self._enabled and self._user_id
                    and self._user_id != "local")

    def local_meta(self, created_at: str) -> dict:
        """Engine/model/language/app_version stamped on the LOCAL record with
        this created_at, or {} for rows from before the stamp existed (or from
        another machine). Read straight from history.json so a remote merge
        that dropped the extra keys cannot hide them."""
        if not created_at:
            return {}
        try:
            path = _local_history_path()
            with _local_history_lock:
                if not os.path.exists(path):
                    return {}
                with open(path, "r", encoding="utf-8") as f:
                    entries = json.load(f)
        except Exception:
            return {}
        for e in entries if isinstance(entries, list) else []:
            if isinstance(e, dict) and e.get("created_at") == created_at:
                return {k: e[k] for k in _META_KEYS if e.get(k)}
        return {}

    def send_feedback(self, report: dict, wav_path: Optional[str] = None,
                      on_done: Optional[Callable[[bool], None]] = None) -> None:
        """Fire-and-forget: file a transcription feedback report.

        The recording is uploaded ONLY when the caller passes wav_path, which
        it does only when the user ticked "Include the recording" on a report
        they chose to send; it is the one way dictation audio leaves the
        machine. An upload failure still files the report without audio.
        on_done(ok) is called from the worker thread with whether the ROW
        landed."""
        payload = {k: v for k, v in dict(report).items()
                   if v not in (None, "")}
        user_id = self._user_id if self.can_send_feedback else None

        def _work():
            ok = False
            try:
                if not user_id:
                    raise RuntimeError("not signed in")
                client = self._get_client()
                payload["user_id"] = user_id
                if wav_path:
                    try:
                        if os.path.getsize(wav_path) > _FEEDBACK_AUDIO_MAX:
                            raise ValueError("recording too large")
                        import uuid
                        obj = f"{user_id}/{uuid.uuid4().hex}.wav"
                        with open(wav_path, "rb") as f:
                            data = f.read()
                        client.storage.from_(_FEEDBACK_BUCKET).upload(
                            obj, data, {"content-type": "audio/wav"})
                        payload["audio_path"] = obj
                    except Exception as e:
                        print(f"[Feedback] audio upload failed "
                              f"(filing without it): {e}")
                # returning=minimal is load-bearing: the default asks PostgREST
                # to read the new row back, which needs SELECT, and only the
                # super admin has SELECT on this table, so every other user's
                # report would be refused by RLS.
                from postgrest.types import ReturnMethod
                client.table(_FEEDBACK_TABLE).insert(
                    payload, returning=ReturnMethod.minimal).execute()
                ok = True
                print("[Feedback] report sent")
            except Exception as e:
                print(f"[Feedback] send failed: {e}")
            if on_done is not None:
                try:
                    on_done(ok)
                except Exception:
                    pass

        threading.Thread(target=_work, daemon=True,
                         name="supabase-feedback").start()

    # ------------------------------------------------------------------
    # Custom vocabulary / snippets sync
    # ------------------------------------------------------------------

    _LIBRARY_TABLES = {"vocabulary": "user_vocabulary",
                       "snippets": "user_snippets"}

    def push_library(self, kind: str, entries) -> None:
        """Upsert this account's entries, tombstones included.

        Blocking (callers already run it on a background thread) and entirely
        best-effort. The local copy in config.json is the source of truth at
        dictation time, so a missing table, an RLS block or an outage costs the
        user nothing — which matters here because this project has shipped
        migrations that were never applied to the live project.
        """
        table = self._LIBRARY_TABLES.get(kind)
        if (not table or not self._enabled or not self._sync_enabled
                or not entries):
            return
        if not self._user_id or self._user_id == "local":
            return
        rows = []
        for e in entries:
            if not isinstance(e, dict) or not e.get("id"):
                continue
            row = {
                "id": e["id"],
                "user_id": self._user_id,
                "updated_at": e.get("updated_at"),
                "deleted": bool(e.get("deleted")),
            }
            if kind == "vocabulary":
                row["term"] = e.get("term") or ""
                row["sounds_like"] = list(e.get("sounds_like") or [])
            else:
                row["name"] = e.get("name") or ""
                row["trigger"] = e.get("trigger") or ""
                row["body"] = e.get("body") or ""
            rows.append(row)
        if not rows:
            return
        try:
            self._get_client().table(table).upsert(rows).execute()
            print(f"[Supabase] {table}: pushed {len(rows)} row(s)")
        except Exception as e:
            print(f"[Supabase] {table} push failed (non-fatal): {e}")

    def fetch_library(self, kind: str) -> list:
        """This account's entries from Supabase, tombstones included so a
        delete made on another machine survives the merge. [] on any failure,
        which is indistinguishable from "nothing synced yet" and is exactly
        how it should behave."""
        table = self._LIBRARY_TABLES.get(kind)
        if not table or not self._enabled or not self._sync_enabled:
            return []
        if not self._user_id or self._user_id == "local":
            return []
        try:
            rows = (self._get_client().table(table).select("*")
                    .eq("user_id", self._user_id).execute().data or [])
        except Exception as e:
            print(f"[Supabase] {table} fetch failed (non-fatal): {e}")
            return []
        out = []
        for r in rows:
            entry = {
                "id": r.get("id"),
                "updated_at": r.get("updated_at") or "",
                "deleted": bool(r.get("deleted")),
            }
            if kind == "vocabulary":
                entry["term"] = r.get("term") or ""
                entry["sounds_like"] = list(r.get("sounds_like") or [])
            else:
                entry["name"] = r.get("name") or ""
                entry["trigger"] = r.get("trigger") or ""
                entry["body"] = r.get("body") or ""
            if entry["id"]:
                out.append(entry)
        return out

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def fetch_app_setting(self, key: str) -> str:
        """Fetch a single value from the app_settings table (synchronous, 8 s timeout)."""
        if not self._enabled:
            return ""
        result: list = [""]
        def _fetch():
            try:
                r = (self._get_client()
                     .table("app_settings")
                     .select("value")
                     .eq("key", key)
                     .limit(1)
                     .execute())
                if r.data:
                    result[0] = r.data[0].get("value", "")
            except Exception as e:
                print(f"[Supabase] fetch_app_setting({key!r}) failed: {e}")
        t = threading.Thread(target=_fetch, daemon=True)
        t.start()
        t.join(timeout=8.0)
        return result[0]

    def fetch_user_display_name(self) -> str:
        """The signed-in user's name from their org membership (FTC Contacts
        shares this Supabase project, so it's the same account the CRM knows them
        by). The shared `handle_new_user` trigger writes the signup name onto
        `org_members.display_name`; `sender_name` is the CRM's outreach name and
        is the fallback. Used to sign off Email refinements. Best-effort: returns
        "" when signed out, offline, or the row/column isn't there. Called from a
        background thread, so this blocks inline. RLS scopes rows to the user."""
        if not self._enabled or not self._user_id or self._user_id == "local":
            return ""
        try:
            r = (self._get_client()
                 .table("org_members")
                 .select("display_name,sender_name")
                 .eq("user_id", self._user_id)
                 .limit(1)
                 .execute())
            if r.data:
                row = r.data[0]
                return ((row.get("display_name") or row.get("sender_name") or "")
                        .strip())
        except Exception as exc:
            print(f"[Supabase] fetch_user_display_name failed (non-fatal): {exc}")
        return ""

    def fetch_contact_vocab(self, limit: int = 500) -> list:
        """Contact and company names from the estate CRM (FTC Contacts shares
        this Supabase project) — used as speech-recognition hotwords so the
        names the user actually dictates are recognised. Best-effort: returns
        [] when signed out, offline, or the table/columns aren't there. RLS
        scopes rows to the signed-in user."""
        if not self._enabled or not self._user_id or self._user_id == "local":
            return []
        shapes = ("first_name,last_name,company",
                  "first_name,last_name,company_name",
                  "name,company",
                  "full_name,company")
        rows = []
        for cols in shapes:
            try:
                rows = (self._get_client().table("contacts").select(cols)
                        .limit(limit).execute().data or [])
                break
            except Exception as exc:
                if not _is_missing_column_error(exc):
                    return []
        terms = []
        seen = set()
        for r in rows:
            first = (r.get("first_name") or "").strip()
            last = (r.get("last_name") or "").strip()
            full = " ".join(p for p in (first, last) if p) \
                or (r.get("name") or r.get("full_name") or "").strip()
            company = (r.get("company") or r.get("company_name") or "").strip()
            for term in (full, company):
                t = " ".join(term.split())
                if len(t) >= 3 and t.lower() not in seen:
                    seen.add(t.lower())
                    terms.append(t)
        return terms[:150]

    def set_app_setting(self, key: str, value: str) -> None:
        """Fire-and-forget upsert into app_settings. RLS only grants writes to
        the super-admin account, so this is a silent no-op for everyone else."""
        if not self._enabled:
            return

        def _upsert():
            try:
                (self._get_client()
                 .table("app_settings")
                 .upsert({"key": key, "value": value})
                 .execute())
                print(f"[Supabase] app_setting saved: {key}")
            except Exception as e:
                print(f"[Supabase] set_app_setting({key!r}) failed (non-fatal): {e}")

        threading.Thread(target=_upsert, daemon=True,
                         name="app-setting-save").start()

    # ------------------------------------------------------------------
    # Local-first history cache / refresh listeners
    # ------------------------------------------------------------------

    def _history_owner(self, user_id=_CURRENT_USER) -> Optional[str]:
        value = self._user_id if user_id is _CURRENT_USER else user_id
        return value if value and value != "local" else None

    def add_history_listener(self, callback: Callable[[list], None], *,
                             replay: bool = False, limit: int = 100) -> None:
        """Subscribe to refreshed history snapshots.

        Callbacks run on the worker that changed the cache; tkinter consumers
        must marshal the snapshot through ``root.after``. ``replay`` emits the
        current local/in-memory snapshot immediately.
        """
        with self._history_lock:
            self._history_listeners.add(callback)
        if replay:
            callback(self.get_cached_history(limit))

    def remove_history_listener(self, callback: Callable[[list], None]) -> None:
        with self._history_lock:
            self._history_listeners.discard(callback)

    def get_cached_history(self, limit: int = 30) -> list:
        """Return an account-scoped local/in-memory snapshot without networking."""
        return self._cached_history_for_owner(self._history_owner(), limit)

    def _cached_history_for_owner(self, owner: Optional[str], limit: int) -> list:
        """Read disk once per account, then serve the maintained memory cache."""
        with self._history_lock:
            if owner in self._history_cache:
                return [dict(r) for r in self._history_cache[owner][:limit]]
        local = self._local_snapshot(owner, max(200, limit))
        self._store_history(owner, local, notify=False)
        return [dict(r) for r in local[:limit]]

    def fetch_history(self, limit: int = 30) -> list:
        """Return local/cached history immediately and refresh remote in flight.

        A listener receives the merged remote result. This keeps tab navigation
        independent of network latency while preserving remote-only records.
        """
        items = self.get_cached_history(limit)
        threading.Thread(target=self._purge_expired_tombstones,
                         daemon=True, name="tombstone-purge").start()
        self.refresh_history_async(limit=max(200, limit))
        return items

    def refresh_history_async(self, limit: int = 200) -> None:
        owner = self._history_owner()
        if not self._enabled or not self._sync_enabled or owner is None:
            return
        with self._history_lock:
            if owner in self._history_refreshing:
                return
            self._history_refreshing.add(owner)

        def _worker() -> None:
            try:
                self.refresh_history(limit=limit, user_id=owner)
            finally:
                with self._history_lock:
                    self._history_refreshing.discard(owner)

        threading.Thread(target=_worker, daemon=True,
                         name="history-refresh").start()

    def refresh_history(self, limit: int = 200, *, user_id=_CURRENT_USER) -> list:
        """Synchronously refresh one account; normally use ``fetch_history``."""
        owner = self._history_owner(user_id)
        if not self._enabled or not self._sync_enabled or owner is None:
            return self._cached_history_for_owner(owner, limit)

        remote, error = self._fetch_remote_history(owner, limit)
        if error is not None:
            print(f"[Supabase] Fetch history failed: {error} — keeping local cache")
            local = self._local_snapshot(owner, max(200, limit))
            with self._history_lock:
                cached = [dict(r) for r in self._history_cache.get(owner, [])]
            merged = self._merge_history(cached, local, max(200, limit))
            return [dict(r) for r in merged[:limit]]

        local = self._fetch_local(max(200, limit), user_id=owner)
        merged = self._filter_tombstoned(
            self._merge_history(remote, local, max(200, limit)), owner)
        self._store_history(owner, merged, notify=True)
        return [dict(r) for r in merged[:limit]]

    def _fetch_remote_history(self, owner: str, limit: int) -> tuple[list, object]:
        with self._history_lock:
            cached_cols = self._history_select_cols
        shapes = (cached_cols,) if cached_cols else _HISTORY_SELECT_SHAPES
        error = None
        for cols in shapes:
            try:
                q = (
                    self._get_client()
                    .table(_TABLE)
                    .select(cols)
                    .eq("user_id", owner)
                    .order("created_at", desc=True)
                    .limit(limit)
                )
                rows = q.execute().data or []
                with self._history_lock:
                    self._history_select_cols = cols
                    self._app_columns_supported = (
                        "app_name" in cols and "app_exe" in cols)
                return [dict(r) for r in rows], None
            except Exception as exc:
                error = exc
                # A connection/RLS/server failure is not schema evidence. Stop
                # instead of issuing more guaranteed-failing select shapes or
                # downgrading metadata capability for the rest of the process.
                if not _is_missing_column_error(exc):
                    return [], exc
        return [], error

    @staticmethod
    def _parse_history_time(record: dict):
        try:
            dt = datetime.datetime.fromisoformat(
                (record.get("created_at") or "").replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except Exception:
            return None

    @classmethod
    def _same_history_event(cls, left: dict, right: dict) -> bool:
        """Conservative legacy identity: exact text and exact/near timestamp.

        New rows share the exact same timestamp. The ten-second tolerance exists
        only for already-shipped builds that called ``now()`` twice; no semantic
        or nearest-neighbour guessing is performed.
        """
        if left.get("transcribed_text") != right.get("transcribed_text"):
            return False
        lraw = left.get("created_at") or ""
        rraw = right.get("created_at") or ""
        if lraw and lraw == rraw:
            return True
        lt, rt = cls._parse_history_time(left), cls._parse_history_time(right)
        return bool(lt and rt and abs((lt - rt).total_seconds()) <= 10)

    def _enrich_from_local(self, remote: list, local: Optional[list] = None) -> list:
        """Fill each missing app field from an exact local event match only."""
        rows = [dict(r) for r in remote]
        if all(r.get("app_name") and r.get("app_exe") for r in rows):
            return rows
        if local is None:
            local = self._fetch_local(200)
        for row in rows:
            need_name = not row.get("app_name")
            need_exe = not row.get("app_exe")
            if not need_name and not need_exe:
                continue
            for candidate in local:
                if not self._same_history_event(row, candidate):
                    continue
                if need_name and candidate.get("app_name"):
                    row["app_name"] = candidate["app_name"]
                    need_name = False
                if need_exe and candidate.get("app_exe"):
                    row["app_exe"] = candidate["app_exe"]
                    need_exe = False
                if not need_name and not need_exe:
                    break
        return rows

    def _merge_history(self, remote: list, local: list, limit: int) -> list:
        rows = self._enrich_from_local(remote, local)
        used_local: set[int] = set()
        for row in rows:
            for index, candidate in enumerate(local):
                if index not in used_local and self._same_history_event(row, candidate):
                    used_local.add(index)
                    break
        rows.extend(dict(row) for index, row in enumerate(local)
                    if index not in used_local)

        def _sort_key(row):
            dt = self._parse_history_time(row)
            return dt.timestamp() if dt else float("-inf")

        rows.sort(key=_sort_key, reverse=True)
        return rows[:limit]

    def _local_snapshot(self, owner: Optional[str], limit: int) -> list:
        return self._filter_tombstoned(
            self._fetch_local(limit, user_id=owner), owner)

    def _store_history(self, owner: Optional[str], items: list, *,
                       notify: bool) -> None:
        snapshot = [dict(r) for r in items]
        with self._history_lock:
            changed = self._history_cache.get(owner) != snapshot
            self._history_cache[owner] = snapshot
            listeners = tuple(self._history_listeners) if changed and notify else ()
        # Never emit an old account's slow response into the current account UI.
        if owner != self._history_owner():
            return
        for callback in listeners:
            try:
                callback([dict(r) for r in snapshot])
            except Exception as exc:
                print(f"[History] Listener failed: {exc}")

    def _publish_history(self, owner: Optional[str], items: list) -> None:
        self._store_history(
            owner, self._filter_tombstoned(items, owner), notify=True)

    def _remember_local_record(self, owner: Optional[str], record: dict) -> None:
        with self._history_lock:
            initialized = owner in self._history_cache
            cached = [dict(r) for r in self._history_cache.get(owner, [])]
        # Once primed, the cache is maintained by log/delete/clear operations;
        # adding one record should not re-read and re-parse the whole JSON file.
        local = [record] if initialized else self._local_snapshot(owner, 200)
        merged = self._merge_history(cached, local, 200)
        self._publish_history(owner, merged)

    def clear_history(self) -> bool:
        """Soft-clear: history disappears from the app immediately; the actual
        Supabase rows are deleted after a 30-day grace period (tombstone),
        so an accidental clear is recoverable server-side."""
        owner = self._history_owner()
        # Stored audio is local-only and unrecoverable server-side, so drop
        # exactly this owner's clips (a shared machine keeps other accounts').
        try:
            import audio_store
            with self._history_lock:
                rows = [dict(r) for r in self._history_cache.get(owner, [])]
            for row in rows:
                audio_store.delete_for(row.get("created_at") or "")
        except Exception:
            pass
        local_ok = self._clear_local(owner)
        now = datetime.datetime.now(datetime.timezone.utc)
        stone = {
            "all_before": now.isoformat(),
            "purge_after": (now + datetime.timedelta(
                days=_TOMBSTONE_GRACE_DAYS)).isoformat(),
        }
        if owner:
            stone["user_id"] = owner
        self._add_tombstone(stone)
        self._publish_history(owner, [])
        return local_ok or True

    def delete_transcription(self, item: dict) -> bool:
        """Soft-delete one transcription: removed from the app immediately,
        deleted from Supabase after the 30-day grace period."""
        text = item.get("transcribed_text") or ""
        created = item.get("created_at") or ""
        try:
            import audio_store
            audio_store.delete_for(created)
        except Exception:
            pass
        now = datetime.datetime.now(datetime.timezone.utc)
        stone = {
            "id": item.get("id"),
            "text": text,
            "created_at": created,
            "purge_after": (now + datetime.timedelta(
                days=_TOMBSTONE_GRACE_DAYS)).isoformat(),
        }
        owner = self._history_owner()
        if owner:
            stone["user_id"] = owner
        self._add_tombstone(stone)
        # Remove from the local history file too.
        try:
            path = _local_history_path()
            with _local_history_lock:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                    entries = [
                        e for e in entries
                        if not (
                            ((e.get("user_id") == owner) if owner
                             else not e.get("user_id"))
                            and e.get("transcribed_text") == text
                            and e.get("created_at") == created
                        )
                    ]
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(entries, f, ensure_ascii=False)
        except Exception as e:
            print(f"[LocalHistory] Delete failed: {e}")
        with self._history_lock:
            cached = [dict(row) for row in self._history_cache.get(owner, [])]
        cached = [row for row in cached
                  if not ((item.get("id") is not None
                           and row.get("id") == item.get("id"))
                          or (row.get("transcribed_text") == text
                              and row.get("created_at") == created))]
        self._publish_history(owner, cached)
        return True

    def update_transcription(self, item: dict, new_text: str) -> bool:
        """Replace one row's text (history "Retry transcription"). created_at
        is deliberately untouched — it is the row's identity and the key of
        its stored audio clip. Remote update is fire-and-forget."""
        old_text = item.get("transcribed_text") or ""
        created = item.get("created_at") or ""
        row_id = item.get("id")
        owner = self._history_owner()
        if not new_text or (new_text == old_text and not item.get("refined_text")):
            return False

        def _matches(row: dict) -> bool:
            if row_id is not None and row.get("id") == row_id:
                return True
            return (row.get("transcribed_text") == old_text
                    and row.get("created_at") == created)

        # Local file
        try:
            path = _local_history_path()
            with _local_history_lock:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        entries = json.load(f) or []
                    for e in entries:
                        same_owner = ((e.get("user_id") == owner) if owner
                                      else not e.get("user_id"))
                        if same_owner and _matches(e):
                            e["transcribed_text"] = new_text
                            e.pop("refined_text", None)
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(entries, f, ensure_ascii=False)
        except Exception as e:
            print(f"[LocalHistory] Update failed: {e}")

        # In-memory cache + listeners (UI re-renders off this publish)
        with self._history_lock:
            cached = [dict(r) for r in self._history_cache.get(owner, [])]
        for row in cached:
            if _matches(row):
                row["transcribed_text"] = new_text
                row.pop("refined_text", None)
        self._publish_history(owner, cached)

        # Remote
        if self._enabled and self._sync_enabled and owner:
            def _update():
                try:
                    q = (self._get_client().table(_TABLE)
                         .update({"transcribed_text": new_text,
                                  "refined_text": None})
                         .eq("user_id", owner))
                    if row_id is not None:
                        q = q.eq("id", row_id)
                    else:
                        q = (q.eq("created_at", created)
                              .eq("transcribed_text", old_text))
                    q.execute()
                except Exception as e:
                    print(f"[Supabase] Update failed (non-fatal): {e}")

            threading.Thread(target=_update, daemon=True,
                             name="supabase-history-update").start()
        return True

    # ── Cloud Sync: settings/phrases, history backfill, recordings ────
    #
    # Blocking, called only from cloud_sync's background thread, and every
    # one returns a failure value instead of raising: a table or bucket that
    # is missing on the live project must cost the user a partial sync, never
    # a dictation.

    def fetch_state(self, key: str):
        """(data, ok). data is None when this account has no row yet; ok is
        False when the fetch itself failed (so the caller must not overwrite
        what it cannot see)."""
        owner = self._history_owner()
        if not self.sync_active:
            return None, False
        try:
            rows = (self._get_client().table(_STATE_TABLE)
                    .select("data").eq("user_id", owner).eq("key", key)
                    .limit(1).execute().data or [])
            return (rows[0].get("data") if rows else None), True
        except Exception as e:
            print(f"[Sync] fetch {key} failed (non-fatal): {e}")
            return None, False

    def push_state(self, key: str, data: dict) -> bool:
        owner = self._history_owner()
        if not self.sync_active:
            return False
        try:
            self._get_client().table(_STATE_TABLE).upsert(
                {"user_id": owner, "key": key, "data": data,
                 "updated_at": datetime.datetime.now(
                     datetime.timezone.utc).isoformat()},
                on_conflict="user_id,key").execute()
            return True
        except Exception as e:
            print(f"[Sync] push {key} failed (non-fatal): {e}")
            return False

    def remote_history_index(self):
        """Every (created_at, text) this account has in the cloud, paged, or
        None on failure. Only the two identity columns are read."""
        owner = self._history_owner()
        if not self.sync_active:
            return None
        out, page, start = [], 1000, 0
        try:
            while True:
                rows = (self._get_client().table(_TABLE)
                        .select("created_at, transcribed_text")
                        .eq("user_id", owner)
                        .order("created_at", desc=True)
                        .range(start, start + page - 1)
                        .execute().data or [])
                out.extend(rows)
                if len(rows) < page:
                    return out
                start += page
        except Exception as e:
            print(f"[Sync] history index failed (non-fatal): {e}")
            return None

    def upload_history_rows(self, rows: list) -> int:
        """Insert local rows the cloud does not have yet. Returns how many
        landed. The same shape log_transcription sends."""
        owner = self._history_owner()
        if not self.sync_active or not rows:
            return 0
        payload = []
        for r in rows:
            p = {"transcribed_text": r.get("transcribed_text") or "",
                 "created_at": r.get("created_at"), "user_id": owner}
            if r.get("app_name") and self._app_columns_supported is not False:
                p["app_name"] = r["app_name"]
            if r.get("app_exe") and self._app_columns_supported is not False:
                p["app_exe"] = r["app_exe"]
            if p["transcribed_text"] and p["created_at"]:
                payload.append(p)
        done = 0
        for i in range(0, len(payload), 200):
            batch = payload[i:i + 200]
            try:
                self._get_client().table(_TABLE).insert(batch).execute()
                done += len(batch)
            except Exception as e:
                if _is_missing_column_error(e, "app_name", "app_exe"):
                    stripped = [{k: v for k, v in p.items()
                                 if k not in ("app_name", "app_exe")}
                                for p in batch]
                    try:
                        self._get_client().table(_TABLE).insert(stripped).execute()
                        done += len(batch)
                        continue
                    except Exception as e2:
                        e = e2
                print(f"[Sync] history upload failed (non-fatal): {e}")
                break
        return done

    def owned_local_history(self, limit: int = 200) -> list:
        """This account's rows in history.json (never untagged ones: a legacy
        row is not assigned to whoever happens to sign in)."""
        owner = self._history_owner()
        if owner is None:
            return []
        return self._local_snapshot(owner, limit)

    def fetch_remote_history_rows(self, limit: int = 200) -> list:
        owner = self._history_owner()
        if not self.sync_active:
            return []
        rows, error = self._fetch_remote_history(owner, limit)
        return [] if error is not None else rows

    def persist_history_rows(self, rows: list) -> int:
        """Write cloud rows into history.json for this account, so a new PC
        really holds the history (offline too), not only a view of it.
        Deleted (tombstoned) rows and rows already present are skipped."""
        owner = self._history_owner()
        if owner is None or not rows:
            return 0
        rows = self._filter_tombstoned([dict(r) for r in rows], owner)
        added = 0
        try:
            path = _local_history_path()
            with _local_history_lock:
                entries = []
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            entries = json.load(f) or []
                    except Exception:
                        entries = []
                mine = [e for e in entries if e.get("user_id") == owner]
                for r in rows:
                    if any(self._same_history_event(r, e) for e in mine):
                        continue
                    rec = {"transcribed_text": r.get("transcribed_text") or "",
                           "created_at": r.get("created_at") or "",
                           "app_name": r.get("app_name") or "",
                           "app_exe": r.get("app_exe") or "",
                           "user_id": owner}
                    if not rec["transcribed_text"] or not rec["created_at"]:
                        continue
                    entries.append(rec)
                    mine.append(rec)
                    added += 1
                if added:
                    entries.sort(key=lambda e: (self._parse_history_time(e)
                                                or datetime.datetime.min.replace(
                                                    tzinfo=datetime.timezone.utc)),
                                 reverse=True)
                    entries = entries[:200]
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(entries, f, ensure_ascii=False)
        except Exception as e:
            print(f"[Sync] history save failed (non-fatal): {e}")
            return 0
        if added:
            with self._history_lock:
                self._history_cache.pop(owner, None)
            self._publish_history(owner, self._local_snapshot(owner, 200))
        return added

    def list_synced_audio(self):
        """Canonical keys of this account's recordings in the cloud, or None
        on failure."""
        owner = self._history_owner()
        if not self.sync_active:
            return None
        keys, start, page = set(), 0, 1000
        try:
            bucket = self._get_client().storage.from_(_SYNC_BUCKET)
            while True:
                items = bucket.list(owner, {"limit": page, "offset": start}) or []
                for it in items:
                    name = (it.get("name") or "") if isinstance(it, dict) else ""
                    if name.endswith(".wav"):
                        keys.add(name[:-4])
                if len(items) < page:
                    return keys
                start += page
        except Exception as e:
            print(f"[Sync] audio list failed (non-fatal): {e}")
            return None

    def upload_audio(self, key: str, path: str) -> bool:
        owner = self._history_owner()
        if not self.sync_active or not key:
            return False
        try:
            if os.path.getsize(path) > _SYNC_AUDIO_MAX:
                return False
            with open(path, "rb") as f:
                data = f.read()
            self._get_client().storage.from_(_SYNC_BUCKET).upload(
                f"{owner}/{key}.wav", data,
                {"content-type": "audio/wav", "upsert": "true"})
            return True
        except Exception as e:
            print(f"[Sync] audio upload failed (non-fatal): {e}")
            return False

    def download_audio(self, key: str, dest: str) -> bool:
        owner = self._history_owner()
        if not self.sync_active or not key:
            return False
        try:
            data = self._get_client().storage.from_(_SYNC_BUCKET).download(
                f"{owner}/{key}.wav")
            if not data:
                return False
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            return True
        except Exception as e:
            print(f"[Sync] audio download failed (non-fatal): {e}")
            return False

    def _remove_audio(self, owner: str, keys) -> None:
        names = [f"{owner}/{k}.wav" for k in keys if k]
        if not names:
            return
        bucket = self._get_client().storage.from_(_SYNC_BUCKET)
        for i in range(0, len(names), 100):
            bucket.remove(names[i:i + 100])

    def _purge_synced_audio(self, owner: str, stone: dict) -> None:
        """A purged history row takes its synced recording with it."""
        try:
            import audio_store
            if stone.get("all_before"):
                cutoff = audio_store.canonical_key(stone["all_before"])
                keys = self.list_synced_audio() or set()
                self._remove_audio(owner, [k for k in keys if k <= cutoff])
            elif stone.get("created_at"):
                self._remove_audio(
                    owner, [audio_store.canonical_key(stone["created_at"])])
        except Exception as e:
            print(f"[Sync] audio purge failed (non-fatal): {e}")

    def delete_cloud_data(self) -> dict:
        """Delete everything personal Echo keeps for this account in the
        cloud: history, vocabulary, snippets, settings, learned phrases and
        synced recordings. Works whether or not Cloud Sync is on (it is how
        someone who turned it off cleans up). The daily usage counts in
        user_daily_stats are left alone on purpose: they hold no words, and
        BrightLink's Home dashboards read them. Returns {part: True/False};
        RLS refusing a delete does not raise, so each table is read back to
        confirm it is empty."""
        owner = self._history_owner()
        result = {}
        if not self._enabled or owner is None:
            return {"signed_in": False}
        client = self._get_client()
        for part, table in (("history", _TABLE),
                            ("vocabulary", "user_vocabulary"),
                            ("snippets", "user_snippets"),
                            ("settings", _STATE_TABLE)):
            try:
                client.table(table).delete().eq("user_id", owner).execute()
                left = (client.table(table).select("user_id")
                        .eq("user_id", owner).limit(1).execute().data or [])
                result[part] = not left
            except Exception as e:
                # A table that was never created holds nothing to delete.
                missing = ("does not exist" in str(e).lower()
                           or "42p01" in str(e).lower()
                           or "could not find the table" in str(e).lower())
                result[part] = missing
                if not missing:
                    print(f"[Sync] delete {table} failed: {e}")
        try:
            was = self._sync_enabled
            self._sync_enabled = True       # list/remove are sync-gated
            try:
                keys = self.list_synced_audio()
                if keys:
                    self._remove_audio(owner, keys)
                    keys = self.list_synced_audio()
                result["recordings"] = keys is not None and not keys
            finally:
                self._sync_enabled = was
        except Exception as e:
            print(f"[Sync] delete recordings failed: {e}")
            result["recordings"] = False
        return result

    # ── Tombstones (deferred remote deletes) ──────────────────────────

    def _load_tombstones(self) -> list:
        try:
            path = _tombstones_path()
            if not os.path.exists(path):
                return []
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or []
        except Exception:
            return []

    def _save_tombstones(self, stones: list) -> None:
        try:
            with open(_tombstones_path(), "w", encoding="utf-8") as f:
                json.dump(stones, f, ensure_ascii=False)
        except Exception as e:
            print(f"[Tombstones] Save failed: {e}")

    def _add_tombstone(self, stone: dict) -> None:
        with _local_history_lock:
            stones = self._load_tombstones()
            stones.append(stone)
            self._save_tombstones(stones)

    def _filter_tombstoned(self, items: list, user_id=_CURRENT_USER) -> list:
        """Hide rows the user deleted (individually or via Clear) from any
        fetched result — remote rows survive up to 30 days after deletion."""
        stones = self._load_tombstones()
        # A tombstone only hides rows for the account that created it — a
        # Clear by one person must not blank another person's history on a
        # shared machine.
        uid = self._history_owner(user_id)
        stones = [s for s in stones if s.get("user_id") == uid]
        if not stones or not items:
            return items

        def _dt(iso):
            try:
                return datetime.datetime.fromisoformat(
                    (iso or "").replace("Z", "+00:00"))
            except Exception:
                return None

        cutoffs = [_dt(s.get("all_before")) for s in stones if s.get("all_before")]
        cutoffs = [c for c in cutoffs if c]
        row_ids = {s.get("id") for s in stones if s.get("id") is not None}
        row_keys = {(s.get("text"), s.get("created_at"))
                    for s in stones if s.get("id") is None and s.get("text")}

        out = []
        for it in items:
            if it.get("id") is not None and it.get("id") in row_ids:
                continue
            if (it.get("transcribed_text"), it.get("created_at")) in row_keys:
                continue
            ts = _dt(it.get("created_at"))
            if ts and cutoffs and any(ts <= c for c in cutoffs):
                continue
            out.append(it)
        return out

    def _purge_expired_tombstones(self) -> None:
        """Execute remote deletes for tombstones past their grace period.
        Best-effort: failures keep the tombstone for the next attempt."""
        if getattr(self, "_purge_running", False):
            return
        self._purge_running = True
        try:
            now = datetime.datetime.now(datetime.timezone.utc)

            def _dt(iso):
                try:
                    return datetime.datetime.fromisoformat(
                        (iso or "").replace("Z", "+00:00"))
                except Exception:
                    return None

            stones = self._load_tombstones()
            if not stones:
                return
            keep = []
            changed = False
            for s in stones:
                pa = _dt(s.get("purge_after"))
                if pa is None or pa > now:
                    keep.append(s)
                    continue
                owner = s.get("user_id")
                if not owner:
                    changed = True  # local-only rows: nothing remote to delete
                    continue
                # Only the owning account's client can (and should) delete,
                # and only while Cloud Sync is on (off, the stone waits: the
                # row is already hidden here, and "Delete my data from the
                # cloud" removes everything at once).
                if (not self._enabled or not self._sync_enabled
                        or owner != self._user_id):
                    keep.append(s)
                    continue
                try:
                    q = self._get_client().table(_TABLE).delete().eq("user_id", owner)
                    if s.get("all_before"):
                        q = q.lte("created_at", s["all_before"])
                    elif s.get("id") is not None:
                        q = q.eq("id", s["id"])
                    else:
                        q = (q.eq("transcribed_text", s.get("text") or "")
                              .eq("created_at", s.get("created_at") or ""))
                    q.execute()
                    self._purge_synced_audio(owner, s)
                    changed = True
                    print("[Supabase] Purged tombstoned history (30-day grace elapsed).")
                except Exception as e:
                    print(f"[Supabase] Tombstone purge failed (will retry): {e}")
                    keep.append(s)
            if changed:
                with _local_history_lock:
                    self._save_tombstones(keep)
        finally:
            self._purge_running = False

    def _clear_local(self, owner: Optional[str]) -> bool:
        try:
            path = _local_history_path()
            with _local_history_lock:
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            entries = json.load(f) or []
                    except Exception:
                        entries = []
                    if owner:
                        entries = [e for e in entries
                                   if e.get("user_id") != owner]
                    else:
                        entries = [e for e in entries if e.get("user_id")]
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(entries, f, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[LocalHistory] Clear failed: {e}")
            return False

    def _append_local(self, text: str, app_name: str = "",
                      app_exe: str = "", created_at: str = "",
                      user_id=_CURRENT_USER, meta: Optional[dict] = None) -> dict:
        owner = self._history_owner(user_id)
        record = {
            "transcribed_text": text,
            "created_at": created_at or datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
            "app_name": app_name,
            "app_exe": app_exe,
        }
        for k in _META_KEYS:
            v = (meta or {}).get(k)
            if v:
                record[k] = str(v)
        if owner:
            record["user_id"] = owner
        try:
            path = _local_history_path()
            with _local_history_lock:
                entries = []
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            entries = json.load(f)
                    except Exception:
                        entries = []
                entries.insert(0, record)
                entries = entries[:200]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(entries, f, ensure_ascii=False)
        except Exception as e:
            print(f"[LocalHistory] Write failed: {e}")
        return record

    def _fetch_local(self, limit: int = 30, user_id=_CURRENT_USER) -> list:
        try:
            path = _local_history_path()
            if not os.path.exists(path):
                return []
            with _local_history_lock:
                with open(path, "r", encoding="utf-8") as f:
                    entries = json.load(f)
            # Strict account separation: authenticated users see only their own
            # tagged rows. Untagged legacy rows remain available only offline;
            # assigning them to an arbitrary account would be a privacy leak on
            # a shared Windows profile.
            owner = self._history_owner(user_id)
            if owner:
                entries = [e for e in entries if e.get("user_id") == owner]
            else:
                entries = [e for e in entries if not e.get("user_id")]
            return entries[:limit]
        except Exception as e:
            print(f"[LocalHistory] Read failed: {e}")
            return []

    def _run(self, payload: dict) -> None:
        """Queue payload for background insert without spawning unbounded threads."""
        if not self._enabled:
            return
        self._ensure_worker()
        try:
            self._write_queue.put_nowait(payload)
        except Full:
            print("[Supabase] Log queue full — dropping oldest entry")
            try:
                _ = self._write_queue.get_nowait()
            except Exception:
                pass
            try:
                self._write_queue.put_nowait(payload)
            except Exception:
                print("[Supabase] Log drop persisted — queue saturated")

    def _ensure_worker(self) -> None:
        if self._worker_started:
            return
        with self._worker_lock:
            if self._worker_started:
                return
            threading.Thread(
                target=self._worker_loop, daemon=True, name="supabase-logger"
            ).start()
            self._worker_started = True

    def _worker_loop(self) -> None:
        while True:
            payload = self._write_queue.get()
            try:
                self._insert(payload)
            finally:
                self._write_queue.task_done()

    def _insert(self, payload: dict) -> None:
        has_app_fields = "app_name" in payload or "app_exe" in payload
        with self._history_lock:
            app_columns_supported = self._app_columns_supported
        if has_app_fields and app_columns_supported is False:
            payload = {k: v for k, v in payload.items()
                       if k not in ("app_name", "app_exe")}
            has_app_fields = False
        try:
            self._get_client().table(_TABLE).insert(payload).execute()
            print(f"[Supabase] Logged: {list(payload.keys())}")
            if has_app_fields:
                with self._history_lock:
                    self._app_columns_supported = True
        except Exception as e:
            # A legacy table may lack the app columns; preserve the record when
            # the server explicitly reports that schema, but not for outages.
            stripped = {k: v for k, v in payload.items()
                        if k not in ("app_name", "app_exe")}
            # Only a confirmed legacy-schema response warrants a metadata-free
            # retry. A timeout/5xx/RLS error must not disable app fields forever.
            if (stripped != payload
                    and _is_missing_column_error(e, "app_name", "app_exe")):
                try:
                    self._get_client().table(_TABLE).insert(stripped).execute()
                    with self._history_lock:
                        self._app_columns_supported = False
                    print(f"[Supabase] Logged (no app cols): {list(stripped.keys())}")
                    return
                except Exception as e2:
                    e = e2
            print(f"[Supabase] Log failed (non-fatal): {e}")
