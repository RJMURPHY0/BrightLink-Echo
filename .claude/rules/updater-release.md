---
paths: ["updater.py", "app_install.py", "pyi_runtime.py", "ftc_whisper.spec", "version_info.txt", "constraints.txt", "brand.py", ".github/workflows/**"]
---
# Updater and release

Full history: docs/decisions/release-updater.md

- Public releases go through CI only. Signing (Azure Artifact Signing) runs in CI. Never hand-upload a local build.
- An update can never install a half-written exe. Keep the integrity checks in `updater.py`.
- Release and naming invariants are in CLAUDE.md. Read them before touching names or assets.
- An update is ONE `run_auto_update` per process, downloading to a file no other run can write, and the swap script installs ONLY a file whose SHA-256 still matches the one verified, through a hashed staged copy and `File.Replace`. Never reintroduce a shared download path, a second download in any entry point, or a plain `Copy-Item` over the installed exe: that combination installed a 21 MB prefix of a 130 MB exe and reported success. Pinned in `tests/test_update_integrity.py`, which runs the real script
- The updater's swap script must be spawned with `CREATE_NO_WINDOW` (+ `CREATE_NEW_PROCESS_GROUP`, DEVNULL std handles) — NEVER add `DETACHED_PROCESS`, which conflicts with `CREATE_NO_WINDOW` and makes powershell.exe exit 0 without running the script (this exact bug silently broke every in-app update ≤ v1.6.3)
- The bundled config in `ftc_whisper.spec` is GENERATED from the `Config` dataclass defaults (+ the shared Supabase URL/key from `config.py` constants), never copied from the dev's `config.json`. Copying it shipped the developer's machine state to every new install: a pinned `input_device` naming a mic nobody else owns (a broken mic out of the box), `window_sizes` keyed by the dev's email, an experimental `whisper_model`, and raw API keys. The build hard-fails if any secret field would ship non-empty. Shipping defaults therefore live in `config.py`, not in `config.json`
- `APP_VERSION` in `app.py`, `filevers`/`prodvers` tuples, and `FileVersion`/`ProductVersion` strings in `version_info.txt` must all be kept in sync before every build
