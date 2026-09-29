# BrightLink Echo on the Microsoft Store

Scoped 2026-09-28. The code side ships in v1.7.1.

## Route: submit the signed exe (Store policy 10.2.9), not MSIX

The Store takes a plain signed `.exe` by URL. Echo is signed by BRIGHTLINK
(OS) LTD with a certificate in the Microsoft Trusted Root Program, and every
release has an immutable versioned URL. MSIX was rejected: its package
container would fight the in-place self-updater, the canonical exe at
`%LOCALAPPDATA%\FTC Whisper`, the logon task and the 660 MB model folder.

From the live policy (updated 2026-09-15):

- Self-updating is allowed. The "update only through the Store" rule (10.2.5)
  covers games and Xbox and names 10.2.9 products as exempt.
- Subscriptions may be billed through BrightLink (10.8.6).
- Company developer accounts are free.

## Done in v1.7.1

| Requirement | Policy | How |
|---|---|---|
| Silent install, no UI | 10.2.9 | `BrightLink-Echo.exe --install /S` installs the canonical copy, Start menu, Installed apps entry, URL protocol and (if enabled) the logon task, then exits. Runs before the handoff and the mutex, so it works while the app is open. Tests: `tests/test_store_install.py` |
| Consent to start at sign-in | 10.2.8 | Settings > Start with Windows (default on). Off removes the logon task. New key `start_with_windows`; the old `auto_start` key is ignored because every existing config holds `false` there |
| Privacy policy URL | 10.5.1 | `PRIVACY.md` in the repo |

## Partner Center values

- **App type**: EXE or MSI app
- **Package URL**: `https://github.com/RJMURPHY0/BrightLink-Echo/releases/download/v1.7.3/BrightLink-Echo.exe`
- **Installer parameters / silent switch**: `--install /S`
- **Architecture**: x64. **Language**: English (United Kingdom)
- **Category**: Productivity
- **Privacy policy URL**: `https://github.com/RJMURPHY0/BrightLink-Echo/blob/main/PRIVACY.md`
- **Support contact**: ryan.murphy@brightlink.io
- **Website**: https://brightlink.io
- **Pricing**: Free (billing, if any, runs through the BrightLink account)

### Short description

Hold a key, speak, and your words appear wherever you are typing.

### Description

BrightLink Echo turns your voice into text in any Windows app. Press Alt+V,
speak, and your words land where your cursor is: email, chat, documents, the
browser.

Speech recognition runs on your own computer, so it is fast, works offline
and your voice never leaves your machine.

- Punctuation, paragraphs and spoken lists laid out for you
- Custom vocabulary for names and terms the app should always get right
- Snippets: say a short phrase, insert a longer block of text
- Refine: tidy, shorten or rewrite selected text with one key (Alt+R)
- History of every dictation, with playback

Signing in is optional. With a BrightLink account your history, vocabulary
and snippets follow you between computers.

### Notes for certification

BrightLink Echo is a push-to-talk dictation app. To test: open Notepad, press
Alt+V, speak a sentence, press Alt+V again. The words are typed into Notepad.
Alt+R on selected text opens the AI Refine panel.

- First launch downloads the speech model (about 660 MB) over HTTPS from
  Hugging Face. The installer itself is standalone; only the app downloads
  the model, once.
- The app needs a microphone.
- It registers global hotkeys and uses input injection (clipboard paste and
  SendInput) because its job is to type into other apps. A keyboard hook
  observes (never blocks) key presses only to hide the confirmation badge
  when the user starts typing again.
- It updates itself from its GitHub releases, as allowed for EXE apps.
- Start with Windows is on by default and can be turned off in Settings.
- Signing in is optional. Test account: [ADD EMAIL AND PASSWORD]

## After launch

- Each release changes the package URL, but Store users self-update, so the
  Partner Center URL only affects new installs. Update it every few
  releases, or automate it in CI later.
- Point the CRM's Download button at the Store listing, so new users skip
  the SmartScreen prompt.

## Open questions (verify, not assumed)

- That a Store install shows no SmartScreen prompt. Microsoft does not
  document it for EXE apps; check on the first live install.
- Whether Partner Center accepts a GitHub release URL (it redirects to a
  CDN). If not, mirror the exe on brightlink.io at a versioned path.
- Certification and DUNS turnaround.
- Whether certifiers query the keyboard hook. The notes above explain it.
