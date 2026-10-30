"""
speech_health — turn a silent speech-engine failure into a visible, logged,
recoverable one.

The app brings its speech engines up in the background *after* the window is
already on screen: Parakeet (ONNX) is primary, faster-whisper is the fallback
(see app.py `_preload_parakeet`). Three things break that load on real
machines, and before this module every one of them was a bare `print()` into a
`console=False` build — so the UI looked perfectly healthy and dictation did
nothing, with nothing on screen or in the logs to say why:

  * antivirus quarantines a native runtime DLL (onnxruntime / ctranslate2),
    so `import onnxruntime` / `import faster_whisper` fails;
  * antivirus quarantines or deletes the downloaded ~660 MB model after it
    lands, so the load finds nothing to load;
  * a firewall or AV blocks the one-time model download from huggingface.co.

This module does ONE thing: given the text of a load/download failure and
whether the model files are on disk, it names the single most likely cause in
plain English and hands back a short message + fix hint the UI can show and the
fleet error log can record. It never raises, never touches the engines, and
never transcribes — app.py owns the wiring to the toast, the tray and the
error-events log, exactly like `hallucination.set_reporter` and friends.

Cause codes are logged and may be matched in the error-events dashboard, so
they are short and STABLE: never rename one, only add a new code.
"""

import re

import brand

# ── Cause codes (stable; logged) ─────────────────────────────────────────────
OK = "ok"
# A native runtime DLL could not be imported — the classic antivirus-quarantine
# signature, and the one that produces "the UI is there but nothing happens".
RUNTIME_BLOCKED = "runtime_blocked"
# The model files were present but the load still failed, or a finished download
# failed its hash: something altered or removed them after they landed.
MODEL_BLOCKED = "model_blocked"
# The one-time model download could not complete (network/firewall/AV).
DOWNLOAD_BLOCKED = "download_blocked"
# First run, model simply not downloaded yet. Benign and transient — the
# background download is still working — so this is NOT treated as "blocked".
MODEL_MISSING = "model_missing"
# A load/download failed for a reason none of the above explain.
UNKNOWN = "unknown"

# Causes that mean the user cannot dictate and should be told. MODEL_MISSING is
# excluded on purpose: the first-run download is in flight and whisper or a
# retry will take over on its own.
_BLOCKING = (RUNTIME_BLOCKED, MODEL_BLOCKED, DOWNLOAD_BLOCKED, UNKNOWN)

# A failed native import looks like one of these on Windows. Matching is done
# case-insensitively against the exception text. "DLL load failed" and the
# WinError numbers are what a quarantined or deleted runtime DLL raises;
# "no module named" / "cannot import" cover a wholesale removal of the package.
_RUNTIME_SIGNS = (
    "dll load failed",
    "winerror 126",            # the specified module could not be found
    "winerror 127",            # the specified procedure could not be found
    "winerror 1114",           # a dynamic link library initialization failed
    "the specified module could not be found",
    "the specified procedure could not be found",
    "no module named 'onnxruntime",
    "no module named 'onnx_asr",
    "no module named 'ctranslate2",
    "no module named 'faster_whisper",
    "onnxruntime_pybind11_state",
    "cannot import name",
)

# Windows' own words for "antivirus stopped this": ERROR_VIRUS_INFECTED (225)
# when a scanner blocks opening a file, ERROR_VIRUS_DELETED (226) when it has
# removed it. These are the ONLY codes read as antivirus for certain. 2 (file
# not found), 5 (access denied) and 193 (bad image) have everyday causes too
# (a half-finished update, a locked file, a 32-bit DLL) and are never listed
# here (audit 2026-10-28).
_ANTIVIRUS_SIGNS = (
    "winerror 225",
    "winerror 226",
    "contains a virus",
    "potentially unwanted software",
)

# A download failure that smells like the network/firewall rather than the file
# being altered. Used only to word the hint; the cause stays DOWNLOAD_BLOCKED.
_NETWORK_SIGNS = (
    "urlerror",
    "timed out",
    "timeout",
    "getaddrinfo",
    "connection",
    "ssl",
    "certificate",
    "http error",
    "name or service not known",
    "failed to establish",
    "network is unreachable",
    "refused",
)

# A download failure that smells like the bytes being tampered with (antivirus
# stripping or rewriting the file mid-flight shows up as a hash/size mismatch).
_TAMPER_SIGNS = (
    "sha-256",
    "sha256",
    "discarded",
    "truncated",
)


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _matches(text: str, signs) -> bool:
    low = _norm(text)
    return any(s in low for s in signs)


def classify_load_error(exc_text, files_present: bool) -> str:
    """Name the cause of an engine LOAD failure.

    exc_text    the text of the exception the load raised (any object; str()'d).
    files_present  whether the model files are on disk right now.

    A runtime-DLL signature wins regardless of the files — a quarantined
    onnxruntime cannot load any model. Otherwise, files on disk that still fail
    to load means the bytes are bad (altered/removed); no files means the
    first-run download simply has not finished yet.
    """
    if _matches(exc_text, _RUNTIME_SIGNS):
        return RUNTIME_BLOCKED
    if _matches(exc_text, _ANTIVIRUS_SIGNS):
        # A file antivirus refused to open (225) or deleted (226). Not a
        # runtime DLL, so a model file; deleted means "not on disk" is no
        # first-run download, and must not read as benign MODEL_MISSING.
        return MODEL_BLOCKED
    if not files_present:
        return MODEL_MISSING
    if _norm(exc_text):
        return MODEL_BLOCKED
    return UNKNOWN


def classify_download_error(err_text) -> str:
    """Name the cause of a model DOWNLOAD failure. Always a blocking cause:
    the download is the one-time step that makes offline dictation possible, so
    a failure here always deserves to be seen."""
    return DOWNLOAD_BLOCKED


def download_error_is_tamper(err_text) -> bool:
    """True when a download failure looks like the file being altered (hash or
    size mismatch) rather than a plain network failure — worth saying, because
    the fix is an antivirus exclusion, not 'check your wifi'."""
    return _matches(err_text, _TAMPER_SIGNS) and not _matches(err_text, _NETWORK_SIGNS)


def is_antivirus_error(exc_text) -> bool:
    """True only when Windows itself said antivirus blocked or removed the
    file (WinError 225/226). Everything else is at most "likely"."""
    return _matches(exc_text, _ANTIVIRUS_SIGNS)


def is_blocked(cause: str) -> bool:
    """True when the cause means the user cannot dictate and should be told."""
    return cause in _BLOCKING


def message_for(cause: str, *, download_tamper: bool = False) -> tuple[str, str]:
    """(headline, fix_hint) in plain English for a toast or tray notice.

    Deliberately blames nothing the user did and names antivirus as the usual
    culprit without accusing a specific product — the same cause shows up under
    Defender, Avast, AVG and others. Short enough for a one-line toast.
    """
    product = brand.PRODUCT_NAME
    if cause == RUNTIME_BLOCKED:
        return (
            f"{product} can't start speech recognition on this PC.",
            "Your antivirus has most likely quarantined one of the speech "
            f"engine files. Restore it (or allow {product}) and restart, see "
            "the error report for the exact file.",
        )
    if cause == MODEL_BLOCKED:
        return (
            f"{product}'s speech model is missing or was changed.",
            "Antivirus may have removed or altered the downloaded model. "
            f"Allow {product} in your antivirus; it will re-download the model "
            "automatically.",
        )
    if cause == DOWNLOAD_BLOCKED:
        if download_tamper:
            return (
                f"{product} couldn't finish downloading its speech model.",
                "The download kept arriving damaged, usually antivirus "
                f"scanning the file. Allow {product} (or huggingface.co) and it "
                "will retry on its own.",
            )
        return (
            f"{product} couldn't download its speech model.",
            "Check the internet connection, or allow this app through your "
            "firewall/antivirus. It keeps retrying in the background.",
        )
    if cause == MODEL_MISSING:
        return (
            f"{product} is still downloading its speech model.",
            "Dictation works on the backup engine until it's ready.",
        )
    return (
        f"{product} couldn't start speech recognition.",
        "Please send an error report so we can see what's being blocked.",
    )


def log_detail(cause: str, *, engine: str = "", exc_text: str = "",
               files_present=None, download_tamper: bool = False) -> dict:
    """The structured payload for the fleet error log. Carries the cause, the
    engine, and a trimmed, lower-cased signature of the failure — never the
    user's speech, so it is safe to send without Cloud Sync. The raw exception
    text is a runtime/library string (DLL names, module names), not content."""
    detail = {"cause": cause, "engine": engine or ""}
    sig = _norm(exc_text)
    if sig:
        detail["signature"] = sig[:300]
        detail["antivirus"] = is_antivirus_error(sig)
    if files_present is not None:
        detail["files_present"] = bool(files_present)
    if cause == DOWNLOAD_BLOCKED:
        detail["tamper"] = bool(download_tamper)
    return detail
