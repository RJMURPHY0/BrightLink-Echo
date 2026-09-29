# Decisions index

Decision history moved out of CLAUDE.md on 2026-09-29. Each file holds dated entries, verbatim. Active rules are in `.claude/rules/<area>.md`, loaded when you touch matching files.

Record a new decision as a dated entry at the bottom of the matching area file. Add a one-line rule to `.claude/rules/<area>.md` only if it must be enforced.

- [`release-updater.md`](release-updater.md): Release assets, auto-update, signing, CI release, half-written exe guard, Store groundwork.
- [`branding-naming.md`](branding-naming.md): Rename to BrightLink Echo, brand.py as the one name source, artwork, repo rename.
- [`auth-signin.md`](auth-signin.md): Shared Supabase auth, sign-in look, auto-login, session restore resilience.
- [`history-impact.md`](history-impact.md): History, Your impact cards, breakdowns, range picker, feedback flag.
- [`settings-window-ui.md`](settings-window-ui.md): Settings, dashboard window, ghosting, Dropdown, search bar, tabs, spacing.
- [`popup-pill.md`](popup-pill.md): Recording pill, refine popup, badge, monitor placement, anchoring policy.
- [`text-formatting.md`](text-formatting.md): Punctuation, spoken symbols, lists, email layout, sentence endings, refine spacing.
- [`accuracy-vocabulary.md`](accuracy-vocabulary.md): Engines, hallucination and stutter guards, VAD, managed vocabulary, phrase learning.
- [`audio-capture-hotkeys.md`](audio-capture-hotkeys.md): Warm mic, mic selection, start cue, hotkey capture and fallback.
- [`injection-clipboard.md`](injection-clipboard.md): Focus capture, clipboard restore, Live Typing, line breaks.
- [`reliability-telemetry.md`](reliability-telemetry.md): Fleet telemetry, memory guard, dead audio stack, hot-path costs.
- [`invariants.md`](invariants.md): the key invariants list, verbatim. Each item encodes a shipped bug.
- [`architecture-notes.md`](architecture-notes.md): threading, Parakeet path, Live Typing, injection, popup, hotkeys, update flow, config.
- [`claude-md-archive.md`](claude-md-archive.md): lines of the old CLAUDE.md that were rewritten, kept verbatim.

