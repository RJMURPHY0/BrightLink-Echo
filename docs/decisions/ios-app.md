# iPhone app (BrightLink Echo for iOS)

Dated entries. Overview, install steps and open questions: `docs/IOS.md`.

- `2026-11-19`: **Echo for iPhone started (branch `claude/echo-ios-app-0lacuj`, first cut, not yet compiled).** Ryan asked for Echo on iPhone with Echo's full capability, set up as simply as Wispr Flow's. Decisions:
  - **Architecture follows the only shape iOS allows.** Keyboards cannot use the microphone, so the Echo keyboard drives the app. The app opens the mic in the foreground (recording can't start in the background) and keeps it warm in the background with `UIBackgroundModes: audio` for a user-chosen time (default 5 min after the last dictation). It keeps audio only while dictating, apart from a 0.4 s pre-roll.
  - **Bridge.** Keyboard and app talk through atomic JSON files in the App Group plus Darwin notifications. Every command carries an ID: the app handles each ID once, and the keyboard records consumed result IDs, so a duplicate tap or a recreated keyboard never types a result twice. A stale heartbeat (over 4 s) reads as "off".
  - **No automatic return to the previous app.** It needs private APIs (host bundle ID), which broke in iOS 26.4 and are an App Review risk. Echo points at the system ◀ link instead.
  - **Opening the app from the keyboard** uses the responder-chain `openURL:options:completionHandler:` call that shipping App Store keyboards use. The old `openURL:` selector died in iOS 18.
  - **Engines mirror desktop.** Parakeet TDT 0.6b v2 (FluidAudio 0.18.3, pinned exactly; not 0.18.4, which was released the same day) is primary for English. Apple on-device recognition is the fallback. Parakeet never uses the GPU, which is forbidden in the background, and retries CPU-only once if a background Neural Engine run is refused (iOS 27 gates it behind an entitlement).
  - **Pipeline parity.** `ios/EchoCore` ports the desktop's pure text modules with the Python tests as golden cases. Refine prompts are generated from `ai_refiner.py` (`ios/tools/gen_refine_prompts.py`), and CI fails on drift.
  - **No model API keys in the app.** AI refine uses only the BrightLink relay with the user's Supabase token.
  - **Cloud rules match desktop.** Vocabulary and snippets sync whenever signed in, using desktop's per-row newest-`updated_at` merge with tombstones. History stays on the phone (Cloud Sync is not offered on iPhone yet).
  - **The phone does not write `user_daily_stats`.** Desktop's absolute per-day upserts would overwrite each other across devices. This needs an additive schema decision first.
  - **The keyboard is a full typing keyboard** (App Review 4.4.1: it must work without Full Access). The mic key opens setup when Full Access is off.
  - **Separate CI.** `.github/workflows/ios.yml` runs on macOS runners and has no shared triggers or secrets with `build-release.yml`. TestFlight uploads use cloud-managed signing with an App Store Connect API key (Admin role), so no Mac is needed.
  - **Identifiers.** `io.brightlink.echo`, `io.brightlink.echo.keyboard`, `group.io.brightlink.echo` and URL scheme `brightlinkecho`. All are permanent after the first App Store Connect upload.
