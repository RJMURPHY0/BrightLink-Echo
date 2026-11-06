"""
Fire-and-forget error reporter: sends errors to FTC Contacts Feedback & Reports page.
Reads ftc_contacts_api_url and ftc_contacts_secret from config.json.
Never raises; a failed send is printed (to the app log in frozen builds).
"""

import json
import os
import sys
import threading
import urllib.parse
import urllib.request

# Plain http is allowed only for a dev server on this machine.
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


def _safe_api_url(url: str) -> str:
    """The configured API origin, or "" (meaning the built-in one) when this is
    a shipped build or the value is not https (http on this machine is fine
    from source). A shipped build never sends reports to a config-set host."""
    url = (url or "").strip()
    if not url:
        return ""
    if getattr(sys, "frozen", False):
        print("[ErrorReporter] Ignoring ftc_contacts_api_url in a shipped build.")
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
        ok = bool(parts.hostname) and (
            parts.scheme == "https"
            or (parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS))
    except ValueError:
        ok = False
    if not ok:
        print(f"[ErrorReporter] Ignoring ftc_contacts_api_url={url!r}: it must be https.")
        return ""
    return url


def _load_contacts_config() -> tuple[str, str]:
    """Returns (api_url, secret) from config.json, or empty strings if missing."""
    try:
        # Use the writable config next to the exe (frozen) / script — reading
        # os.path.dirname(__file__) resolved to the read-only bundle dir in
        # PyInstaller builds, so user-edited values were ignored.
        from config import get_config_path
        config_path = get_config_path()
    except Exception:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("ftc_contacts_api_url", ""), cfg.get("ftc_contacts_secret", "")
    except Exception:
        return "", ""


def report_error(
    message: str,
    context: dict | None = None,
    user_email: str | None = None,
    token: str | None = None,
) -> None:
    """
    Report an error to FTC Contacts asynchronously.
    Safe to call from any thread; always returns immediately.

    token: the signed-in user's access token. Shipped builds carry no app
    secret, so without it nothing is sent; with it the BrightLink intake
    verifies the user and files the row under them. Pass it only for errors
    worth a row each (the intake is shared and rate limited), never for the
    routine "No speech detected" feedback.
    """
    def _send() -> None:
        api_url, secret = _load_contacts_config()
        api_url = _safe_api_url(api_url)
        if not (api_url and secret) and not token:
            return
        if not api_url:
            import brand
            api_url = brand.CRM_URL
        payload: dict = {
            "message": message,
            "source": "whisper",
            "context": context or {},
        }
        if user_email:
            payload["user_email"] = user_email
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["x-app-secret"] = secret
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            f"{api_url.rstrip('/')}/api/log-error",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"[ErrorReporter] Could not send error report: {e}")

    threading.Thread(target=_send, daemon=True).start()
