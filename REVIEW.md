# REVIEW.md: BrightLink Echo

## What failure looks like

- **Tests fail.** Run `python -m unittest discover -s tests` (Windows, venv active). ~1,343 tests; three pre-existing failures are documented in `docs/INSTALLER_MIGRATION_BRIEF.md`.
- **Security gate fails.** Semgrep (ERROR-severity findings the PR adds vs. base), gitleaks (secrets in new commits), osv-scanner (new CVSS 7.0+ dependency). See `.github/workflows/security.yml`.
- **A release invariant breaks.** Wrong asset names, version fields out of sync, unsigned exe, half-written exe during update. These have all shipped as bugs before.
- **Dictation regresses.** Stutter returns, hallucinations come back, first or last words go missing, homophone fixes over-correct. Every invariant encodes a shipped defect; read `.claude/rules/` for the one you are near.
- **UI glitches.** Scroll tearing, page-change flashes, DPI-rescaling black patches, sign-in-to-dashboard flash. Guarded by `tests/test_scroll_guard.py`, `tests/test_page_change_guard.py` and `tools/*_check.py`.
- **Something crashes silently.** Memory guard, speech health and AV block recovery must all stay visible; a swallowed exception in any of them is a finding.

## Highest-risk paths (review these first)

- `app.py` (`APP_VERSION`), `version_info.txt`: version sync gates releases
- `updater.py`, `app_install.py`, `pyi_runtime.py`, `installer/activate.ps1`: update integrity
- `brand.py`, `data_paths.py`: naming and folder invariants (break ⇒ stranded clients)
- `asr_engine.py`, `transcriber.py`, `hallucination.py`, `disfluency.py`, `stream_session.py`: transcription
- `injector.py`, `app.py` (Live Typing blocks): clipboard, focus, injection
- `popup.py`, `app_window.py`, `ui_render.py`: UI painting and DPI
- `recorder.py`, `feedback.py`: audio capture and cues (the beep is final)
- `auth.py`, `login_window.py`: sign-in and session restore
- `.github/workflows/build-release.yml`, `echo.spec`: CI release pipeline
- `constraints.txt`: removing `-c constraints.txt` from CI lets unreviewed packages ship

## Paths to skip

`assets/`, `assets/brand/`, `assets/brand_icons/`, `*.png`, `*.ico`, `refine_debug.log`, `installer/single_instance.isi`, `docs/` (review if relevant but don't nitpick).

Never skip lockfiles, `.claude/`, `.claude-flow/`, or key and secret files (`*.key`, `*.secret`, `*credentials*`, `.env*`). Read them: a key or secret file in a diff is a finding.

## Evidence rules

- Every finding cites file:line, never a guess from a name.
- Tag every finding **Important**, **Nit** or **Pre-existing**.
- The summary starts with a count: "3 findings (2 Important, 1 Nit)" or "Nothing to fix."
- Nits cap at 3, labelled Nit.

## Nits (max 3, house style)

- Nit: British English, colons and full stops, no em dashes, "-ise" not "-ize", single spaces.
- Nit: Settings card descriptions are one short line saying what ON means.
- Nit: Release commits are `Release vX.Y.Z` (one line); feature commits start `Echo X.Y.Z:`.

## Recurring mistakes

1. Hard-coding a product name outside `brand.py`. The next rename must be a one-line change. [CLAUDE.md §D]
2. Copying the developer's `config.json` into the bundled config. `echo.spec` must generate from `Config` defaults, shipping the dev's machine state once broke every new install's mic. [.claude/rules/updater-release.md]
3. `APP_VERSION` and `version_info.txt` out of sync. All four version fields must match before every build. [CLAUDE.md §G, .claude/rules/updater-release.md]
4. Removing `-c constraints.txt` from CI. An unreviewed onnxruntime upgrade once broke the app on the previous build's binary layer. [CLAUDE.md §D, constraints.txt]
5. Using `DETACHED_PROCESS` in the updater swap script. Conflicts with `CREATE_NO_WINDOW`, silently broke every in-app update ≤ v1.6.3. [.claude/rules/updater-release.md, git]
6. Sending Ctrl+V after `_clipboard_set` reported failure. Pastes stale clipboard content (possibly a password). [.claude/rules/injection.md]
7. Calling tkinter widgets from a background thread directly. Always `root.after(0, ...)`. [.claude/rules/popup-and-ui.md]
8. Removing or loosening the release tail in `Recorder.stop()`. Re-opens "the last few words go missing." [.claude/rules/audio-capture.md, git: 115eda4]

## Review rounds

- Max 3 author/reviewer rounds.
- After round 1, re-review only the new diff.
- After round 3, stop and hand to Ryan with open items listed.
