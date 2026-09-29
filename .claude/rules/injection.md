---
paths: ["injector.py", "app.py"]
---
# Text injection

Full history: docs/decisions/injection-clipboard.md

- Capture the focused child control and caret at record start, not just the top-level hwnd.
- Copy to Clipboard OFF restores what the user had copied, images included.
- A typed line break is Shift+Enter, never Enter.
- Live Typing never retypes over a failed delete.
- `_clipboard_paste` must NEVER send Ctrl+V when `_clipboard_set` reported failure — that pastes stale clipboard content (possibly a password) and reports success
- A typed line break (`_send_unicode`, used by the browser fallback and Live Typing) must be Shift+Enter via `_line_break_events()`, NEVER a bare VK_RETURN: Enter is Send in every chat composer, and a paragraph break then submits half the dictation. A partial SendInput must never be re-sent through another transport. Pinned in `tests/test_typed_line_breaks.py`
- In Live Typing, `_reconcile_live` (app.py) is the ONLY place backspaces are sent, and only when the target field provably kept focus. `on_inject` contract: True = landed, None = target not foreground (skip the tick, stream stays alive and resumes), False = transport failure (freezes `stream_frozen`). Any focus wobble flips `_live_focus_lost`, so reconcile appends instead of deleting; the append path aligns by CONTENT (streamed-suffix match in target), never by word count. A pause-flushed terminal period is withheld (`_pending_punct`) and restored only if the next chunk starts a capital. A tick whose hypothesis comes back empty must return early — never emit or shrink the caption on a busy tick
