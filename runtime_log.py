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
# Every character RFC 5322 allows before the @, apostrophes (straight and
# curly) included, so no "o'" or "a#" of an address stays behind (issue #4).
_EMAIL = re.compile(r"[\w.!#$%&'’*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")
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
    m = _TAG.match(text)
    if m and m.group(1) in _KEEP_QUOTES:
        pass
    elif _FRAME.match(text):
        text = "\n".join(_hide_quoted(line) for line in text.split("\n"))
    else:
        text = _hide_quoted(text)
    # Last: an address can now start with a quote mark, and masking it first
    # would take that mark from the quoted words it opens.
    return _EMAIL.sub("<email>", text)


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


_installed = None   # the _LogFile install() put on stdout/stderr, if any


def install(path: str) -> bool:
    """Send stdout/stderr to the log when the process has no console.
    Returns True when installed. A console run (run.bat, tests) is left
    alone so developers keep seeing output live."""
    global _installed
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
    _installed = stream
    return True


# ---------------------------------------------------------------------------
# Identifiers in auth-restore.log
# ---------------------------------------------------------------------------

def mask_email(email) -> str:
    """An address as auth-restore.log may hold it: its first character and
    its domain ("r***@example.com"), enough to tell two accounts apart."""
    email = str(email or "").strip()
    local, at, domain = email.partition("@")
    if not at or not local:
        return "<email>" if email else "<none>"
    return f"{local[0]}***@{domain}"


def mask_identifiers(text: str) -> str:
    """Tokens and keys hidden, email addresses masked (see mask_email)."""
    for pattern in _SECRETS:
        if pattern.groups:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", text)
        else:
            text = pattern.sub("<redacted>", text)
    return _EMAIL.sub(lambda m: mask_email(m.group(0)), text)


# ---------------------------------------------------------------------------
# Scrubbing logs written by v1.8.12 and earlier
# ---------------------------------------------------------------------------
# Those builds redacted line by line and ended a quoted span at the first
# apostrophe, so their echo.log can hold dictated words: the tail after a
# contraction ("<2 chars>s fine, don<16 chars>"), every line of a multi-line
# dictation but the last, an unquoted sign-off name, and email addresses.
# scrub_old_logs() rewrites those files once per install, streaming them so a
# big file never sits in memory, through redact() per block plus the stricter
# rules below for what the old redaction left behind.

SCRUB_MARKER = "logs_scrubbed_v2"
# A file bigger than this is deleted, not rewritten: the live writer keeps
# echo.log near _MAX_BYTES, so only a damaged file gets here.
_SCRUB_MAX_BYTES = 32 * 1024 * 1024
_ECHO_LOG_NAME = re.compile(r"^echo\.log(?:\.\d+)?$", re.IGNORECASE)
_STAMP = re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] ")
_MARK = r"<\d+ chars>"
_Q = re.escape(_QUOTE_MARKS)
# A traceback frame as the old redaction left it: its quoted path became a
# length marker.
_OLD_FRAME = re.compile(rf'^\s*File (?:"|{_MARK})')
# Lines that open a traceback: never a further line of the print above them.
_TRACEBACK_START = re.compile(
    r"^(?:Traceback \(most recent call last\):"
    r"|During handling of the above exception"
    r"|The above exception was the direct cause)")
# What the old redaction left: from the first quote mark or length marker to
# the last one ("<2 chars>s fine, don<16 chars>"), then a quote mark whose
# partner the old pattern swallowed, to the end of the block.
_RESIDUE = re.compile(f"(?:[{_Q}]|{_MARK}).*(?:[{_Q}]|{_MARK})", re.DOTALL)
_LONE_QUOTE = re.compile(f"[{_Q}].*", re.DOTALL)
_IN_WORD_APOSTROPHE = re.compile(r"[^\W\d_]['’][^\W\d_]")
_MARK_NUM = re.compile(r"<(\d+) chars>")
# Old prints that held user text with no quotes round it.
_OLD_UNQUOTED = re.compile(r"^(\s*\[App\] Email sign-off name: )(.+)", re.DOTALL)
# A block with none of these needs no work (most diagnostic lines).
_SUSPECT = re.compile(
    f"[{_Q}<@]|eyJ|sb_|sk-|token|password|api_?key", re.IGNORECASE)


class _ChangedMeanwhile(Exception):
    """The file was rotated or trimmed during the scrub; try next launch."""


def _hidden_length(span: str) -> int:
    """The original length of a collapsed span, as near as can be told."""
    hidden = sum(int(n) + 2 for n in _MARK_NUM.findall(span))
    return max(0, hidden + len(_MARK_NUM.sub("", span)) - 2)


def _hide_residue(text: str) -> str:
    text = _RESIDUE.sub(lambda m: f"<{_hidden_length(m.group(0))} chars>", text)
    # Now at most one quote mark or marker is left. One apostrophe inside a
    # word on a line of its own ("[App] Couldn't open the mic") is program
    # text: every old print of dictation opened its quote, which shows here
    # as a marker or a quote mark that does not sit inside a word.
    if "\n" not in text and _IN_WORD_APOSTROPHE.search(text):
        return text
    return _LONE_QUOTE.sub(lambda m: f"<{len(m.group(0)) - 1} chars>", text)


def _scrub_old_block(text: str, kind: str) -> str:
    """One block of an old log (a print, as near as the file can show it),
    through redact() and then the stricter rules for old leftovers."""
    if kind == "frame":
        # A traceback frame and its source line: program text, kept per line
        # so the line number stays readable.
        return "\n".join(_hide_residue(redact(line)) for line in text.split("\n"))
    head, nl, rest = text.partition("\n")
    m = _TAG.match(head)
    if m and m.group(1) in _KEEP_QUOTES:
        # Device and hotkey names keep their quotes. A line under them was
        # never part of such a name, so it gets the strict rules.
        return redact(head) + nl + (_scrub_old_block(rest, "plain") if rest else "")
    text = _OLD_UNQUOTED.sub(lambda u: f"{u.group(1)}<{len(u.group(2))} chars>", text)
    if not _SUSPECT.search(text):
        return text
    return _hide_residue(redact(text))


def _old_blocks(lines):
    """Group an old log's lines into blocks and yield them scrubbed.

    The old writer stamped every line, even the lines of one multi-line
    print, so a block is a tagged line ("[App] ...") with the untagged lines
    after it. A traceback frame and its source line make a block of their
    own; any other untagged line after them starts a fresh, strict block."""
    stamp, kind, parts, size, dropped = "", "", [], 0, False

    def flush():
        if dropped:
            return f"{stamp}<{size} chars in one block dropped>\n"
        if not parts:
            return ""
        out = _scrub_old_block("\n".join(parts),
                               "frame" if kind.startswith("frame") else kind)
        return "".join(f"{stamp}{line}\n" for line in out.split("\n")
                       if line.strip())

    for raw in lines:
        line = raw.rstrip("\r\n")
        m = _STAMP.match(line)
        line_stamp, content = (m.group(0), line[m.end():]) if m else ("", line)
        if _TAG.match(content):
            new_kind = "tagged"
        elif _FRAME.match(content) or _OLD_FRAME.match(content):
            new_kind = "frame"
        elif _TRACEBACK_START.match(content):
            new_kind = "plain"
        elif kind == "frame":
            new_kind, kind = None, "frame-done"   # the frame's source line
        elif kind in ("tagged", "plain"):
            new_kind = None                       # more of the same print
        else:
            new_kind = "plain"
        if new_kind is not None:
            yield flush()
            stamp, kind, parts, size, dropped = line_stamp, new_kind, [], 0, False
        size += len(content) + 1
        if dropped or size > _MAX_PENDING:
            # As the live writer does: a block this big is dropped whole,
            # never split (its closing quote could be anywhere in it).
            dropped, parts = True, []
            continue
        parts.append(content)
    yield flush()


def _rewrite(path: str, scrub, lock=None) -> str:
    """Rewrite *path* through scrub(text lines) -> text chunks, atomically:
    into a temp file beside it, then os.replace. Returns "rewritten" or
    "deleted".

    Safe alongside a live writer that appends whole lines under *lock*: the
    file is streamed without the lock, then, holding it, whatever was appended
    meanwhile (already redacted by that writer) is copied across unchanged and
    the temp file replaces the original. A file rotated or trimmed meanwhile
    is left alone and _ChangedMeanwhile raised, so the next launch retries."""
    first = os.stat(path)
    if first.st_size > _SCRUB_MAX_BYTES:
        if lock is not None:
            with lock:
                os.remove(path)
        else:
            os.remove(path)
        return "deleted"
    tmp = path + ".scrub-tmp"
    try:
        done = 0
        with open(path, "rb") as src, open(tmp, "w", encoding="utf-8") as dst:
            def text_lines():
                nonlocal done
                for raw in src:
                    if not raw.endswith(b"\n"):
                        break        # a line still being written: the tail
                    done += len(raw)
                    yield raw.decode("utf-8", errors="replace")
            for chunk in scrub(text_lines()):
                if chunk:
                    dst.write(chunk)
        with (lock if lock is not None else threading.Lock()):
            now = os.stat(path)
            if ((now.st_ino, now.st_dev) != (first.st_ino, first.st_dev)
                    or now.st_size < done):
                raise _ChangedMeanwhile()
            if now.st_size > done:
                with open(path, "rb") as src, open(tmp, "ab") as dst:
                    src.seek(done)
                    while True:
                        block = src.read(1024 * 1024)
                        if not block:
                            break
                        dst.write(block)
            os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass   # the original error below is what the caller records
        raise
    return "rewritten"


def scrub_echo_log(path: str, lock=None) -> str:
    """Rewrite one echo.log (or a rotated echo.log.1) without dictated text."""
    return _rewrite(path, _old_blocks, lock)


def _restore_lines(lines):
    for line in lines:
        yield mask_identifiers(line.rstrip("\r\n")) + "\n"


def scrub_restore_log(path: str, lock=None) -> str:
    """Rewrite auth-restore.log with email addresses masked and tokens hidden."""
    return _rewrite(path, _restore_lines, lock)


def scrub_old_logs(folders, marker_dir: str, restore_name: str = "auth-restore.log",
                   restore_lock=None) -> dict:
    """Once per install: rewrite every echo.log, rotated echo.log.N and
    auth-restore.log in *folders* (the current and the legacy data folder;
    a folder that does not exist is skipped, never created), then write
    SCRUB_MARKER in *marker_dir*. With the marker there it does nothing.

    Never raises. A file that fails is counted and its error kept by type
    only (a message can carry a path with the user's name); the marker is
    then not written, so the next launch tries again. Safe alongside the live
    echo.log writer (its lock, see _rewrite) and, given *restore_lock*, the
    auth-restore.log writer. Prints nothing: the caller logs the result."""
    result = {"rewritten": 0, "deleted": 0, "errors": [], "skipped": False}
    try:
        marker = os.path.join(marker_dir, SCRUB_MARKER)
        if os.path.exists(marker):
            result["skipped"] = True
            return result
        seen = set()
        for folder in folders:
            key = os.path.normcase(os.path.abspath(folder))
            if key in seen or not os.path.isdir(folder):
                continue
            seen.add(key)
            for name in sorted(os.listdir(folder)):
                path = os.path.join(folder, name)
                low = name.lower()
                if low.endswith(".scrub-tmp"):
                    # Left by a scrub that was cut off: only scrubbed text.
                    try:
                        os.remove(path)
                    except OSError as e:
                        result["errors"].append(type(e).__name__)
                    continue
                if _ECHO_LOG_NAME.match(name):
                    job = scrub_echo_log
                    lock = _installed._lock if _installed is not None else None
                elif low == restore_name.lower():
                    job, lock = scrub_restore_log, restore_lock
                else:
                    continue
                if not os.path.isfile(path):
                    continue
                try:
                    result[job(path, lock)] += 1
                except Exception as e:
                    result["errors"].append(type(e).__name__)
        if not result["errors"]:
            os.makedirs(marker_dir, exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S\n"))
    except Exception as e:
        result["errors"].append(type(e).__name__)
    return result
