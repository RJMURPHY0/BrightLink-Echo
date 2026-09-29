"""
Cloud Sync — everything Echo knows about one person, on every PC they sign in
to. Opt-in (Settings > Account), OFF by default on every PC.

Asked for 2026-09-29: "off by default, but you have the option to store all of
your stuff over the cloud so moving between devices is easier; opt in and opt
out". Before v1.7.4 part of this (history text, vocabulary, snippets, impact
figures) was uploaded for every signed-in user with no switch at all; now
NOTHING the user said, typed or recorded leaves the PC unless this is on, and
turning it off offers to delete what is already in the cloud.

What syncs (everything personal), and how each part merges:

  * History text        transcriptions table. Local rows the cloud lacks are
                        uploaded; the newest 200 cloud rows are written into
                        history.json. Identity is (created_at, text), with the
                        same 10 s tolerance the History merge uses for rows
                        from builds that minted two timestamps.
  * Recordings          private bucket echo-sync-audio/<user>/<key>.wav, key =
                        audio_store.canonical_key(created_at). Each new
                        dictation's clip is uploaded as it finishes; a full
                        sync uploads what is missing and downloads the clips
                        of history rows this PC does not have.
  * Vocabulary/snippets user_vocabulary / user_snippets (existing merge,
                        last-write-wins per entry with soft deletes).
  * Settings           echo_user_state row "settings": per-setting value and
                        the time it was last changed. Newer change wins; a
                        setting nobody has changed on either side keeps the
                        chosen (non-default) value over the default. Only
                        preferences sync — never the mic, hotkeys, popup
                        position or anything else that belongs to one machine.
  * Learned phrases     echo_user_state row "phrases": counts merge by max,
                        a phrase forgotten on any PC stays forgotten unless it
                        was learned again after that.

NOT part of Cloud Sync, by decision (2026-09-29): the daily usage figures in
user_daily_stats (word counts, seconds spoken, refines — never what was said).
BrightLink's Home dashboards read them for every signed-in user, so they keep
flowing whatever this switch says, and "delete my data" leaves them alone.
Diagnostics (error_events) likewise stay on, but drop any text sample unless
Cloud Sync is on.

Every network step is best-effort and runs on a background thread. A missing
table or bucket, an outage, or a refused write costs a partial sync and a
status line, never a dictation.
"""

import datetime
import threading
import time
from typing import Callable, Optional

# Preferences that follow the user between PCs. Deliberately NOT here:
# input_device / sample_rate / warm_mic (this PC's hardware), hotkeys (one
# keyboard's layout), popup_height/offset/align (one monitor's geometry),
# start_with_windows / auto_update (this install), engine and model choices
# (each triggers a download), API keys and anything secret.
SYNCED_SETTINGS = (
    "auto_punctuate", "end_punctuation", "spoken_punctuation",
    "live_captions", "live_inject", "homophone_fix", "auto_lists",
    "email_format", "auto_paragraphs", "show_popup", "show_pill_arrows",
    "badge_dismiss_on_key", "hide_popup_in_screenshots", "impact_range",
    "trailing_space", "auto_enter", "copy_to_clipboard", "sound_feedback",
    "vocab_fuzzy", "learned_phrases", "managed_vocab",
)

PERIODIC_SECONDS = 15 * 60
_HISTORY_DOWN = 200
_TIME_TOLERANCE_S = 10
_MAX_FORGOTTEN = 600


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── Pure merge rules (unit-tested) ───────────────────────────────────────────

def merge_settings(local_values: dict, local_stamps: dict, remote: Optional[dict],
                   defaults: dict):
    """Merge this PC's synced settings with the cloud copy.

    Returns (merged_values, merged_stamps, apply_here) where apply_here is the
    subset of merged_values this PC must adopt. Per setting: the newer change
    wins; with no stamp on either side (nobody changed it since Cloud Sync
    existed) a chosen value beats the default, and otherwise this PC keeps its
    own. ISO timestamps from the same clock format compare as strings."""
    remote = remote if isinstance(remote, dict) else {}
    r_vals = remote.get("values") if isinstance(remote.get("values"), dict) else {}
    r_stamps = remote.get("stamps") if isinstance(remote.get("stamps"), dict) else {}
    values, stamps, apply_here = {}, {}, {}
    for key in SYNCED_SETTINGS:
        has_l, has_r = key in local_values, key in r_vals
        lv, rv = local_values.get(key), r_vals.get(key)
        ls, rs = str(local_stamps.get(key) or ""), str(r_stamps.get(key) or "")
        if not has_r:
            winner = "local"
        elif not has_l:
            winner = "remote"
        elif ls or rs:
            winner = "remote" if rs > ls else "local"
        else:
            d = defaults.get(key)
            winner = "remote" if (lv == d and rv != d) else "local"
        if winner == "remote":
            values[key], stamps[key] = rv, rs
            if not has_l or rv != lv:
                apply_here[key] = rv
        elif has_l:
            values[key], stamps[key] = lv, ls
    return values, stamps, apply_here


def merge_phrases(local: Optional[dict], remote: Optional[dict]) -> dict:
    """Merge two learned-phrase snapshots (PhraseStore.snapshot shape)."""
    local = local if isinstance(local, dict) else {}
    remote = remote if isinstance(remote, dict) else {}

    forgotten = {}
    for src in (local, remote):
        for norm, at in (src.get("forgotten") or {}).items():
            if str(at) > forgotten.get(norm, ""):
                forgotten[norm] = str(at)

    phrases = {}
    for src in (local, remote):
        for row in src.get("phrases") or []:
            if not isinstance(row, dict) or not row.get("phrase"):
                continue
            norm = " ".join(row["phrase"].split()).lower()
            cur = phrases.get(norm)
            count = int(row.get("count") or 0)
            learned = str(row.get("learned_at") or "")
            if cur is None:
                phrases[norm] = {"phrase": " ".join(row["phrase"].split()),
                                 "count": count, "learned_at": learned}
            else:
                cur["count"] = max(cur["count"], count)
                if learned and (not cur["learned_at"] or learned < cur["learned_at"]):
                    cur["learned_at"] = learned
    for norm in list(phrases):
        gone = forgotten.get(norm)
        # A phrase learned again AFTER it was forgotten is wanted again.
        if gone and not (phrases[norm]["learned_at"] > gone):
            phrases.pop(norm)

    candidates = {}
    for src in (local, remote):
        for norm, row in (src.get("candidates") or {}).items():
            try:
                n, last = int(row[0]), str(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            if norm in phrases or norm in forgotten:
                continue
            cur = candidates.get(norm)
            candidates[norm] = ([max(cur[0], n), max(cur[1], last)]
                                if cur else [n, last])

    fumbled = {}
    for src in (local, remote):
        for code, n in (src.get("fumbled") or {}).items():
            try:
                fumbled[str(code)] = max(fumbled.get(str(code), 0), int(n))
            except (TypeError, ValueError):
                continue

    if len(forgotten) > _MAX_FORGOTTEN:
        forgotten = dict(sorted(forgotten.items(), key=lambda kv: kv[1],
                                reverse=True)[:_MAX_FORGOTTEN])
    return {"version": local.get("version") or remote.get("version") or 1,
            "candidates": candidates, "fumbled": fumbled,
            "phrases": list(phrases.values()), "forgotten": forgotten}


def _parse(iso: str):
    try:
        dt = datetime.datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None


def missing_from_cloud(local_rows: list, remote_index: list) -> list:
    """Local rows with no cloud row of the same text within the tolerance."""
    by_text = {}
    for r in remote_index or []:
        t = _parse(r.get("created_at") or "")
        if t is not None:
            by_text.setdefault(r.get("transcribed_text") or "", []).append(t)
    out = []
    for row in local_rows or []:
        t = _parse(row.get("created_at") or "")
        if t is None or not row.get("transcribed_text"):
            continue
        times = by_text.get(row["transcribed_text"], ())
        if not any(abs((t - rt).total_seconds()) <= _TIME_TOLERANCE_S
                   for rt in times):
            out.append(row)
    return out


# ── The sync itself ──────────────────────────────────────────────────────────

class CloudSync:
    """Runs Cloud Sync for the app. All work happens on one background thread
    at a time; status goes to on_status(text, kind) where kind is one of
    "ok", "busy", "error", "off", "signed_out"."""

    def __init__(self, db, stats, config, *,
                 phrase_store: Callable = lambda: None,
                 apply_setting: Callable = lambda k, v: None,
                 sync_libraries: Callable = lambda: None,
                 on_status: Callable = lambda text, kind: None):
        self._db = db
        self._stats = stats
        self._config = config
        self._phrase_store = phrase_store
        self._apply_setting = apply_setting
        self._sync_libraries = sync_libraries
        self._on_status = on_status
        self._lock = threading.Lock()
        self._running = False
        self._again = False
        self._timer: Optional[threading.Timer] = None
        self._push_timer: Optional[threading.Timer] = None
        self.last_status = ("", "off")

    # -- state --------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._config, "cloud_sync", False))

    def _status(self, text: str, kind: str) -> None:
        self.last_status = (text, kind)
        try:
            self._on_status(text, kind)
        except Exception:
            pass

    def refresh_status(self) -> None:
        """Say where things stand without doing any work."""
        if not self.enabled:
            self._status("Off. Nothing you dictate leaves this PC.", "off")
        elif not self._db.sync_active:
            self._status("Sign in to sync with your other PCs.", "signed_out")

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """App startup / sign-in: sync now and keep syncing while on."""
        self._db.set_sync_enabled(self.enabled)
        self.refresh_status()
        if self.enabled:
            self.sync_now()
            self._arm_timer()

    def set_enabled(self, on: bool) -> None:
        """The switch in Settings changed (config already holds the value)."""
        self._db.set_sync_enabled(bool(on))
        if on:
            self.sync_now()
            self._arm_timer()
        else:
            self._cancel_timers()
            self.refresh_status()

    def stop(self) -> None:
        self._cancel_timers()

    def _arm_timer(self) -> None:
        self._cancel_timer(self._timer)
        t = threading.Timer(PERIODIC_SECONDS, self._periodic)
        t.daemon = True
        self._timer = t
        t.start()

    def _periodic(self) -> None:
        if self.enabled:
            self.sync_now()
            self._arm_timer()

    @staticmethod
    def _cancel_timer(t) -> None:
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass

    def _cancel_timers(self) -> None:
        self._cancel_timer(self._timer)
        self._cancel_timer(self._push_timer)
        self._timer = self._push_timer = None

    # -- full sync ----------------------------------------------------------

    def sync_now(self) -> None:
        """Start a full sync in the background (coalesced: a request made
        while one is running runs once more afterwards)."""
        with self._lock:
            if self._running:
                self._again = True
                return
            self._running = True
        threading.Thread(target=self._run, daemon=True, name="cloud-sync").start()

    def _run(self) -> None:
        try:
            while True:
                self._full_sync()
                with self._lock:
                    if not self._again:
                        self._running = False
                        return
                    self._again = False
        except Exception as e:
            print(f"[Sync] failed: {e}")
            with self._lock:
                self._running = False
            self._status("Couldn't sync just now. It will try again.", "error")

    def _full_sync(self) -> None:
        if not self.enabled:
            self.refresh_status()
            return
        if not self._db.sync_active:
            self.refresh_status()
            return
        self._status("Syncing…", "busy")
        steps =(("libraries", self._step_libraries),
                 ("settings", self._step_settings),
                 ("phrases", self._step_phrases),
                 ("history", self._step_history),
                 ("recordings", self._step_audio))
        failed = []
        for name, step in steps:
            if not self.enabled:
                self.refresh_status()
                return
            try:
                if step() is False:
                    failed.append(name)
            except Exception as e:
                print(f"[Sync] {name} failed (non-fatal): {e}")
                failed.append(name)
        ok = not failed
        stamp = time.strftime("%H:%M")
        if ok:
            self._status(f"On. Synced at {stamp}.", "ok")
        else:
            print(f"[Sync] incomplete: {', '.join(failed)}")
            self._status(f"On. Synced at {stamp}, but some items could not "
                         f"sync ({', '.join(failed)}).", "error")

    def _step_libraries(self):
        self._sync_libraries()
        return True

    def _step_settings(self):
        remote, ok = self._db.fetch_state("settings")
        if not ok:
            return False
        import config as config_mod
        defaults = {}
        try:
            import dataclasses
            defaults = {f.name: f.default for f in dataclasses.fields(config_mod.Config)
                        if f.name in SYNCED_SETTINGS}
        except Exception:
            pass
        local_vals = {k: getattr(self._config, k) for k in SYNCED_SETTINGS
                      if hasattr(self._config, k)}
        stamps = dict(getattr(self._config, "sync_stamps", None) or {})
        values, merged_stamps, apply_here = merge_settings(
            local_vals, stamps, remote, defaults)
        for key, value in apply_here.items():
            try:
                self._apply_setting(key, value)
            except Exception as e:
                print(f"[Sync] could not apply {key}: {e}")
        cfg_stamps = dict(getattr(self._config, "sync_stamps", None) or {})
        for key, st in merged_stamps.items():
            if st:
                cfg_stamps[key] = st
        if cfg_stamps != (getattr(self._config, "sync_stamps", None) or {}):
            self._config.sync_stamps = cfg_stamps
            try:
                self._config.save_async()
            except Exception:
                pass
        return self._db.push_state("settings",
                                   {"values": values, "stamps": merged_stamps})

    def push_settings_soon(self) -> None:
        """A synced setting changed here: push it a moment later (debounced,
        so dragging through several toggles is one write)."""
        if not self.enabled:
            return
        self._cancel_timer(self._push_timer)
        t = threading.Timer(3.0, self._push_settings)
        t.daemon = True
        self._push_timer = t
        t.start()

    def _push_settings(self) -> None:
        if not self._db.sync_active:
            return
        try:
            self._step_settings()
        except Exception as e:
            print(f"[Sync] settings push failed (non-fatal): {e}")

    def _step_phrases(self):
        store = self._phrase_store()
        if store is None:
            return True     # learning is off: nothing to carry
        remote, ok = self._db.fetch_state("phrases")
        if not ok:
            return False
        merged = merge_phrases(store.snapshot(), remote)
        store.replace_with(merged)
        return self._db.push_state("phrases", merged)

    def _step_history(self):
        index = self._db.remote_history_index()
        if index is None:
            return False
        local = self._db.owned_local_history(200)
        up = missing_from_cloud(local, index)
        if up:
            n = self._db.upload_history_rows(up)
            print(f"[Sync] history: uploaded {n} of {len(up)}")
            if n < len(up):
                return False
        rows = self._db.fetch_remote_history_rows(_HISTORY_DOWN)
        added = self._db.persist_history_rows(rows)
        if added:
            print(f"[Sync] history: {added} row(s) from your other PCs")
        return True

    def _step_audio(self):
        import audio_store
        remote = self._db.list_synced_audio()
        if remote is None:
            return False
        rows = self._db.owned_local_history(200)
        ok = True
        downloaded = 0
        for row in rows:
            created = row.get("created_at") or ""
            if not created:
                continue
            key = audio_store.canonical_key(created)
            local = audio_store.find(created)
            if local and key not in remote:
                if self._db.upload_audio(key, local):
                    remote.add(key)
                else:
                    ok = False
            elif not local and key in remote:
                if self._db.download_audio(key, audio_store.path_for(created)):
                    downloaded += 1
                else:
                    ok = False
        if downloaded:
            print(f"[Sync] recordings: {downloaded} from your other PCs")
            try:
                audio_store.prune()
            except Exception:
                pass
        return ok

    # -- per-dictation ------------------------------------------------------

    def upload_clip(self, created_at: str) -> None:
        """A dictation just finished: send its recording (background)."""
        if not self.enabled or not self._db.sync_active or not created_at:
            return

        def _go():
            import audio_store
            path = audio_store.find(created_at)
            if path:
                self._db.upload_audio(audio_store.canonical_key(created_at), path)

        threading.Thread(target=_go, daemon=True, name="sync-clip").start()

    # -- opting out ---------------------------------------------------------

    def delete_cloud_data(self, done: Callable[[bool, dict], None]) -> None:
        """Delete everything in the cloud for this account (background).
        done(all_ok, detail) is called from the worker thread."""
        def _go():
            try:
                detail = self._db.delete_cloud_data()
            except Exception as e:
                print(f"[Sync] delete failed: {e}")
                detail = {"error": False}
            all_ok = bool(detail) and all(detail.values())
            try:
                done(all_ok, detail)
            except Exception:
                pass

        threading.Thread(target=_go, daemon=True, name="sync-delete").start()
