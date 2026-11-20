# BrightLink Echo for iPhone

*Started 2026-11-19; on `main` since 2026-11-20. Status: first cut **builds and passes its tests on GitHub's macOS runners** (see "State of the build"). Not yet on a real iPhone: that needs the Apple account steps below.*

Echo on iPhone works the way the PC app does: talk, and clean text appears in whatever app you are typing in. It is a normal iPhone app plus an **Echo keyboard**. You tap the mic on the keyboard, speak, tap ✓, and the text is typed for you.

## How it works

iOS does not let keyboards use the microphone ([Apple: "Custom keyboards… have no access to the device microphone"](https://developer.apple.com/library/archive/documentation/General/Conceptual/ExtensibilityPG/CustomKeyboard.html)). Every dictation keyboard on the App Store (Wispr Flow, OpenWhispr and others) works around this the same way, and so does Echo:

1. **First tap of the day.** You tap the mic on the Echo keyboard. The keyboard opens the Echo app, which turns the microphone on and starts recording straight away. Echo shows "Tap here to go back"; you tap iOS's own **◀ App** link in the top-left corner and keep talking.
2. **The mic stays warm.** The app keeps the microphone open in the background (the orange dot) for as long as you choose (default 5 minutes after your last dictation). It keeps no audio unless you are dictating, except a 0.4 s pre-roll so your first word isn't clipped (the desktop's warm-mic design).
3. **Every tap after that is instant.** The keyboard tells the app "start" and "stop" through the shared App Group. The app turns the speech into text, runs the desktop's formatting pipeline, and the keyboard types the result.

```
Keyboard extension                 App Group container              Echo app (background audio)
  mic tap ── command.json ───────►  + Darwin "command" ping ──────►  start/stop recording
  types text ◄── state.json ◄─────  + Darwin "state" ping ◄────────  Parakeet → pipeline → result
```

**Speech engines**, as on desktop:

| | Engine | When |
|---|---|---|
| Primary | **Parakeet TDT 0.6b v2** (the PC's engine), Core ML via [FluidAudio](https://github.com/FluidInference/FluidAudio) v0.18.3, on CPU + Neural Engine | English, once the model (about 500 MB) has downloaded |
| Fallback | **Apple on-device speech** (SpeechAnalyzer on iOS 26+, SFSpeechRecognizer forced on-device before that) | Other languages, before the model downloads, or if Parakeet fails |

**Text pipeline.** `ios/EchoCore` is a Swift port of the desktop pipeline in desktop order. It covers the hallucination guard, de-stutter, filler words, pause punctuation and sentence endings, homophones, spoken symbols and tech terms, lists, email sign-offs, and vocabulary (exact and fuzzy, Double Metaphone) plus snippets. The Python test cases are ported as golden tests. The four writing styles (Formal, Casual, very casual, Excited) are applied last, deterministically and offline, so they add no delay.

**Account (optional).** This is the same shared BrightLink Supabase account, including two-step sign-in through the CRM's `/api/auth/mfa`. When signed in:

- Vocabulary and snippets sync with the PC, using desktop's merge rule (per row, newest `updated_at` wins, tombstones included).
- The sign-off name comes from `org_members`.
- AI refine goes through the BrightLink relay (`app.brightlink.io/api/whisper/ai`). **No API key ships in the app.**
- The refine prompts are generated from `ai_refiner.py`, and CI fails if they drift.
- History stays on the phone (desktop gates history upload on Cloud Sync, which is off by default).

## Getting it onto your iPhone

There is no way to install a home-made iPhone app without an Apple Developer account, and there's no way round that for an app you want to ship to the App Store. Everything else runs in GitHub Actions, so **you never need a Mac**.

### One-time setup (about an hour, plus Apple's enrolment wait)

1. **Join the Apple Developer Program** (US$99 a year; Apple sets the local price, check the enrolment page) at <https://developer.apple.com/programs/enroll/>. Enrol as an organisation for BRIGHTLINK (OS) LTD so the App Store shows the company name. That needs a D-U-N-S number (free, takes a few days) and Account Holder access.
2. **Create the identifiers** at developer.apple.com → Certificates, Identifiers & Profiles → Identifiers. The App Store Connect API can't create App Groups, so this step is done by hand.
   - App Group: `group.io.brightlink.echo`
   - App ID `io.brightlink.echo`: tick **App Groups** and assign the group above.
   - App ID `io.brightlink.echo.keyboard`: tick **App Groups** and assign the same group.
3. **Create the app record** at App Store Connect → Apps → ＋ → New App: iOS, name "BrightLink Echo", bundle ID `io.brightlink.echo`, SKU `brightlink-echo-ios`.
4. **Make an API key** at App Store Connect → Users and Access → Integrations → App Store Connect API → Team Keys → ＋, with role **Admin** (cloud signing requires Admin). Download the `.p8` file; Apple only lets you download it once. Note the **Key ID** and the **Issuer ID**.
5. **Find your Team ID** at developer.apple.com → Membership details.
6. **Add four GitHub secrets** in the repo → Settings → Secrets and variables → Actions:
   - `ASC_KEY_ID`: the Key ID
   - `ASC_ISSUER_ID`: the Issuer ID
   - `ASC_KEY_P8`: the whole contents of the `.p8` file
   - `APPLE_TEAM_ID`: the Team ID

### Each build

1. GitHub → Actions → **iOS** → Run workflow → branch `main` → tick **testflight** → Run.
2. After the run, wait 5 to 30 minutes for Apple to process the build. Then go to App Store Connect → TestFlight → Internal Testing, add yourself, and accept the email on your iPhone.
3. Install **TestFlight** from the App Store, then install Echo from it. Open Echo and follow the setup. It covers the microphone, adding the keyboard with Full Access, the model download, a practice dictation, your default style, and optional sign-in.

### Later: the App Store

The same workflow's uploads can be submitted for review from App Store Connect. Before submitting:

- A privacy policy must be live at `https://brightlink.io/privacy` (the app links there).
- Write a privacy "nutrition label": speech is processed on device; refine text goes to BrightLink only when you use it.
- Prepare screenshots.
- Add a review note explaining that the keyboard opens Echo to turn on the microphone, because keyboards can't. This is App Review guideline 4.4.1's grey area that Wispr Flow and others ship under.

## State of the build (read this first)

- **Builds and tests green (2026-11-20).** First macOS run (Xcode 26.6, Swift 6.3.3, iPhone simulator, unsigned): EchoCore 341 tests, 0 failures; the app with its embedded keyboard extension builds and its 4 tests pass.
  - Simulator only so far. A signed device build first happens on the TestFlight run, after the Apple account steps above; signing or entitlement errors would show up there.
  - Nothing has run on a real iPhone yet: microphone, keyboard Full Access, the Parakeet download and Apple speech are untested on hardware.
  - `.github/workflows/ios.yml` builds and tests on every push that touches `ios/`.
- **Desktop untouched.** Nothing outside `ios/`, `.github/workflows/ios.yml` and the docs changed, so the Windows app, its release workflow and the auto-updater are untouched. The new workflow has no shared triggers or secrets with `build-release.yml`.
- **Cost.** macOS runner minutes on a private repo bill at 10× Linux minutes. One build-and-test run is roughly 10 to 15 minutes.

## Decisions waiting for you

1. **Bundle IDs.** `io.brightlink.echo`, `io.brightlink.echo.keyboard` and `group.io.brightlink.echo` are permanent after the first upload. They are set in one place, `ios/project.yml`.
2. **Phone stats in "Your impact" on BrightLink Home.** Desktop upserts absolute per-day totals into `user_daily_stats` and merges by per-day max, which assumes one device. A phone writing the same row would overwrite the PC's numbers. The phone therefore keeps its stats locally for now. Fixing it properly needs an additive schema change, for example a `device` column in the key or a server-side increment RPC. That needs your approval because the table is shared with BrightLink Home.
3. **CLAUDE.md says "Out of scope: non-Windows platforms".** If iPhone is now in scope, that line should change. Agents read it and may refuse iOS work.
4. **Automatic return to the previous app.** Wispr Flow appears to do this. On iOS it needs private APIs, which broke in iOS 26.4 and risk App Review, so Echo points at the system ◀ link instead. Revisit only if testers find the extra tap a problem.

## Known gaps in this first cut

- **No streaming yet.** Transcription runs once you tap ✓. Parakeet on the Neural Engine handles typical dictations in well under a second. CPU-only, which iOS 27 may force in the background without the new `continued-processing.inference` entitlement (unverified), is slower on long dictations. Desktop-style incremental streaming (`stream_session.py`) is the next latency step.
- **Not ported yet:**
  - phrase learning and habit phrases
  - managed/CRM vocabulary and contacts vocabulary
  - voice isolation
  - Live Typing
  - the background AI context fix
  - full email layout (needs email-app detection, which iOS keyboards can't do reliably)
  - the "approve in the web app" two-step method (codes work)
- **The Echo keyboard is a plain typing keyboard.** It has no autocorrect, predictions, swipe typing or accent long-press. It only needs to be good enough for quick edits; dictation is the point.
- **The memory guard isn't ported.** iOS can still end a background app that uses a lot of memory. If that happens, the next mic tap simply reopens Echo.

## Files

```
ios/
  project.yml              XcodeGen spec (the .xcodeproj is generated, never committed)
  App/                     SwiftUI app: setup, home, settings, dictation, speech, account
  Keyboard/                the Echo keyboard extension
  Shared/                  compiled into both: bridge, shared settings, brand names
  EchoCore/                Swift package: the text pipeline + its tests (`swift test`)
  Tests/                   app-level unit tests
  tools/gen_refine_prompts.py   regenerates App/Cloud/RefinePrompts.swift from ai_refiner.py
.github/workflows/ios.yml  build + test on every push; TestFlight upload on request
```
