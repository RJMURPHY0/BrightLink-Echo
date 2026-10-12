# Handoff: ship BrightLink Echo v1.8.5 (full rename + pill position fix)

(Not for committing. Delete this file once v1.8.5 is live.)

You are finishing a release of BrightLink Echo, a Windows push-to-talk dictation app (Python 3.11 + tkinter + PyInstaller, installed per-user by Inno Setup). Repo: https://github.com/RJMURPHY0/BrightLink-Echo (branch `main`). Owner: Ryan Murphy (GitHub RJMURPHY0). Read `CLAUDE.md` and `.claude/rules/updater-release.md` in the repo before touching anything.

## Goal (Ryan's words, condensed)
1. The old name "FTC Whisper" must be gone from everything a new user sees: download, installer, install folder, exe, shortcuts, Installed apps, Task Manager, startup entry, notifications, antivirus prompts (Avast etc. show the exe file name, path, description and signer), the GitHub release page.
2. The recording pill must open bottom-centre, a small fixed gap above the taskbar, on every laptop and monitor at every display scale.
3. Everything pushed to `main` and released, so auto-update and the install link both deliver it.

## Where the work is
All code is DONE and committed locally on branch `rename-everywhere`, in the worktree `C:\Users\ryan.murphy\Code\echo-identity` (on Ryan's GIGABYTE laptop). It was NOT pushed: this laptop had no working GitHub sign-in.

Commits on `rename-everywhere`, on top of `origin/main` at db6eac2 (v1.8.4):
- `fd9f62f` Ship the on-disk rename to BrightLink Echo (v1.8.5), merged with v1.8.4. Merges the old unmerged branch `identity-rename` (commit 92b8ad1, 2026-09-30). That rename was built but never merged, which is why v1.8.1 to v1.8.4 still installed to `%LOCALAPPDATA%\FTC Whisper\FTC Whisper.exe`. Also: CRM favicon cache path goes through `data_paths`; release body with a direct download link; GitHub asset labels hide the legacy file names on the release page; README install button links straight to `BrightLink-Echo.exe`; migration-e2e also upgrades from v1.8.4.
- `f80a7dc` Pill opens bottom-centre at every display scale. Root cause: `popup._dpi_scale` divided Tk's cached screen width by `GetSystemMetrics` and scaled the already-real work area by 1.5 again on the 150% laptop (pill landed 639px right of centre, on the taskbar). Removed; placement reads only `OverlayMonitor`; gaps scale with the monitor; default `popup_offset` 30 -> 8, configs still on exactly 30 migrate to 8. Decision logged in `docs/decisions/popup-pill.md`.

If you cannot reach that worktree (e.g. you run in the cloud), Ryan must first push it from the laptop: in `C:\Users\ryan.murphy\Code\echo-identity` run `git push -u origin rename-everywhere` with the real Git for Windows (`C:\Program Files\Git`), which signs in through Git Credential Manager. Do NOT use `~\.hermes\tools\git-*`, which has no credential helper.

## Steps
1. **Push** `rename-everywhere` (never force-push, never push `main` yet).
2. **Dry-run build**: Actions -> "Build and publish Windows installer" -> Run workflow on `rename-everywhere`, `publish` unticked. It builds, signs, installs and self-tests, and keeps the files as an artifact. If signing is skipped because the `release` environment only allows `main`/`v*`, say so; the migration test needs signed files, so in that case go to step 4 with extra care (or temporarily allow the branch in the environment rule, with Ryan's OK).
3. **Migration test**: Actions -> "Installer migration scenarios" -> Run workflow with `build_run_id` = the dry run's run id. Defaults upgrade from 1.7.2, 1.6.86, 1.6.79 (onefile) and 1.8.0, 1.8.4 (installed layout). Every job must pass: after the update the machine runs from `%LOCALAPPDATA%\BrightLink Echo\BrightLink Echo.exe`, the model, sign-in and history moved, and nothing is left under the legacy names. Fix any failure before going on.
4. **Release**: merge `rename-everywhere` into `main` (fast-forward or merge commit, no rebase of published history). Bump the version to **1.8.5**: `APP_VERSION = "1.8.5"` in `app.py`, and all four fields in `version_info.txt` (`filevers=(1, 8, 5, 0)`, `prodvers=(1, 8, 5, 0)`, `FileVersion '1.8.5.0'`, `ProductVersion '1.8.5.0'`). Commit and push `main`. CI publishes the release on the version bump (check first that no v1.8.5 release exists; tags must be strictly higher than v1.8.4).
5. **Verify the live release** (https://github.com/RJMURPHY0/BrightLink-Echo/releases/latest):
   - six assets: `FTC-Whisper.exe`, `BrightLink-Echo-Setup.exe`, `FTC-Whisper-Setup.exe`, `BrightLink-Echo.exe`, `BrightLink-Echo-rollout.json`, `FTC-Whisper-rollout.json`. The `FTC-*` names are FROZEN forever: older installed copies download them by exact name. Never rename or delete them.
   - the "Label the release assets" step ran, and the release page shows "BrightLink Echo for Windows (install this)" and "Auto-update file N (installed copies only)" instead of the FTC file names. Verify this on the actual page: labels hiding file names is expected but unproven.
   - the body shows the download link; https://github.com/RJMURPHY0/BrightLink-Echo/releases/latest/download/BrightLink-Echo.exe downloads the new installer.
6. **Real install check on Ryan's laptop** (Ryan has v1.8.4 installed): let it auto-update or run the download link. Confirm `%LOCALAPPDATA%\BrightLink Echo\BrightLink Echo.exe` exists, `%LOCALAPPDATA%\FTC Whisper` is gone, Installed apps and Task Manager say BrightLink Echo, and the recording pill opens bottom-centre just above the taskbar. The pill's placement log is `%TEMP%\ftc_pos_debug.log`: the `place mode=status` lines must show x = (work width - pill width) / 2 with no `CORRECTED` line after them.
7. Tell Ryan the install link: https://github.com/RJMURPHY0/BrightLink-Echo/releases/latest/download/BrightLink-Echo.exe

## Later, not in this release
- The BrightLink CRM (repo RJMURPHY0/Brightlink, `src/components/AppSidebar.tsx`) opens `ftcwhisper://launch`. v1.8.5 registers both `brightlinkecho://` and `ftcwhisper://`. Switch the CRM to `brightlinkecho://` once the fleet is on v1.8.5+. Its install link already points at `BrightLink-Echo.exe`.

## Rules that matter here
- British English, no em dashes, terse replies. Ryan wants results, not menus of options.
- Never force-push, never skip hooks, never commit `.env` or secrets. Never hand-build and upload an exe: releases only through CI (signing runs only there).
- The main checkout `C:\Users\ryan.murphy\Code\BrightLink - Echo` has someone else's uncommitted work (`app.py`, `asr_engine.py`, `transcriber.py`, `tests/test_memory_footprint.py`) and is 6 commits behind `origin/main`. Do not stash, reset or commit it; work in the `echo-identity` worktree.
- This laptop runs Avast Business, which intercepts HTTPS. Tools with their own certificate list fail with UnknownIssuer; per-user env vars already fix this (`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `UV_NATIVE_TLS=1`). Never use `verify=False`.
- Known test failures that also fail on untouched v1.8.4 on this laptop (environment, not regressions): `test_impact_panel` SpeedPanel footnote x2, `test_phrase_learning` corpus, `test_library_pages` SharedSearchBar x4, `test_settings_copy` LiveMicApply. Everything else passes (1,558+). Test venv used: Python 3.11 via uv with `-c constraints.txt`.
- End by listing anything Ryan still has to do under "Still waiting on you".
