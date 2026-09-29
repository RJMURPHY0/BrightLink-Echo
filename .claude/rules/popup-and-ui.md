---
paths: ["popup.py", "app_window.py", "ui_render.py", "bookmark_tabs.py", "login_window.py", "tray.py"]
---
# Popup, window and UI

Full history: docs/decisions/popup-pill.md, docs/decisions/settings-window-ui.md and docs/decisions/history-impact.md

- Use the house `Dropdown`, never `tk.OptionMenu` (it ignores the configured colours on Windows).
- Sign-in bars are white with dark text. Ryan's explicit, final call.
- Impact breakdowns never resize the window. The impact panel dismisses on any click.
- Read `docs/decisions/popup-pill.md` before changing popup anchoring or monitor logic. Four policies failed before the root cause (shared `ctypes.windll` poisoning) was found.
- Every Settings card description is one short line saying what ON means.
- Popup widget mutations always happen via `root.after(0, ...)` from background threads
- `popup.set_upgrade_result()` must always be called with the `session=` stamp of the dictation the result belongs to
- Never call tkinter widgets from a background thread directly — always `self._root.after(0, lambda: ...)`
- Don't reintroduce a trailing-word-window truncation in `update_caption` — that's what made caption scrollback impossible
