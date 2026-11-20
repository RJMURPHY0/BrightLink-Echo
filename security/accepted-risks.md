# Accepted security risks

Risks Ryan has decided to live with. The security agent does not raise these again unless the reason stops being true. Each line: what, why it is accepted, who decided, date.

Nothing is accepted yet. Add a line here only when Ryan decides, never on an agent's own judgement.

## Scanner false positives (read in the code and proved, 2026-11-20)

Not risks Ryan accepted: findings from the 13 Nov generic Semgrep pass that the code shows cannot be reached. Echo is a local desktop app with no server of its own, so a path or command built from its own install and data folders has no outside author. Remove a line if the code it names changes.

- Code generation, `app.py` Tk self-test (`tcl.eval("package require msgcat")`, `tcl.eval("expr {1+1}")`) and `app_icons.py` `Image.eval` (PIL pixel maths): both take constant text, never user or network input.
- Weak random number, `tools/term_bench.py` (`random.Random(seed)`): a seeded benchmark shuffle in a dev tool, not shipped in the exe and not used for any secret.
- OS command, `app.py`, `app_install.py`, `installer.py`, `pyi_runtime.py`, `audio_engine.py`, `tools/*`: every `subprocess` call is an argument list without `shell=True`; the PowerShell `-Command` strings embed only Echo's own exe, shortcut and data paths (from `data_paths` and `install_layout`), with single quotes doubled. No dictated text, config value or synced value is placed in one.
- File path (the 227 + 7 sites in `app.py`, `app_install.py`, `tools/page_change_check.py`, `tools/scroll_check.py`): paths are built from `data_paths`, the install layout or fixed names; none comes from a dictation, a synced snippet or a network reply.
