# Plan: onefile exe to onedir + signed installer

Status: **BUILT on branch `installer-migration` (v1.8.0), not committed or released.** Written
2026-09-29 against v1.7.1, and built on v1.7.3 (`50e61f4`) after Ryan's go-ahead. Brief:
`docs/INSTALLER_MIGRATION_BRIEF.md`. The decision record, with measurements, is
`docs/decisions/release-updater.md` (2026-09-29).

Ryan's open questions, decided by following what Slack, Discord, VS Code (user setup) and Teams
do, and Echo's own look:

- The accuracy work had already shipped as v1.7.2 / v1.7.3, so this version is **v1.8.0**.
- **`BrightLink-Echo.exe` becomes the installer**, so every existing link gives new users an
  installer. Updaters use the frozen `FTC-Whisper-Setup.exe`.
- **Staging:** no live release is used. CI dry runs, plus `migration-e2e.yml` on clean GitHub
  VMs with a fake GitHub. Windows Sandbox is not available on Windows 11 Home.
- **The model stays the app's job:** retry, resume, per-file hashes, and installs that work
  offline.
- **The installer:** a dark wizard with the BrightLink mark and two ticks, both on ("desktop
  shortcut", "start when I sign in"), like VS Code's user setup.

Changes found while building, beyond the plan:

- Update checks started only after sign-in: now at core load.
- The bridge must migrate at its own version (`migration_due`).
- MAX_PATH guard in CI.
- Health is also written at the single-instance exit (the mutex is Global).

## 0. The design in one paragraph

The canonical path `%LOCALAPPDATA%\FTC Whisper\FTC Whisper.exe` stays. It becomes a PyInstaller
**onedir** exe whose contents folder is **versioned** (`app-1.8.0\` beside it, via
`contents_directory`). Nothing is unpacked at launch. An update never touches the running version's
files. The new version is laid out in full in `pending-<ver>\`, every file is checked against a
build-time SHA-256 manifest, then two steps activate it: the folder is renamed into place, then the
one exe is swapped with today's proven `File.Replace` + `.previous` primitive. The old exe still
points at the old folder, which still exists, so rollback is one exe swap. An **Inno Setup**
installer (signed, per-user, no admin, writes no uninstall entry of its own) delivers the files for
fresh installs, the Store, manual downloads and updates. `FTC-Whisper.exe` stays a **full onefile
build of the same version** (the "bridge"). Old clients install it with their own old swap script.
It runs exactly like today's app, then migrates itself to onedir when idle. If migration cannot
happen (offline, installer blocked), the machine keeps a working onefile Echo that retries later.

## 1. What I verified before writing this (PyInstaller 6.22.3, this laptop)

Throwaway probe builds in the session scratchpad (onedir versioned, onedir default, onefile):

| Question | Result | Consequence |
|---|---|---|
| Does `contents_directory='app-9.9.9'` work? | Yes. `sys._MEIPASS` = `<exe dir>\app-9.9.9` | A versioned layout needs no launcher |
| Does a onedir exe carry the onefile marker `MEI\x0c\x0b\x0a\x0b\x0e`? | **Yes**, `updater.pyi_archive_intact()` returns True | Old copies' `_handoff_to_canonical_if_newer` (v1.6.82+) accepts the onedir canonical exe and hands off to it instead of overwriting it |
| What bootloader variables does onedir set? | `_PYI_ARCHIVE_FILE`, `_PYI_PARENT_PROCESS_LEVEL`; **no** `_PYI_APPLICATION_HOME_DIR` | `pyi_runtime.running_on_foreign_runtime()` already returns False for onedir: the startup guard cannot relaunch-loop |
| Onedir exe started with a onefile process's leaked `_PYI_*` pointing elsewhere? | Ignored; used its own `app-9.9.9` | Onedir is immune to the v1.6.79 failure class |
| Onedir exe size (probe) | 1.7 MB (the PYZ is inside the exe) | Real app: to be measured. Irrelevant to old clients, which never download it |
| Current per-launch unpack on this laptop | 5,334 files, 291 MB, **197 PE files**, and **two** such folders present right now | Baseline for the measurements, and for the signing decision in §9 |

Also noted: the dev venv is **Python 3.12.10**, but CI builds on 3.11. Local builds are not
representative, so every proof in §12 uses CI dry-run artifacts.

Old updaters, read from git:

| Client | Swap script | Checks before installing | Repo it asks |
|---|---|---|---|
| ≤ v1.6.3 | `DETACHED_PROCESS`: never runs | size + MZ | `FTC_Whisper` (redirect) |
| v1.6.4 to v1.6.79 | `Copy-Item`, **leaks `_PYI_*`** | size + MZ (+ asset size) | `FTC_Whisper` (redirect) |
| v1.6.80 to v1.6.81 | `Copy-Item`, clean env | size + MZ | `FTC_Whisper` (redirect) |
| v1.6.82 to v1.6.86 | staged copy + hash + `File.Replace` | + MEI marker + GitHub SHA-256 | `FTC_Whisper` (redirect) |
| v1.6.87 to v1.7.1 | same as above | same | `BrightLink-Echo` |

Every one of them can install only a **PyInstaller onefile exe named `FTC-Whisper.exe`**.

## 2. Installed layout

```
%LOCALAPPDATA%\FTC Whisper\
  FTC Whisper.exe          canonical, signed onedir bootloader for the CURRENT version
  app-1.8.0\               its contents: _internal equivalent, config.json default, assets,
                           manifest.json, activate.ps1
  pending-1.8.1\           only while an update is staged (FTC Whisper.exe + app-1.8.1\)
  FTC Whisper.exe.previous only during activation/health check, then deleted
  models\                  UNTOUCHED (Parakeet, 660 MB)
  config.json              UNTOUCHED (still beside the exe, see §7)
  last-version.txt, last-product-name.txt, install-state.json, startup-error.log   UNTOUCHED
  update.log               new: activation log (moved out of %TEMP%)
  health.json              new: written by the app once its UI is up (see §4)
  runtime\                 onefile unpack dir: emptied after migration, then unused
%APPDATA%\FTC Whisper\     UNTOUCHED
```

Why a versioned contents folder rather than a launcher exe (the Squirrel/Discord shape):
- Every shortcut, the logon task, `ftcwhisper://`, App Paths and the uninstall entry already point
  at the canonical path, and it stays a real app exe. Nothing is repointed.
- `config.json` stays beside the exe with no migration.
- The single-instance mutex, `taskkill /IM "FTC Whisper.exe"` and the swap scripts' kill-by-leaf
  logic keep matching.
- No second native program to write, sign and maintain (a launcher that isn't PyInstaller would
  mean C in a pure-Python repo).

## 3. Activation: all-or-nothing, with rollback

One script, `activate.ps1`, **ships inside each new version** (generated from a Python template like
the current swap script, so tests run the real thing). The new version therefore controls its own
install. Today the old version's script installs the new one, which is how v1.6.79 happened.

Steps, each logged to `update.log`:

1. Wait for the given PID to exit. Kill anything whose path is the canonical exe, then by leaf name
   (same as the swap script).
2. **Repair first:** if the canonical exe is missing and `.previous` exists (a crash in an earlier
   run), restore it.
3. Check `pending-<ver>` against `manifest.json`: every path present with the right size, and the
   exe's SHA-256. Python has already hashed every file just before; see §4. On a mismatch,
   install nothing, relaunch the current version and exit 1.
4. Remove any leftover `app-<ver>` from an earlier failed attempt (never the running version's),
   then `[IO.Directory]::Move(pending-<ver>\app-<ver>, app-<ver>)`. This is one rename on the same
   volume.
5. `[IO.File]::Replace(pending exe, canonical, canonical.previous)`, re-hash, and restore
   `.previous` on a mismatch (exactly today's primitive). Set the exe's mtime to now: old copies
   without the handoff then never see themselves as "newer" and never copy over it.
6. Install mode only: run `"<canonical>" --install /S [--no-desktop-shortcut]
   [--start-with-windows=0|1]` **synchronously**. A non-zero exit rolls back.
7. Relaunch mode: start the canonical exe, then watch it for up to 180 s.
   - If `health.json` shows the new version: delete `.previous` and `pending-<ver>`.
   - If the new process **exits** without it (a startup crash): restore `.previous`, write
     `bad-version.txt`, relaunch the old version.
   - If it is merely slow (still running), never roll back.
8. The new app, once healthy, deletes `app-*` folders other than its own and every
   `runtime\_MEI*` it can (locked means in use: left alone).

Every failure point, and what the user is left with:

| Killed or failed at | State | Result |
|---|---|---|
| Download / stage (Inno killed mid-extract, AV quarantines a DLL, disk full) | `pending-<ver>` partial; live files untouched | Old version keeps running; the manifest refuses; the next attempt clears `pending` |
| Before step 4 | Nothing changed | Old version launches |
| Between 4 and 5 | New folder in place; exe still old | Old exe runs on the old folder; the next attempt reuses the new one |
| Inside `File.Replace` | Milliseconds between two renames; canonical may be missing, `.previous` present | Same exposure as today's swap. Step 2 repairs it on the next activation. **Residual risk, stated plainly** |
| New build crashes at start | Health watch sees the exit | Automatic rollback to the previous exe **and folder** (new vs today, which has no rollback after the hash check) |
| New build starts but is broken in use (a v1.6.79-class bug) | Health says OK | No automatic rollback. Mitigated by the CI installed-location `--selftest` gate (§8) |

`bad-version.txt` makes the updater skip that version until a strictly newer release appears. That
avoids an update-rollback loop every 6 hours.

## 4. Updates, onedir to onedir (v1.8.0 → v1.8.1)

Same shape and guards as today: one run per process, a per-run download file, idle wait, and
Update Now / `/update` join the run in flight.

1. `releases/latest` → asset `brand.SETUP_UPDATE_ASSET` (new frozen name, proposed
   `FTC-Whisper-Setup.exe`), its `size` and `digest`.
2. Download to `FTC-Whisper-Setup-new-<pid>-<time>.exe`. Then:
   - exact size;
   - **GitHub SHA-256 required** (today it is optional; for the installer a missing digest means
     no update);
   - Authenticode `Valid` with a signer subject exactly `CN=BRIGHTLINK (OS) LTD, …`, via
     `Get-AuthenticodeSignature`, not a PyInstaller marker check.
3. **Stage while the app keeps running:** start the installer with
   `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /STAGEONLY /LOG=<update dir>`, using the swap script's
   flags and `clean_launch_env()`. It writes only `pending-<ver>\`. Nothing live is touched and
   dictation keeps working.
4. Python hashes every file in `pending-<ver>` against `manifest.json` (a few seconds, in the
   background).
5. Wait for idle (`_safe_to_restart`, unchanged), re-check the exe hash, spawn
   `pending-<ver>\app-<ver>\activate.ps1 -Pid <pid> -Relaunch`, `os._exit(0)`.

The downtime is the activation only (kill, rename, one exe swap, relaunch), about as long as
today's swap, and the onedir start that follows is faster.

## 5. Transition: every old client

Every release from v1.8.0 on publishes:

| Asset | What it is | Who uses it |
|---|---|---|
| `FTC-Whisper.exe` (frozen, forever) | **Full onefile app**, same code and version (the bridge) | Every pre-1.8 updater |
| `FTC-Whisper-Setup.exe` (new, frozen) | Signed Inno installer | New updaters, the bridge's migration |
| `BrightLink-Echo.exe` (display name) | **Question 2:** the installer (same bytes as the setup) or stay onefile | README, CRM button, people |
| `FTC-Whisper-rollout.json` | `{"migrate_percent": 0-100}`, covered by its digest | Bridge migration gate. Absent = do not migrate |

The bridge, running at the canonical path, updates **only** by migrating, and only when all of
these hold:
- it is a onefile build;
- the rollout gate includes this machine (a stable hash of the machine GUID);
- the setup asset verifies.

Migration uses §4 exactly, and the `.previous` it leaves is the onefile bridge itself, a complete
standalone app, so rollback is safe. If the setup path fails 3 times, it falls back to today's
onefile `FTC-Whisper.exe` swap, so a machine that blocks installers still gets updates. The gate
lets us migrate Ryan's two PCs, then 5 %, 25 %, 100 %, and **pause fleet-wide without a new
build**.

What each client does when v1.8.0 is `latest`:

- **v1.6.3 (and older):** as today, its swap script never runs. The app exits and nothing
  installs. These machines have been stranded since July and still are. **Rescue: download and
  run the installer**, which kills the old copy, installs onedir and re-registers. The new app
  then repoints the logon task, reconciles the `Run` key and old Startup shortcuts, and retargets
  the desktop shortcut. That code already exists and still runs.
- **v1.6.79:** downloads `FTC-Whisper.exe` (onefile, passes size + MZ). Its leaky
  `Copy-Item` script installs it and relaunches with the old `_PYI_*`. The bridge is built exactly
  like today (onefile, PyInstaller 6.22.3, guard above every import, nothing sorting before
  `anthropic/`), so it inherits the old unpack and `relaunch_if_foreign_runtime` restarts it clean.
  This is the path proven 3 of 3 on 2026-09-14. The bridge then migrates when gated in.
- **v1.6.86:** asks `FTC_Whisper` and GitHub redirects. It downloads `FTC-Whisper.exe`, checks MEI
  marker + digest, and installs through staging + `File.Replace` with a clean env. The bridge
  starts normally, then migrates.
- **v1.7.1:** same as v1.6.86, via the new repo name. Then migrates.
- **An old onefile copy in Downloads, launched after migration:**
  - v1.6.15 or later: hands off, because the canonical exe is newer and passes the marker check.
  - Older than v1.6.15 (no handoff): may copy itself over the canonical exe if its mtime is newer.
    Step 5's mtime touch makes that unlikely. If it happens, the machine runs that old onefile,
    updates to the bridge, and migrates again. It self-heals and never bricks.
- **After migration (onedir v1.8.0 → v1.8.1):** §4. The new updater never takes `FTC-Whisper.exe`.

## 6. The installer (Inno Setup)

- Settings:
  - `PrivilegesRequired=lowest`, `DefaultDirName={localappdata}\FTC Whisper`,
    `DisableDirPage=yes`, `UsePreviousAppDir=no`, `ArchitecturesAllowed=x64compatible`.
  - **`CreateUninstallRegKey=no`, `Uninstallable=no`**, so the only Installed apps entry is ours
    (`FTCWhisper`, registered by `--install /S`).
  - No `AppMutex` (staging must run while the app is open).
  - Version info and publisher come from `brand.py` and `version_info.txt`, rendered at build.
- `[InstallDelete]` clears `pending-*`. `[Files]` go into `{app}\pending-<ver>\`. `[Run]` calls
  `activate.ps1 -Install`, waiting until it finishes, unless `/STAGEONLY`. The final page offers
  "Launch BrightLink Echo" (skipped when silent).
- Pages: one ready page with two tasks, **"Create a desktop shortcut"** and **"Start BrightLink
  Echo when I sign in"**. Both checked by default, and that checkbox is the Store 10.2.8 consent.
  It is passed to `--install /S` and written to `start_with_windows`. Branding comes from
  `assets/brand`. Details are Question 5.
- The model is **not** in the installer. Question 4 recommends leaving the download to the app, as
  today.
- Exit codes are Inno's (0 OK, 1-8 documented), with the Store mapping in `MICROSOFT_STORE.md`.

## 7. Everything that assumes one exe (audited)

- **`config.py`:** `get_config_path()` stays beside the exe, the same path as today, so there is
  nothing to migrate. `_bootstrap_config` reads `sys._MEIPASS\config.json` = `app-<ver>\config.json`
  (the spec keeps generating it, with the secret hard-fail). `--install /S` and `--verify` must never
  call `Config.load()` from `pending` (the existing `_installed_start_with_windows` pattern).
- **`sys._MEIPASS` users** (`app_icons`, `logo_cache`, `tray._resource_path`, `rthook_sounddevice`):
  the path works unchanged (verified). Tests pin it.
- **`_clean_stale_runtime_dirs`:** onedir removes every `_MEI*` it can (not only those over a day
  old), plus `.previous` and orphan `app-*` / `pending-*`.
- **`_ensure_installed_copy`:** **a onedir build must never copy itself.** Copying the bare exe
  without its folder would install an exe that cannot start. Onefile keeps today's behaviour. This
  is the most dangerous line in the migration and gets tests in both directions.
- **`_handoff_to_canonical_if_newer`:** the target must be "intact" in the new sense: marker, plus
  for onedir `app-<FileVersion>\manifest.json` present.
- **`_run_silent_install`:** for onedir, registration only. The files are already in place because
  the installer put them there.
- **`verify_exe` / `pyi_archive_intact`:** stay for the onefile path. A new
  `verify_installer(path, size, sha256)` checks MZ, size, digest and signer.
- **Kill logic:** leaf name unchanged. `image_names()` keeps `BrightLink-Echo.exe` for old
  Downloads copies. Nothing kills `FTC-Whisper-Setup.exe` mid-stage except uninstall.
- **`app_install._dir_size_kb`:** skips `runtime`, `pending-*`, `*.previous`.
- **`pyi_runtime`:** no behaviour change needed (§1). Add tests pinning "onedir is never foreign"
  and "onefile foreign is still detected". Every launch of our exe or installer keeps
  `clean_launch_env()` and the swap-script flags, never `DETACHED_PROCESS`.
- **Local server `/ping` `/show` `/update`, `ftcwhisper://`:** unchanged. `/update` goes through
  the same single run.

## 8. Build and CI

- **One spec, one `Analysis`, two outputs.** A onefile `EXE` (the bridge, unchanged settings) and
  a onedir `EXE` + `COLLECT` with `contents_directory=f"app-{APP_VERSION}"`. Distpaths
  `dist\onefile`, `dist\onedir`. `upx=False`, version resource and runtime hook are kept on both.
- `tools/make_manifest.py` writes `app-<ver>\manifest.json` (path, size, sha256) after the onedir
  exe is signed. `tools/render_installer.py` renders `installer\echo.iss` names from `brand.py`.
- **Inno Setup pinned:** download the exact release, check its SHA-256 (hard-coded in the workflow),
  install silently. `ISCC` gets `/DAppVersion=…`.
- **Signing,** in two passes, because the action is not recursive:
  1. `dist\onefile\FTC Whisper.exe` + `dist\onedir\FTC Whisper\FTC Whisper.exe`;
  2. the installer after `ISCC`.

  Verification: every shipped exe `Valid` **and** subject equal to the pinned
  `CN=BRIGHTLINK (OS) LTD, O=…, L=Syston, S=Leicester, C=GB`.
- **Installed-location smoke gate, before publish:** on the (throwaway) runner:
  - silent-install the setup, then run `"%LOCALAPPDATA%\FTC Whisper\FTC Whisper.exe" --selftest`
    on a clip generated with Windows SAPI on the runner (no personal recording in the repo);
  - the model comes from `actions/cache`;
  - also run `--selftest` on the onefile bridge;
  - a failure blocks the release.

  This catches a v1.6.79-class packaging break before any client sees it.
- `concurrency: { group: build-release, cancel-in-progress: false }`.
- Asset assertion: the release must contain every name in §5 before `make_latest`.
- VirusTotal scans all three exes. The dry-run artifact carries all of them (3 days).
- `-c constraints.txt`, the 6.22.3 pin, and the `APP_VERSION` / `version_info.txt` sync are kept.

## 9. Signing decision (to record)

Sign **our** PE files only: the onedir exe, the bridge and the installer, all on the same
certificate profile. **Do not** sign the 197 bundled third-party `.pyd`/`.dll` files:
- many are already vendor-signed (python311, onnxruntime by Microsoft);
- signing someone else's binary under BRIGHTLINK asserts authorship;
- a flag on any one of them lands on our certificate's reputation.

Revisit only if VirusTotal or Smart App Control shows DLL-level detections on the onedir folder.
Onefile loads the same unsigned DLLs today, so this is no regression.

## 10. Uninstall

The only entry is ours: `"<canonical>" --uninstall [/S]` → `run_uninstall`, unchanged. It kills
by image names, removes launchers, registry and shortcuts, then the deferred cleanup deletes
`%LOCALAPPDATA%\FTC Whisper`, which now includes `app-*` and `pending-*`. It asks before touching
`%APPDATA%`. `safe_to_delete` is unchanged. Inno leaves nothing (`Uninstallable=no`), which the
sandbox run checks with a registry and filesystem diff.

## 11. Tests (both directions, like the rest of the suite)

- `activate.ps1` executed for real against dummy trees, covering:
  - good activation;
  - a missing file, and a hash mismatch, refused with the old version relaunched;
  - leftover `app-<ver>` reused;
  - a locked file;
  - canonical missing + `.previous` repaired;
  - health rollback (a dummy "new exe" that exits at once, vs one that keeps running slow);
  - mtime touched;
  - never removes the running version's folder.
- The updater setup path:
  - digest required;
  - signer checked;
  - one run per process, and a per-run file;
  - stage-then-idle ordering;
  - `bad-version.txt` skip;
  - rollout gate (absent = no migration);
  - 3-strike fallback to the onefile swap.
- `_ensure_installed_copy`: onedir never copies itself; onefile unchanged. Handoff requires
  `app-<ver>\manifest.json`.
- `pyi_runtime`: onedir env is never foreign; the onefile leaked env still is.
- `brand`: new frozen constants pinned (`SETUP_UPDATE_ASSET`, `CONTENTS_DIR_PREFIX`,
  rollout asset name).
- Spec and workflow static checks:
  - both outputs, `contents_directory` from `APP_VERSION`;
  - `-c constraints.txt`;
  - Inno pinned by hash, signing covers every shipped exe, concurrency present.
- **Replaced, not deleted:** any test that pins "the canonical exe is always onefile" becomes a
  test of the new rule, named in the decision entry.

## 12. Proving it on real Windows (Windows Sandbox, CI-signed artifacts)

Staging (Question 3), recommended: **no GitHub release at all.** Inside the Sandbox, a tiny
Python "release server" answers `releases/latest` with the real dry-run artifacts and their real
SHA-256 digests. Failure injection is a switch on it: a wrong digest, a cut-off stream, a 404, no
network.
- Old clients (v1.7.1, v1.6.86, v1.6.79) are rebuilt from their tags with **one line changed**
  (the API URL pointed at the server). Their updater and swap script run otherwise as shipped.
- Those test builds are unsigned and never leave the Sandbox.
- Nothing live ever sees them.

Scenarios, with evidence captured per run (`update.log`, a registry export, a folder listing, a
`--selftest` report, `/ping`):

1. Fresh install, from the installer UI and from the Store silent switch:
   - the app starts;
   - the model downloads, verifies and loads (`--selftest` from the installed path);
   - dictation works;
   - Start menu, Installed apps (one entry), logon task on/off, `ftcwhisper://` and `/ping` all
     work.
2. v1.7.1 → v1.8.0 through v1.7.1's own updater, then migration:
   - onedir layout in place;
   - settings, history, vocabulary and sign-in survive;
   - **the model is not re-downloaded** (folder mtime and hash unchanged);
   - exactly one Installed apps entry;
   - every launcher works.
3. v1.6.86 → v1.8.0 (old repo name / redirect path), and v1.6.79 → v1.8.0 (leaky env path).
4. Failure injection. After each, the previous version must still launch:
   - kill the installer mid-stage;
   - kill `activate.ps1` at each step;
   - corrupt the download (digest mismatch);
   - a locked file in `app-<ver>`;
   - no network;
   - a new build that crashes at start (health rollback).
5. onedir v1.8.0 → v1.8.1 through the new updater.
6. Uninstall: everything removed, user data only on consent, nothing left running.

## 13. Measurements (before vs after)

- **Cold start to ready:**
  - fresh Sandbox, first launch;
  - time from process start to `/ping` answering, and to the engine-loaded log line;
  - 5 runs each, median.
- **Writes per launch:** files and bytes under `%LOCALAPPDATA%\FTC Whisper` and `%TEMP%` before
  and after a launch (baseline: 5,334 files / 291 MB).
- **VirusTotal:** detection count for the v1.7.1 `BrightLink-Echo.exe` vs the new installer, the
  new onedir exe and the bridge (the CI step, with the `VT_API_KEY` secret).

## 14. Release plan

- **v1.8.0** carries everything, with the rollout at **0 %**: the bridge ships to the fleet and
  behaves exactly like v1.7.1, and fresh installs get the installer.
- Then **Ryan's two PCs** (a machine allow-list in the rollout JSON), then 5 % → 25 % → 100 %,
  over days, watching update telemetry (`log_update_event` gains `stage_ok`, `activate_ok`,
  `rollback`).
- Changing the rollout JSON is a new release, or an edit of the latest release's asset (Question 3
  covers who does that).

## 15. Risks

1. **The `File.Replace` window** (§3). The same as today, and repaired on the next activation, not
   at boot.
2. **Two PyInstaller outputs per build.** A dependency that behaves differently onefile vs onedir
   is covered by both self-tests in CI.
3. **AV on staging 5,000 files** (one-time, per update). The manifest catches quarantine. The
   VirusTotal measurement decides whether DLL signing is needed.
4. **Store behaviour with an Inno installer** (return codes, "installed" detection via our entry).
   Proven only when Partner Center tests it.
5. **Disk:** about 290 MB × 2 during an update. The steady state is below today's (130 MB exe +
   291 MB unpack per run, with leftovers).
6. **The bridge build forever:** CI time roughly +40 %. It can be dropped only when telemetry shows
   no pre-1.8 clients, and even then `FTC-Whisper.exe` must stay published.
7. **Smart App Control and unsigned DLLs:** untestable in the Sandbox (SAC needs a clean OS
   install). The same exposure as today.

## 16. Questions for Ryan

1. Has the uncommitted accuracy work (`homophones.py`, `asr_engine.py` retry/integrity, …) been
   released? If not, commit and release it as v1.7.2 first, then branch `installer-migration`?
2. What links to `BrightLink-Echo.exe` besides the README (CRM button, emails, anything else)?
   Should that name become the installer?
3. Staging: the Sandbox fake release server (recommended), or something else?
4. Model download: leave it to the app as today (recommended), or add an installer progress page?
5. Installer: desktop shortcut and "start when I sign in" as checked tasks? Any branding wishes?
