"""
A local log of what the installed app prints, without the user's words.

The installed exe is a windowed build: sys.stdout and sys.stderr are None, so
every diagnostic print (recorder, hotkeys, mic probe, sync) went nowhere and a
dictation that came back "No speech detected" left no trace of why. install()
points both streams at echo.log in the app's local data folder, capped at
_MAX_BYTES with one previous file kept.

Nothing the user said, typed or signed in with may reach the file: dictated
text is printed in quotes, so every quoted span is replaced by its length,
except on the few tags that only ever quote device and hotkey names; tokens
and keys are masked on every line whatever the tag. A deleted dictation must
not survive in a log (issue #2), and a log may be attached to a support email.
"""

import datetime
import os
import re
import sys
import threading

_MAX_BYTES = 2 * 1024 * 1024

# Tags whose quoted values are device, hotkey or path names, never dictation.
_KEEP_QUOTES = frozenset({
    "Recorder", "HotkeyManager", "TriggerHotkeyManager", "AudioEngine",
    "MicScan", "Updater", "Install", "Tray",
})

_TAG = re.compile(r"^\s*\[([A-Za-z]+)\]")
_QUOTED = re.compile(r"'[^'\n]*'|\"[^\"\n]*\"")
_SECRETS = (
    re.compile(r"eyJ[\w-]{6,}\.[\w-]{6,}\.[\w-]{6,}"),            # JWTs
    re.compile(r"\bsb_(?:publishable|secret)_[\w-]+"),             # Supabase keys
    re.compile(r"\bsk-[\w-]{10,}"),                                # API keys
    re.compile(r"(?i)\b(access_token|refresh_token|password|api_key|apikey)"
               r"(\s*[=:]\s*)\S+"),
)


def redact(line: str) -> str:
    """One line as it may be written to disk."""
    for pattern in _SECRETS:
        if pattern.groups:
            line = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", line)
        else:
            line = pattern.sub("<redacted>", line)
    m = _TAG.match(line)
    if not (m and m.group(1) in _KEEP_QUOTES):
        line = _QUOTED.sub(lambda q: f"<{len(q.group(0)) - 2} chars>", line)
    return line


class _LogFile:
    """A text stream that timestamps, redacts and appends whole lines."""

    def __init__(self, path: str, max_bytes: int = _MAX_BYTES):
        self.path = path
        self.max_bytes = max_bytes
        self._pending = ""
        self._lock = threading.Lock()

    # The io.TextIOBase surface print() and traceback need.
    encoding = "utf-8"
    errors = "replace"

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False

    def flush(self) -> None:
        pass

    def write(self, text) -> int:
        if not text:
            return 0
        text = str(text)
        with self._lock:
            self._pending += text
            if "\n" not in self._pending:
                return len(text)
            *lines, self._pending = self._pending.split("\n")
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            out = "".join(f"[{stamp}] {redact(l)}\n" for l in lines if l.strip())
            if out:
                self._append(out)
        return len(text)

    def _append(self, out: str) -> None:
        try:
            if (os.path.exists(self.path)
                    and os.path.getsize(self.path) > self.max_bytes):
                os.replace(self.path, self.path + ".1")
            with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                f.write(out)
        except Exception:
            # Logging must never break the app; there is nowhere else to say so.
            pass


def install(path: str) -> bool:
    """Send stdout/stderr to the log when the process has no console.
    Returns True when installed. A console run (run.bat, tests) is left
    alone so developers keep seeing output live."""
    if sys.stdout is not None and sys.stderr is not None:
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        return False
    stream = _LogFile(path)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    return True
