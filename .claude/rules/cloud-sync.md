---
paths: ["supabase_client.py", "cloud_sync.py", "stats.py", "audio_store.py", "phrase_learning.py", "vocab_store.py", "voice_training.py"]
---
# Cloud Sync

Full history: docs/decisions/cloud-sync.md

- Nothing the user said, typed or recorded may leave the PC unless `config.cloud_sync` is on. A new remote read or write of personal data must be gated on `SupabaseLogger.sync_enabled` / `sync_active` (default False), and needs a default-off test in `tests/test_cloud_sync.py`.
- `user_daily_stats` (counts only) is deliberately NOT gated: BrightLink Home reads it. Never put text in it, and "delete my data" must keep leaving it alone.
- Diagnostics may carry a text sample only when Cloud Sync is on (the app.py reporter strips `sample`/`text`/`excerpt`).
- Synced recordings are named `audio_store.canonical_key(created_at)`, never the raw digits of the timestamp string.
- Only preferences go in `cloud_sync.SYNCED_SETTINGS`: never hardware, hotkeys, popup geometry, install behaviour, engine/model or secrets.
