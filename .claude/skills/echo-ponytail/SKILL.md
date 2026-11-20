---
name: echo-ponytail
description: Smallest-complete-change coding mode for BrightLink Echo (wraps DietrichGebert's Ponytail). Use on any coding task here, or when Ryan says "ponytail", "be lazy", "simplest solution" or complains about bloat. "/echo-ponytail debt" lists the deferred shortcuts. Levels lite, full (default), ultra.
argument-hint: "[lite|full|ultra|off|debt]"
---

# BrightLink Echo Ponytail

The method is in `references/ponytail.md` (upstream, unchanged). Read it, then follow it **with the rules below. Where they clash, these rules win**, and so do `CLAUDE.md`, `.claude/rules/` and `REVIEW.md`. A version bump merged to `main` builds a signed release that auto-updates on users' machines.

## Overrides (read these first)

1. **Lean means less new code, never fewer safety checks.** Upstream already says never cut validation, error handling or security. In this repo that list includes everything under "Never cut" below. If the short version drops one of them, it is the wrong version.
2. **Stay inside the task.** "Deletion beats addition" applies to the code you are changing. Do not delete or rewrite other code you happen to see; list it in your closing line instead. Wider clean-up goes through a separate, named clean-up task.
3. **No new packages** without Ryan saying yes, even when upstream rule 4 would allow one.
4. **Finished means checked.** Run `python -m unittest discover -s tests` (three known failures are listed in `docs/INSTALLER_MIGRATION_BRIEF.md`) and paste the real output. A smaller diff that fails a check is not done.
5. **Closing line**: end with what you skipped or did not check, and any risk, in plain British English (no em dashes).
6. **Shortcut comments** use upstream's form `shortcut: <the limit>, <when to upgrade>`. Never put one on auth, permission, money or data-safety code: those are finished properly or not at all.
7. **Ultra level** questions the request before building. Keep it to one short list of pushbacks, then do what Ryan decides.

## Never cut (this repo)

- Every invariant in `.claude/rules/`. Each one encodes a bug that shipped; a guard that looks redundant is there on purpose.
- Update integrity: `updater.py`, `app_install.py`, `pyi_runtime.py`, `installer/activate.ps1`, version sync (`app.py` `APP_VERSION`, `version_info.txt`) and `-c constraints.txt` in CI.
- Naming and folder invariants in `brand.py` and `data_paths.py`.
- Visible failure paths: memory guard, speech health and AV block recovery must never swallow an exception.
- Clipboard, focus and injection safety in `injector.py`, and sign-in and session restore in `auth.py` / `login_window.py`.
- The privacy promises in `PRIVACY.md` (what audio and text leaves the machine).

## Debt ledger

`/echo-ponytail debt` follows `references/ponytail-debt.md`: it lists every `shortcut:` comment with its limit and upgrade trigger, and changes nothing.

## Turn off

"stop ponytail" or "normal mode" turns it off for the session.
