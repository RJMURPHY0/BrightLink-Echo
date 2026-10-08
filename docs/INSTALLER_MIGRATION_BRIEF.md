# Brief: move BrightLink Echo from a single self-extracting exe to a real installer

You are taking over a planned engineering project on **BrightLink Echo** (formerly FTC Whisper), a Windows push-to-talk dictation app owned by Ryan Murphy (BRIGHTLINK (OS) LTD). It is live and in daily use by real customers, and it auto-updates itself. **A mistake in the update path can silently strand every installed copy. That has already happened once.** Treat this as a careful migration, not a quick change.

Read this whole brief before you touch anything. Then read `CLAUDE.md`, `docs/decisions/release-updater.md`, `docs/decisions/invariants.md`, `docs/decisions/architecture-notes.md`, `docs/FALSE_POSITIVE_REPORTING.md` (especially §5), `docs/MICROSOFT_STORE.md`, `docs/CODE_SIGNING.md` and `.claude/rules/updater-release.md`.

---

## 1. Where things are

- **Repo:** `C:\Users\ryanm\Code\BrightLink - Echo`. GitHub is `RJMURPHY0/BrightLink-Echo`, branch `main`. Ryan's other PC has a copy at `C:\Users\ryan.murphy\BrightLink - Echo`.
- **Stack:** Python 3.11, tkinter, PyInstaller (pinned to **6.22.3** in `constraints.txt`; this pin is load-bearing), onnxruntime and onnx-asr (Parakeet speech model), faster-whisper (fallback engine), Supabase (optional sign-in). There is no JS or Node.
- **Dev setup:**
  - Dev venv: `venv\` (already created).
  - Run the app: `venv\Scripts\python.exe app.py`.
  - Tests: `venv\Scripts\python.exe -m unittest discover -s tests`. About 1,343 tests. **Three already fail on this laptop and are not yours to fix:**
    - `test_impact_panel.SpeedPanelTests` ×2: a tkinter layout quirk.
    - `test_phrase_learning...test_learned_phrases_do_not_rewrite_real_dictation`: this PC's dictation history is too short.
  - The suite occasionally aborts at teardown with `Tcl_AsyncDelete`. Re-run it.
- **Uncommitted work already in this tree.** Accuracy changes are sitting uncommitted in the working copy:
  - New files: `homophones.py`, `tests/test_homophones.py`, `tests/test_model_integrity.py`, `tests/test_parakeet_download_retry.py`.
  - Edits to `app.py`, `asr_engine.py`, `config.py`, `app_window.py` and the docs.
  - **Do not discard, reformat or bundle them into your work.** Ask Ryan whether they have been released yet. If not, ask whether to commit them first as their own release. Then do this project on its own branch (for example `installer-migration`).
- **House rules:**
  - Never commit, push or tag unless Ryan explicitly says so.
  - Never force-push or skip hooks.
  - **Public releases go through CI only.** Never hand-upload a locally built exe; local builds are unsigned.
  - Record decisions as dated entries at the bottom of the matching `docs/decisions/<area>.md`, not in `CLAUDE.md`.

## 2. Why this project exists

Echo ships as **one PyInstaller onefile exe** (`FTC Whisper.exe`, about 130 MB, signed by BRIGHTLINK (OS) LTD through Azure Artifact Signing). Every launch it unpacks itself into `%LOCALAPPDATA%\FTC Whisper\runtime\_MEIxxxxx`. Measured on 2026-09-29, that is **291 MB and 5,334 files written to disk on every start**.

That causes two problems:

1. **Slower start-up.**
2. **The strongest remaining antivirus heuristic after code signing.** Unpacking native code and then running it looks like malware staging. `docs/FALSE_POSITIVE_REPORTING.md` §5 already names the fix: **onedir + a real installer (e.g. Inno Setup)**. That doc also warns it "breaks the current auto-update swap logic… needs a planned refactor of the updater… do not attempt it piecemeal."

**Goal:** new and existing users end up with an onedir build installed by a signed installer. Auto-update, the Microsoft Store route, uninstall, start-with-Windows, the URL protocol and the model folder all keep working. Every existing install on every old version migrates automatically, with no manual step and no re-download of the 660 MB speech model.

**Success is measured, not assumed.** Report before and after numbers for:
- cold-start time to the app being ready
- files and MB written per launch
- VirusTotal detection count for the old asset vs the new installer and the new exe

## 3. How it works today (facts, with locations)

### Build: `echo.spec`
- It is onefile: `EXE(...)` takes binaries, zipfiles and datas, and there is no `COLLECT`.
- Settings: `name=_brand.EXE_BASENAME` ("FTC Whisper"), `upx=False`, `runtime_tmpdir='%LOCALAPPDATA%\\FTC Whisper\\runtime'`, `console=False`, icon `exe_icon.ico`, and version info rendered from `version_info.txt` through `brand.render_version_info`.
- It **generates** the bundled `config.json` from the `Config` dataclass defaults into `build/sanitized/config.json`. The frozen app bootstraps from `sys._MEIPASS/config.json`.
- The build **hard-fails if any secret field is non-empty**. Keep that.
- `collect_all` runs over 24 packages. The runtime hook is `rthook_sounddevice.py`, which puts `_MEIPASS\_sounddevice_data\portaudio-binaries` on PATH.

### CI: `.github/workflows/build-release.yml`
- The `check` job reads `APP_VERSION` from `app.py`. It only builds if no release exists for that version. A tag push forces a build; `workflow_dispatch` is a **dry run** unless `publish` is ticked.
- The build uses `uv pip install ... -c constraints.txt` (never remove the `-c`), then `pyinstaller --noconfirm --clean echo.spec`.
- Signing:
  - `azure/login` uses OIDC.
  - `azure/artifact-signing-action@v2.0.0` signs **only `*.exe` directly in `dist\`**. It is not recursive, so a onedir subfolder or an installer in another folder will not be signed unless you change this.
  - A partial set of signing variables throws an error.
- The signed exe is **copied** to two release assets, `FTC-Whisper.exe` and `BrightLink-Echo.exe`, which have identical hashes. Both must pass `Get-AuthenticodeSignature` = Valid.
- A VirusTotal scan runs (`continue-on-error`).
- `softprops/action-gh-release@v2` publishes tag `v<ver>` with `make_latest: true`.
- There is no `concurrency:` block. Add one.

### Updater: `updater.py`
Every old client runs this, so it is the contract you inherit.

- **Release lookup:** `https://api.github.com/repos/<brand.GITHUB_REPO>/releases/latest`. It picks the asset named **exactly `FTC-Whisper.exe`** (`brand.UPDATE_ASSET`) and takes its SHA-256 from the GitHub asset `digest`. `is_newer()` is a strict tuple comparison, so tags must strictly increase.
- **Download:** one `run_auto_update` per process, each run with its own download file (`FTC-Whisper-new-<pid>-<time>.exe`).
- **Onefile-only checks:** `verify_exe` checks size, the `MZ` header, and `pyi_archive_intact()`, which looks for the PyInstaller onefile cookie `MEI\x0c\x0b\x0a\x0b\x0e` at the end of the exe.
- **The swap script:** `spawn_swap_script` writes a PowerShell script to `%TEMP%\ftc_whisper_update.ps1`. The script:
  1. Waits for the process to exit.
  2. Kills the exe by path and then by leaf name.
  3. Unblocks the file and re-checks its hash.
  4. Stages a copy, hash-checks it, then runs `[IO.File]::Replace(stage, current, current.previous)`.
  5. Re-hashes the installed file and restores `.previous` on a mismatch.
  6. Relaunches.
- **Process flags:** `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` (+ `CREATE_BREAKAWAY_FROM_JOB`), DEVNULL std handles, and `env=pyi_runtime.clean_launch_env()`. **Never `DETACHED_PROCESS`**; it made every update ≤ v1.6.3 silently do nothing.
- **Important:** the *currently installed* version's swap script is the one that installs the next version. Whatever you ship must install correctly through the **old** scripts. Old clients back to ≤ v1.6.86 still reach the repo through GitHub's rename redirect from `FTC_Whisper`, so never create a repo called `FTC_Whisper`.
- **Callers:** app.py `_start_update_check` (at launch, then every 6 h) and `_start_auto_update`, which applies only when idle and more than 120 s after the last dictation. Also the local-server `/update` route on `127.0.0.1:47832` and the banner in `app_window.py` (`show_update_banner` / `_do_update`).

### Install and registration: the app installs itself (`app.py`, `app_install.py`)
- **Startup order in `_main()`:** `--selftest` → `--uninstall` → `--install` (silent Store install) → `_handoff_to_canonical_if_newer()` → `_ensure_single_instance()` (mutex `Global\FTC_Whisper_SingleInstance`) → config → background registration.
- **The canonical exe** lives at `%LOCALAPPDATA%\FTC Whisper\FTC Whisper.exe`. `_ensure_installed_copy()` copies the running exe there (staging + `os.replace`). `_handoff_to_canonical_if_newer()` hands off to it if its FileVersion is newer.
- **Everything points at the canonical exe:**
  - Start menu and desktop shortcuts
  - the Task Scheduler logon task "FTC Whisper" (created from XML, gated by `start_with_windows`)
  - the `ftcwhisper://` URL protocol (`"<exe>" "%1"`)
  - App Paths
  - the Installed apps entry `HKCU\...\Uninstall\FTCWhisper`: `UninstallString="<exe>" --uninstall`, `QuietUninstallString ... --uninstall /S`, `NoModify`/`NoRepair`
- **Uninstall** (`run_uninstall`) kills instances by image name, removes launchers, registry entries and shortcuts, then deletes `%LOCALAPPDATA%\FTC Whisper` through a deferred cleanup script. `%APPDATA%\FTC Whisper` is deleted only if the user chooses to. `safe_to_delete()` refuses anything but those two exact folders.
- `docs/decisions/release-updater.md` (2026-08-05) records that a real installer was deliberately **not** built *then*, because it would fight the in-place exe swap. This project reverses that decision on purpose. Record the reversal and the reasons.
- **Microsoft Store** (`docs/MICROSOFT_STORE.md`): the plan is the Store's "EXE or MSI app" route (policy 10.2.9) with a versioned GitHub URL and silent switch `--install /S`. MSIX was rejected. Self-updating is allowed; start-at-sign-in needs consent (`start_with_windows`). A new installer changes the package URL and the silent switch (Inno uses `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`), so update that doc.

### PyInstaller runtime guards: `pyi_runtime.py` + the top of `app.py`
- **`clean_launch_env()`** strips the `_PYI_*` variables whenever we launch our own exe. **Every launch of our own exe must use it.** This comes from the v1.6.79 outage: a relaunched exe ran on the *old* build's unpacked native libraries.
- **The startup guard** at the top of `app.py` (above every project import) calls `relaunch_if_foreign_runtime`.
- Both are built around the **onefile parent/child** model. Decide deliberately what they mean for onedir. They must keep working for the transitional onefile builds, and must not break the onedir build.

### Things that assume one exe
Audit each one; don't grep and hope.

- **`config.py`:** `get_config_path()` puts `config.json` **beside the exe** (`dirname(sys.executable)`). `_bootstrap_config()` copies `sys._MEIPASS/config.json` on first run.
  - In a onedir build `sys._MEIPASS` is the `_internal` folder. Verify it.
  - If the exe ever moves, **migrate the user's `config.json`**. It holds their settings, vocabulary and window sizes.
  - A Program Files install would make this path unwritable. That is one reason the install should stay **per-user, no admin** (`asInvoker`), under `%LOCALAPPDATA%\FTC Whisper`.
- **`sys._MEIPASS` users:** `app_icons.py`, `logo_cache.py`, `tray.py` (`_resource_path`), `rthook_sounddevice.py`, and `app.py`'s `_clean_stale_runtime_dirs` and `_selftest`.
- **`pyi_archive_intact` / `verify_exe`** are used in `_ensure_installed_copy`, `_handoff_to_canonical_if_newer` and `_run_silent_install`. The onefile cookie does not exist in an onedir exe.
- **Kill logic:** the swap script kills by exe leaf name; `app_install._kill_other_instances` uses `taskkill /IM` over `image_names()`.
- `app_install._dir_size_kb` skips `runtime`.
- `README.md` links `releases/latest/download/BrightLink-Echo.exe`, and the CRM's download button probably does too. **Ask Ryan** what else links to that asset.
- The local server on `127.0.0.1:47832` (`/ping`, `/show`, `/update`) and `ftcwhisper://` are used by the BrightLink CRM. Both must keep working.

### `brand.py` frozen block
These names never change: `DATA_DIR_NAME`, `EXE_BASENAME`, `CANONICAL_EXE_NAME`, `MUTEX_NAME`, `TASK_NAME`, `URL_SCHEME`, `UNINSTALL_KEY_NAME`, `UPDATE_ASSET`, `GITHUB_REPO`, and the user agents.

- `tests/test_brand.py` pins every value.
- **Names a person sees come only from `brand.py`.**
- **Never build a path, registry key or exe name from `PRODUCT_NAME`.**
- New assets or constants (for example a setup exe name) belong in `brand.py`, with tests.

### Models and data
These must survive the migration untouched.

- **Parakeet** (660 MB) lives at `%LOCALAPPDATA%\FTC Whisper\models\parakeet-tdt-0.6b-v2-onnx\`. It is pinned to an exact HF commit, with a per-file SHA-256 and a `.verified.json` marker (`asr_engine.py`). It is downloaded at first run by the app, with retry and resume. **An update must never delete or re-download it.** Decide deliberately whether the installer downloads it (with visible progress) or leaves it to the app. Do not bundle it into the installer.
- **Whisper fallback models** go to the default Hugging Face user cache (no `download_root`).
- **User data** is in `%APPDATA%\FTC Whisper\`: session, history, audio, stats, and the `phrases` folder under LOCALAPPDATA.
- `last-version.txt`, `last-product-name.txt`, `install-state.json` and `startup-error.log` live in `%LOCALAPPDATA%\FTC Whisper\`.

### Self-test
`FTC Whisper.exe --selftest <wav> <report.json>` proves the **packaged** engine works: model load, VAD and one transcription. It exits 0 only when words come back. It runs before the mutex and touches no config. **Run it against every build you produce, installed in its real location.** A test clip exists on this laptop at `%APPDATA%\FTC Whisper\audio\20260929182347843235.wav`; the expected text is "Revenue One this quarter." or similar.

## 4. Hard constraints

Each of these encodes a shipped bug.

1. **The `FTC-Whisper.exe` release asset is forever.** Every installed client finds updates by that exact name and installs it with its *own* old swap script, which expects a single onefile exe (MZ header + MEI cookie + SHA-256 match). So there must be a **transitional path**: `FTC-Whisper.exe` stays a valid onefile exe that the old scripts install. Its job becomes handing the machine over to the new installed layout. Never drop or rename that asset.
2. **No machine may be left without a working Echo.** The update must be all-or-nothing with rollback, like today's `File.Replace` + `.previous` + re-hash.
   - An interrupted or failed install must leave the previous version launchable.
   - Never ship a design where a crash half-way through copying 5,000 files bricks the app.
   - Versioned side-by-side folders with a switch at the end are one option. Inno Setup's own behaviour is another, but only if you can prove the failure cases.
3. **Keep the canonical launch path working.** Existing shortcuts, the logon task, the URL protocol, App Paths and the uninstall entry all point at `%LOCALAPPDATA%\FTC Whisper\FTC Whisper.exe`.
   - Either keep that path launchable (for example onedir laid out in that folder, or a tiny stable launcher there), or repoint every one of them in the same migration and repair them on every launch as today.
   - The existing `_repair_desktop_shortcut` / `register()`-on-every-launch pattern exists for exactly this.
4. **Integrity end to end.**
   - Verify the downloaded installer's SHA-256 against the GitHub asset digest before running it.
   - The installer and the app exe must both be Authenticode-signed with the **same certificate subject** (`CN=BRIGHTLINK (OS) LTD`); SmartScreen reputation is tied to it.
   - Extend the CI signing and verification step to every exe you ship. Consider whether bundled `.pyd`/`.dll` files need signing (they're third-party). Decide and record it.
5. **No admin, no UAC prompt.** Per-user install, `PrivilegesRequired=lowest` (Inno), `asInvoker`. The self-updater runs unattended.
6. **Every launch of our own exe or installer uses `pyi_runtime.clean_launch_env()`.** Spawn detached helpers with the same flags as the swap script. **Never `DETACHED_PROCESS`.**
7. **Keep the other build rules:**
   - `-c constraints.txt` and the PyInstaller 6.22.3 pin
   - `upx=False`
   - full version metadata
   - the generated-config secret hard-fail
   - `APP_VERSION` synced with all four `version_info.txt` fields
   - strictly increasing tags
   - new build tools (Inno Setup) pinned to an exact version in CI
8. **Keep the silent Store install working.** Update `docs/MICROSOFT_STORE.md` with the new package URL and switch.
9. **Uninstall still removes everything it should, and nothing else.** That includes the new app folder and the Installed apps entry. Make sure there is one entry, not two (Echo's own plus Inno's). Keep `safe_to_delete` semantics, and keep asking before deleting user data.
10. **Don't delete or weaken tests to make the suite green.** Where a test pins onefile behaviour that deliberately changes, replace it with a test that pins the new behaviour, and say so in the decision entry.

## 5. What to do, in order

1. **Investigate, then write a plan. Stop there for approval.**
   - Read the docs and code above.
   - Put a written design in `docs/decisions/` or a plan file covering:
     - the installed folder layout
     - how the canonical path stays valid
     - the update mechanism for onedir, with its all-or-nothing and rollback story
     - **the exact transition path for every old client version**. Walk through what a v1.6.3, v1.6.79, v1.6.86 and v1.7.1 client each does when it sees your first new release.
     - how config and data migrate
     - CI changes
     - signing
     - Store impact
     - uninstall
     - risks
   - **Get Ryan's explicit go-ahead before building.**
2. **Build it on a branch**, with tests for every new rule (both directions, like the rest of the suite).
3. **Prove it on real Windows, not just unit tests.** Use **Windows Sandbox** (or a clean VM) so each run starts from a clean machine. Run the real signed artifacts from a `workflow_dispatch` dry run: dispatch without `publish`, and download the `dry-run-v<ver>` artifact. Required scenarios:
   - **Fresh install:** from the download asset and from the Store silent switch. Then check:
     - the app starts
     - the model downloads, verifies and loads (`--selftest` passes from the installed location)
     - dictation works
     - Start menu entry, Installed apps entry, logon task (on/off) and `ftcwhisper://` work
     - `127.0.0.1:47832/ping` answers
   - **Upgrade from the current release through the real auto-update path.** Install v1.7.1 (or the latest release), point it at your test release, and let *its* updater do the work. Confirm afterwards:
     - you're on the onedir layout
     - settings, history, vocabulary and sign-in survived
     - the model was **not** re-downloaded
     - there is exactly one Installed apps entry
     - all shortcuts and the logon task still launch
   - **Upgrade from an old client** (e.g. v1.6.86, which still uses the old repo name via redirect). This proves the transition path handles the oldest clients in the wild.
   - **Failure injection:**
     - kill the update half-way
     - corrupt the downloaded installer (hash mismatch)
     - lock a file in the install folder
     - no network

     After each, the previous version must still launch.
   - **Next update after migration:** onedir v(N) to onedir v(N+1) through the new updater.
   - **Uninstall:** everything removed, user data only on consent, nothing left running.

   Testing against a live release is outward-facing (clients update to it). **Ask Ryan how he wants to stage it**, for example a private test repo or a pre-release that `releases/latest` does not return. Never publish to the real repo to test.
4. **Measure and compare:**
   - cold-start time and disk writes per launch, before and after
   - VirusTotal detection count for the new installer and app exe vs the current `BrightLink-Echo.exe` (the CI already has an optional VirusTotal step)
5. **Document:**
   - decision entry in `docs/decisions/release-updater.md` (reversing the 2026-08-05 "not a real installer" entry, with the reasons and measurements)
   - update `FALSE_POSITIVE_REPORTING.md` §3/§5, `MICROSOFT_STORE.md`, `CODE_SIGNING.md`, `ARCHITECTURE.md` and the invariants list
   - one-line enforced rules in `.claude/rules/updater-release.md`
6. **Hand back to Ryan** before any release:
   - what changed
   - the scenario results (pass/fail per scenario, with evidence)
   - the measurements
   - the exact release plan (which version carries the transition, what old clients will do)
   - anything left unproven, stated plainly

## 6. Things to ask Ryan rather than assume

- Whether the uncommitted accuracy work in the tree has been released, and whether to commit it first.
- What links to `BrightLink-Echo.exe` besides the README (the CRM's download button, emails, the Store listing).
- How to stage a test release safely.
- Whether the installer should download the speech model during install, with a progress page, or leave it to the app as today.
- Installer look and feel: branding, whether to offer a desktop shortcut or a "start with Windows" checkbox. The Store policy needs consent for start-at-sign-in.
