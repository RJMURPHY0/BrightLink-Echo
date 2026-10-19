"""
av_report — the user-side fix and the developer-side report for an antivirus
false positive.

speech_health names *why* speech is blocked; this module says *what to do about
it*. Two audiences:

  * the user, who can unblock themselves in seconds by allow-listing one
    folder in their antivirus — far faster than waiting for a vendor to clear
    the detection;
  * the developer, who needs a concrete report (version, OS, the blocked file
    signature, the folder in play) to submit to the vendors so the detection
    is cleared at source.

The one folder a user must allow-list is this machine's data folder, which
holds the exe, the unpack area and the model. It is resolved through
`data_paths` so it is always the folder THIS install actually uses — the
legacy folder on a machine that has not migrated, the current one otherwise —
never a name written here by hand (the CLAUDE.md naming invariant, and the
reason the old docs path went stale).

Pure and side-effect-free: app.py owns opening the folder, opening a vendor
form and sending the report. Never raises.
"""

import os
import platform

import brand
import data_paths

# Vendor false-positive submission forms, from docs/FALSE_POSITIVE_REPORTING.md.
# Microsoft/SmartScreen first — the big one on Windows — then Avast (the
# product users report most), then the rest. Submitting the file (or its
# SHA-256) as a false positive is what clears a detection for everyone.
VENDOR_FORMS = (
    ("Microsoft Defender / SmartScreen",
     "https://www.microsoft.com/en-us/wdsi/filesubmission"),
    ("Avast / AVG", "https://www.avast.com/false-positive-file-form.php"),
    ("Bitdefender",
     "https://www.bitdefender.com/consumer/support/answer/29358/"),
    ("Kaspersky", "https://opentip.kaspersky.com/"),
    ("Malwarebytes", "https://www.malwarebytes.com/false-positive"),
)


def allowlist_dirs() -> list:
    """Every data folder that might hold our files on THIS machine, newest
    first. Usually one; a machine mid-migration can briefly have the legacy
    folder too, and allow-listing both covers it. Only folders that exist are
    returned, so the user is never told to exclude a path that isn't there."""
    seen, out = set(), []
    for d in (data_paths.local_dir(),) + tuple(data_paths.all_local_dirs()):
        try:
            key = os.path.normcase(os.path.abspath(d))
        except Exception:
            key = d
        if key in seen:
            continue
        seen.add(key)
        if os.path.isdir(d):
            out.append(d)
    # Fall back to the computed primary even when nothing exists yet, so the
    # guidance is never empty.
    return out or [data_paths.local_dir()]


def primary_allowlist_dir() -> str:
    """The single folder to put in front of the user — the one this install
    uses for its exe, unpack area and model."""
    return allowlist_dirs()[0]


def fix_steps() -> list:
    """Plain-English steps that unblock the user themselves, in order."""
    folder = primary_allowlist_dir()
    product = brand.PRODUCT_NAME
    return [
        f"Open your antivirus (e.g. Avast, AVG, Windows Security) and add an "
        f"exclusion / allowed folder for:\n    {folder}",
        "If it quarantined a file, restore it from the antivirus's "
        "quarantine / virus chest.",
        f"Restart {product}. Speech recognition will set itself up again.",
    ]


def fix_message() -> str:
    """One compact block for a toast or dialog: the folder, then the steps."""
    lines = [f"Allow {brand.PRODUCT_NAME} in your antivirus, then restart it.",
             "", f"Folder to allow:\n{primary_allowlist_dir()}", ""]
    for i, step in enumerate(fix_steps(), 1):
        lines.append(f"{i}. {step}")
    return "\n".join(lines)


def vendor_form_urls() -> list:
    """(vendor name, submission URL) pairs for the developer to report to."""
    return list(VENDOR_FORMS)


def _os_label() -> str:
    try:
        return f"{platform.system()} {platform.release()} ({platform.version()})"
    except Exception:
        return "unknown"


def build_report(cause: str = "", detail: dict | None = None,
                 app_version: str = "") -> dict:
    """The structured false-positive report. Carries the version, OS, the
    blocked cause and its file signature, and the folder in play — everything
    a vendor submission or a support ticket needs, and nothing the user said.
    `detail` is the speech_health.log_detail payload (cause/engine/signature/
    files_present); only its non-speech fields are ever present there."""
    detail = dict(detail or {})
    return {
        "kind": "av_false_positive",
        "product": brand.PRODUCT_NAME,
        "app_version": app_version or "",
        "os": _os_label(),
        "cause": cause or detail.get("cause", ""),
        "engine": detail.get("engine", ""),
        "signature": detail.get("signature", ""),
        "files_present": detail.get("files_present"),
        "allowlist_dir": primary_allowlist_dir(),
        "github_repo": brand.GITHUB_REPO,
    }


def report_text(report: dict) -> str:
    """A human-readable rendering of build_report() for a support email body
    or a vendor form's notes field."""
    r = report or {}
    lines = [
        f"{r.get('product', brand.PRODUCT_NAME)} — antivirus false-positive report",
        "",
        f"Version:      {r.get('app_version') or 'unknown'}",
        f"OS:           {r.get('os') or 'unknown'}",
        f"Blocked:      {r.get('cause') or 'unknown'}",
    ]
    if r.get("engine"):
        lines.append(f"Engine:       {r['engine']}")
    if r.get("signature"):
        lines.append(f"Signature:    {r['signature']}")
    if r.get("files_present") is not None:
        lines.append(f"Model on disk: {r['files_present']}")
    lines += [
        f"Folder:       {r.get('allowlist_dir', '')}",
        f"Repository:   {r.get('github_repo', brand.GITHUB_REPO)}",
        "",
        "This is a legitimate, code-signed push-to-talk dictation app. "
        "Transcription runs locally on the user's PC; the speech engine was "
        "blocked from loading or downloading its model.",
    ]
    return "\n".join(lines)
