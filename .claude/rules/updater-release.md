---
paths: ["updater.py", "app_install.py", "pyi_runtime.py", "echo.spec", "version_info.txt", "constraints.txt", "brand.py", ".github/workflows/**"]
---
# Updater and release

Full history: docs/decisions/release-updater.md

- Public releases go through CI only. Signing (Azure Artifact Signing) runs in CI. Never hand-upload a local build.
- An update can never install a half-written exe. Keep the integrity checks in `updater.py`.
- Release and naming invariants are in CLAUDE.md. Read them before touching names or assets.
- An update is ONE `run_auto_update` per process, downloading to a file no other run can write, and the swap script installs ONLY a file whose SHA-256 still matches the one verified, through a hashed staged copy and `File.Replace`. Never reintroduce a shared download path, a second download in any entry point, or a plain `Copy-Item` over the installed exe: that combination installed a 21 MB prefix of a 130 MB exe and reported success. Pinned in `tests/test_update_integrity.py`, which runs the real script
- The updater's swap script must be spawned with `CREATE_NO_WINDOW` (+ `CREATE_NEW_PROCESS_GROUP`, DEVNULL std handles) — NEVER add `DETACHED_PROCESS`, which conflicts with `CREATE_NO_WINDOW` and makes powershell.exe exit 0 without running the script (this exact bug silently broke every in-app update ≤ v1.6.3)
- The bundled config in `echo.spec` is GENERATED from the `Config` dataclass defaults (+ the shared Supabase URL/key from `config.py` constants), never copied from the dev's `config.json`. Copying it shipped the developer's machine state to every new install: a pinned `input_device` naming a mic nobody else owns (a broken mic out of the box), `window_sizes` keyed by the dev's email, an experimental `whisper_model`, and raw API keys. The build hard-fails if any secret field would ship non-empty. Shipping defaults therefore live in `config.py`, not in `config.json`
- `APP_VERSION` in `app.py`, `filevers`/`prodvers` tuples, and `FileVersion`/`ProductVersion` strings in `version_info.txt` must all be kept in sync before every build
- Every release publishes SIX assets from one build (v1.8.1): `FTC-Whisper.exe` (the onefile bridge every pre-1.8 updater installs, forever), `BrightLink-Echo-Setup.exe` (the installer v1.8.1+ updates from), `FTC-Whisper-Setup.exe` (the same installer for v1.8.0 copies), `BrightLink-Echo.exe` (the same installer, for downloads) and the rollout file as `BrightLink-Echo-rollout.json` and `FTC-Whisper-rollout.json`. Never drop a legacy-named asset while a copy that fetches it may exist.
- Every data path goes through `data_paths.py`; never join `brand.DATA_DIR_NAME` or the legacy name yourself. Only `installer/activate.ps1` moves the legacy folders, recording every move and undoing them on any failure. `stage_installer` always passes `/DIR`: without it the installer stages in the legacy folder for v1.8.0.
- A onedir build NEVER copies its exe anywhere (`_ensure_installed_copy`): without its `app-<version>` folder it cannot start. Only the installer and `activate.ps1` put the installed layout in place. A onefile copy never overwrites a whole installed layout.
- Versions are switched only by the NEW version's `installer/activate.ps1`: manifest check first, the folder moved in, one exe `File.Replace` with a backup, rollback if the new version exits before `health.json`. Never write into a running version's `app-<version>` folder, and never stop a process by leaf name alone.
- The installer path requires GitHub's SHA-256 AND Authenticode `Valid` with exactly `brand.SIGNER_SUBJECT`. The installer registers no uninstall entry of its own (`Uninstallable=no`, `CreateUninstallRegKey=no`) and has no `AppMutex`.
- Update checks start when the core has loaded, signed in or not. A release goes out only after CI's installed-location `--selftest` passes (`tools/selftest_install.py`).
