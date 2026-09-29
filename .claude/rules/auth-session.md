---
paths: ["auth.py", "login_window.py", "supabase_client.py"]
---
# Auth and session

Full history: docs/decisions/auth-signin.md

- Auth uses the shared FTC Supabase project. Legacy URLs in `_LEGACY_SUPABASE_URLS` are migrated on next launch.
- Sign-in and session restore must survive a slow or absent network at boot. Restore failures must be visible.
- A returning user with a saved session sees the "Signing you in" splash, never the login form.
- History is per account with soft deletes. Never run an unfiltered remote query.
- `_main()` must NEVER call `auth.try_restore_session()` synchronously — `set_session()` refreshes the usually-expired token over the network and blocks first paint; `_session_restore_retry_loop` in AppWindow is the startup restore path
