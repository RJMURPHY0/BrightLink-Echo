"""
Fire-and-forget error reporter: sends errors to FTC Contacts Feedback & Reports page.
Reads ftc_contacts_api_url and ftc_contacts_secret from config.json.
Never raises; a failed send is printed (to the app log in frozen builds).
"""

import json
import os
import threading
import urllib.request


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
