"""
A local log of what the installed app prints, without the user's words.

The installed exe is a windowed build: sys.stdout and sys.stderr are None, so
every diagnostic print (recorder, hotkeys, mic probe, sync) went nowhere and a
dictation that came back "No speech detected" left no trace of why. install()
points both streams at echo.log in the app's local data folder, capped at
_MAX_BYTES with one previous file kept.

Nothing the user said, typed or signed in with may reach the file. The call
sites log the LENGTH of dictated, refined and clipboard text, never the text
(see tests/test_runtime_log.py, which scans the source for regressions).
redact() is the safety net behind that: each print is redacted as one block,
so text with line breaks stays together, and everything from the first quote
mark to the last one in the block (straight or curly, so an apostrophe inside
"it's" cannot end the span early) becomes its length. The few tags that only
ever quote device and hotkey names keep their quotes; tokens, keys and email
addresses are masked whatever the tag. A deleted dictation must not survive
in a log (issue #2), and a log may be attached to a support email.
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
# Every quote mark text can arrive in: straight, curly, low-9, angle, backtick.
_QUOTE_MARKS = "'\"`‘’‚‛“”„‟‹›\xab\xbb"
# First quote mark to last one (DOTALL: a quoted span may run over lines).
_QUOTED_SPAN = re.compile(
    f"[{re.escape(_QUOTE_MARKS)}].*[{re.escape(_QUOTE_MARKS)}]", re.DOTALL)
# A traceback frame ('  File "x.py", line 3, in f' plus its source line) is
# program text: redact it line by line so the line numbers stay readable.
_FRAME = re.compile(r'^\s*File "')
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# A print that never ends its line is dropped past this size, never split.
_MAX_PENDING = 64 * 1024
_SECRETS = (
    re.compile(r"eyJ[\w-]{6,}\.[\w-]{6,}\.[\w-]{6,}"),            # JWTs
    re.compile(r"\bsb_(?:publishable|secret)_[\w-]+"),             # Supabase keys
    re.compile(r"\bsk-[\w-]{10,}"),                                # API keys
    re.compile(r"(?i)\b(access_token|refresh_token|password|api_key|apikey)"
               r"(\s*[=:]\s*)\S+"),
)


def _hide_quoted(text: str) -> str:
    return _QUOTED_SPAN.sub(lambda q: f"<{len(q.group(0)) - 2} chars>", text)


def redact(text: str) -> str:
    """One print (a line, or several lines written together) as it may be
    written to disk."""
    for pattern in _SECRETS:
        if pattern.groups:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", text)
        else:
            text = pattern.sub("<redacted>", text)
    text = _EMAIL.sub("<email>", text)
    m = _TAG.match(text)
    if m and m.group(1) in _KEEP_QUOTES:
        return text
    if _FRAME.match(text):
        return "\n".join(_hide_quoted(line) for line in text.split("\n"))
    return _hide_quoted(text)


def safe_value(value) -> str:
    """A setting's value as it may be logged: numbers, switches and None as
    they are; text and lists (snippets, vocabulary, a name, a prompt) only by
    size."""
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    if isinstance(value, str):
        return f"<{len(value)} chars>"
    try:
        return f"<{type(value).__name__}, {len(value)} items>"
    except TypeError:
        return f"<{type(value).__name__}>"


class _LogFile:
    """A text stream that timestamps, redacts and appends whole lines."""

    def __init__(self, path: str, max_bytes: int = _MAX_BYTES):
        self.path = path
        self.max_bytes = max_bytes
        # Unfinished text per thread: print() writes its message and its
        # line end separately, and two threads' prints must never mix into
        # one block (a device-name tag would then shelter the other's words).
        self._pending: dict = {}
        self._dropping: set = set()
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
        me = threading.get_ident()
        with self._lock:
            if me in self._dropping:
                # The rest of a print already dropped for its size: its
                # closing quote may be in here, so none of it is kept.
                if text.endswith("\n"):
                    self._dropping.discard(me)
                return len(text)
            block = self._pending.pop(me, "") + text
            if not block.endswith("\n"):
                # Wait for the line end, so a message with line breaks in it
                # is redacted whole, never one half-quoted line at a time.
                if len(block) <= _MAX_PENDING:
                    self._pending[me] = block
                    return len(text)
                self._dropping.add(me)
                block = f"<{len(block)} chars with no line end dropped>\n"
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            out = "".join(f"[{stamp}] {l}\n"
                          for l in redact(block).split("\n") if l.strip())
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
