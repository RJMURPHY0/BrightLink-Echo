"""
Two-factor sign-in for the shared account.

Every second step is a Supabase TOTP factor (decided in the CRM, 2026-11-03),
so a finished step is a genuine aal2 session. The authenticator app needs only
Supabase: challenge + verify with the code the person types. Email, WhatsApp,
text and backup codes go through the CRM's `/api/auth/mfa` route, which sends
its own code and, once that is right, hands back the current TOTP for the
factor; Supabase's own verify then finishes the step.

The CRM's copy of these rules is `src/lib/mfa/factors.ts` and
`api/auth/mfa.ts`; keep the factor names in step with them.

Nothing here touches Tk, so it is all testable on its own.
"""

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Optional

API_PATH = "/api/auth/mfa"
_TIMEOUT = 20.0

# Factor friendly names the CRM gives its own kinds; anything else is an
# authenticator app the person named themselves.
FACTOR_NAME = {
    "email": "bl-email",
    "whatsapp": "bl-whatsapp",
    "sms": "bl-sms",
    "backup": "bl-backup",
}
BROWSER_PREFIX = "bl-browser:"

# The order methods are offered in: the one that needs no message first.
ORDER = ("app", "whatsapp", "sms", "email", "backup")
SENDS_CODE = ("email", "whatsapp", "sms")
RESEND_SECONDS = 30

KIND_NAME = {
    "app": "Authenticator app",
    "email": "Email me a code",
    "whatsapp": "WhatsApp me a code",
    "sms": "Text me a code",
    "backup": "Use a backup code",
}

NO_CONNECTION = "No connection. Check your internet and try again."
NOT_ACCEPTED = "That code was not accepted. Check it and try again."


class MfaError(Exception):
    """A failure whose message can be shown to the person as it is.

    `code` is the server's machine-readable reason when it gave one
    ("sharing_off", "no_server_factor", "rate_limited", ...), `status` the
    HTTP status (0 when the server was never reached)."""

    def __init__(self, message: str = "", code: str = "", status: int = 0):
        super().__init__(message)
        self.code = code or ""
        self.status = status


# ── Approve from the web app ─────────────────────────────────────────────────
# The person verifies once in an open, fully signed-in web app tab: Echo asks,
# the tab shows the request, and they pick the number Echo shows. Echo then
# collects the current code of a factor the server holds and verifies it with
# Supabase like any other. The claim the server hands back is the only thing
# that can collect the answer: it stays in memory, never on disk or in a log.

APPROVAL_APP = "echo"
APPROVAL_POLL_MS = 2000
APPROVAL_SECONDS = 120
# The person cannot use approvals at all: offer typed codes only, quietly.
APPROVAL_UNAVAILABLE = ("sharing_off", "no_server_factor")


def approval_unavailable(err) -> bool:
    """True when this person cannot approve from the web app at all, so the
    option should vanish quietly: switched off, no server-held factor, no
    two-factor to approve, or a web app too old to know the action (a 400
    with no reason code)."""
    code = getattr(err, "code", "")
    if code in APPROVAL_UNAVAILABLE:
        return True
    return getattr(err, "status", 0) == 400 and not code


def device_label() -> str:
    """How the request names this PC in the web app: Echo on RYAN-LAPTOP."""
    import brand
    import socket
    name = (os.environ.get("COMPUTERNAME") or "").strip()
    if not name:
        try:
            name = socket.gethostname().strip()
        except OSError:
            name = ""
    label = f"{brand.PRODUCT_SHORT_NAME} on {name}" if name else brand.PRODUCT_SHORT_NAME
    return label[:80]


def kind_of(friendly_name: Optional[str]) -> str:
    n = friendly_name or ""
    if n.startswith(BROWSER_PREFIX):
        return "browser"
    for kind, name in FACTOR_NAME.items():
        if n == name:
            return kind
    return "app"


def token_claims(token: Optional[str]) -> dict:
    """The JWT payload, unverified (the server checks it). {} if unreadable."""
    try:
        part = (token or "").split(".")[1]
        part += "=" * (-len(part) % 4)
        data = json.loads(base64.urlsafe_b64decode(part.encode("ascii")))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def token_aal(token: Optional[str]) -> str:
    return "aal2" if token_claims(token).get("aal") == "aal2" else "aal1"


def _field(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def verified_factors(user) -> list:
    return [f for f in (_field(user, "factors") or [])
            if _field(f, "status") == "verified"]


def owes_second_step(user, access_token: Optional[str]) -> bool:
    """True while a signed-in session still owes its second step: the account
    has a verified factor and this token is not aal2. Read from the session
    itself, so it needs no network call."""
    if not verified_factors(user):
        return False
    return token_aal(access_token) != "aal2"


def local_app_methods(user) -> list:
    """Authenticator-app methods known from the session alone, for when the
    CRM cannot be reached: an app code needs nothing but Supabase."""
    out = []
    for f in verified_factors(user):
        if _field(f, "factor_type", "totp") != "totp":
            continue
        if kind_of(_field(f, "friendly_name")) != "app":
            continue
        out.append({"factorId": str(_field(f, "id")), "kind": "app",
                    "label": _field(f, "friendly_name") or None,
                    "destination": None})
    return out


def usable_methods(methods: list, email_may_finish: bool) -> list:
    """The methods that can finish this sign-in, in the order to offer them.

    Trusted browsers belong to a browser, never to this app. Email may finish
    a sign-in only when the password was the first step (a reset link reaches
    the same mailbox), which the server reports as `emailMayFinish`."""
    keep = [m for m in methods
            if m.get("kind") in ORDER
            and (m.get("kind") != "email" or email_may_finish)]
    keep.sort(key=lambda m: ORDER.index(m["kind"]))
    return keep


def prompt(method: dict) -> str:
    kind = method.get("kind")
    dest = method.get("destination")
    if kind == "app":
        return "Enter the six-digit code from your authenticator app."
    if kind == "email":
        return f"We emailed a code to {dest or 'your email'}."
    if kind == "whatsapp":
        return f"We sent a code to WhatsApp on {dest or 'your phone'}."
    if kind == "sms":
        return f"We texted a code to {dest or 'your phone'}."
    return "Enter one of your backup codes."


def clean_code(kind: str, text: str) -> str:
    """What the code box keeps of what was typed or pasted."""
    if kind == "backup":
        return "".join(c for c in (text or "").upper()
                       if c.isascii() and (c.isalnum() or c == "-"))[:9]
    return "".join(c for c in (text or "") if c.isdigit())[:6]


def code_ready(kind: str, code: str) -> bool:
    if kind == "backup":
        return len([c for c in code if c.isalnum()]) == 8
    return len(code) == 6


def api_url() -> str:
    # Same origin as the AI relay, including its dev override rules: a
    # released build never sends the token anywhere but the real app.
    from ai_refiner import relay_url
    return relay_url() + API_PATH


def call(action: str, token: str, body: Optional[dict] = None) -> dict:
    """POST one action to the CRM's two-factor route as this session.
    Raises MfaError with a message fit to show."""
    if not token:
        raise MfaError("Your sign-in has ended. Sign in again.")
    payload = dict(body or {})
    payload["action"] = action
    req = urllib.request.Request(
        api_url(), data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except urllib.error.HTTPError as e:
        message, code = "", ""
        try:
            body = json.loads(e.read().decode("utf-8") or "{}")
            if isinstance(body, dict):
                message = str(body.get("error") or "")
                code = str(body.get("code") or "")
        except Exception:
            pass
        raise MfaError(message or f"Something went wrong ({e.code}). "
                                  "Try again.", code=code, status=e.code) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MfaError(NO_CONNECTION) from e
    except ValueError as e:
        raise MfaError("Something went wrong. Try again.") from e
