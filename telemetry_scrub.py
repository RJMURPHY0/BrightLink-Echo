"""What leaves this PC in a diagnostics report (error_events).

Data minimisation for the fleet error log. A report keeps what fixes faults
and drops what identifies the person or their habits:

* Microphone names become a kind ("built-in array", "webcam", "headset").
  A Bluetooth mic is often named after its owner ("Sam's AirPods").
* The app being typed into becomes a category ("browser", "office"). Its
  name, exe and window class are never sent: together they are a record of
  which programs someone uses.
* A crash report's log tail has every microphone name, user folder and email
  address taken out.

Pure functions, stdlib and brand only: supabase_client calls scrub_event() on every
payload, so no caller can send a raw value by mistake.
"""

import re

import brand  # constants only, imports nothing

# ── microphones ──────────────────────────────────────────────────────────────
# First match wins, so the specific kinds come before the generic ones.
_DEVICE_KINDS = (
    ("virtual", ("stereo mix", "virtual", "cable output", "voicemeeter",
                 "broadcast", "krisp", "loopback", "what u hear")),
    ("headset", ("headset", "headphone", "airpods", "buds", "hands-free",
                 "handsfree", "bluetooth", " bt ", "jabra", "plantronics",
                 "poly ", "earphone", "wh-", "wf-")),
    ("webcam", ("webcam", "camera", " cam", "c920", "c922", "c930", "brio",
                "kiyo")),
    ("built-in array", ("array",)),
    ("usb mic", ("usb", "yeti", "rode", "shure", "at2020", "fifine",
                 "samson", "hyperx", "elgato wave", "blue ")),
    ("built-in", ("realtek", "conexant", "intel", "high definition",
                  "hd audio", "smart sound", "internal", "microphone (2-")),
    ("default", ("default", "primary sound", "sound mapper")),
)


def device_kind(name) -> str:
    """A microphone's kind, never its name. "" stays ""."""
    if not name:
        return ""
    low = f" {str(name).lower()} "
    for kind, needles in _DEVICE_KINDS:
        if any(n in low for n in needles):
            return kind
    return "other"


# ── the app being typed into ─────────────────────────────────────────────────
_APP_KINDS = (
    ("browser", ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi",
                 "arc.exe", "iexplore", "browser")),
    ("office", ("winword", "excel", "powerpnt", "outlook", "olk.exe",
                "onenote", "msaccess", "mspub", "wps", "soffice")),
    ("chat", ("teams", "slack", "discord", "whatsapp", "telegram", "signal",
              "zoom", "skype", "messenger")),
    ("code", ("code.exe", "cursor", "devenv", "pycharm", "idea64", "webstorm",
              "rider", "sublime", "notepad++", "windsurf", "zed")),
    ("terminal", ("windowsterminal", "cmd.exe", "powershell", "pwsh",
                  "conhost", "wt.exe", "mintty", "alacritty", "wezterm")),
    ("notes", ("notepad", "obsidian", "notion", "evernote", "wordpad",
               "stickynot")),
    ("windows", ("explorer.exe", "searchhost", "searchapp", "shellexperience",
                 "startmenuexperience", "applicationframehost")),
    # Echo itself, under every name it has had (brand.py owns them).
    ("echo", tuple(n.lower() for n in (brand.PRODUCT_NAME,) + tuple(
        brand.LEGACY_PRODUCT_NAMES)) + ("ftc-whisper",)),
)


def app_kind(app_exe: str = "", app_name: str = "") -> str:
    """The category of the app typed into, from its exe (or display name)."""
    low = f"{app_exe or ''} {app_name or ''}".strip().lower()
    if not low:
        return ""
    for kind, needles in _APP_KINDS:
        if any(n in low for n in needles):
            return kind
    return "other"


_WINDOW_FAMILIES = (
    ("chromium", ("chrome_widgetwin", "chrome_renderwidgethosthwnd")),
    ("office", ("opusapp", "xlmain", "pptframeclass", "rctrl_renwnd32",
                "framework::cframe", "_wwg", "excel7")),
    ("uwp", ("applicationframewindow", "windows.ui.core.corewindow")),
    ("console", ("consolewindowclass", "cascadia_hosting_window_class",
                 "pseudoconsolewindow")),
    ("edit", ("edit", "richedit", "scintilla", "notepad")),
    ("mozilla", ("mozillawindowclass",)),
)


def window_family(window_class: str) -> str:
    """The kind of text control, from a window class. Never the class."""
    low = (window_class or "").lower()
    if not low:
        return ""
    for family, needles in _WINDOW_FAMILIES:
        if any(n in low for n in needles):
            return family
    return "other"


# ── log tails ────────────────────────────────────────────────────────────────
_USER_DIR = re.compile(r"(?i)([a-z]:\\users\\)[^\\/\s'\"]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DEVICE_LIST = re.compile(r"(input device\(s\):\s*)(\[.*\])\s*$")
_QUOTED = re.compile(r"'([^'\n]*)'")
# The recorder always writes a stream's device name just before its rate:
# "(Headset (Sam AirPods), 16000 Hz" or "(warm, Headset (...), 16000 Hz".
_NAME_BEFORE_RATE = re.compile(r"\((warm, |recovered, )?([^\n]+?)(, \d+ Hz)")
_MIC_LINE = re.compile(r"\[(?:Recorder|Settings|Mic|MicAccess|Probe)\]")


def _names_in(lines) -> list:
    """Every microphone name the log itself mentions, longest first."""
    import ast
    names = set()
    for line in lines:
        if not _MIC_LINE.search(line):
            continue
        m = _DEVICE_LIST.search(line)
        if m:
            try:
                names.update(str(n) for n in ast.literal_eval(m.group(2)))
            except (ValueError, SyntaxError):
                pass
        names.update(q for q in _QUOTED.findall(line) if q)
        for m in _NAME_BEFORE_RATE.finditer(line):
            names.add(m.group(2))
    names.discard("<mic>")
    return sorted((n for n in names if len(n) >= 3), key=len, reverse=True)


def scrub_log_text(text: str) -> str:
    """A log tail with microphone names, user folders and emails removed."""
    if not text:
        return text
    text = _USER_DIR.sub(r"\1<user>", str(text))
    text = _EMAIL.sub("<email>", text)
    lines = text.splitlines()
    names = _names_in(lines)
    out = []
    for line in lines:
        if _MIC_LINE.search(line):
            line = _DEVICE_LIST.sub(r"\1[<mics>]", line)
            line = _QUOTED.sub("'<mic>'", line)
            line = _NAME_BEFORE_RATE.sub(r"(\1<mic>\3", line)
        # Safety net: a name the log mentioned anywhere is gone everywhere.
        for n in names:
            if n in line:
                line = line.replace(n, "<mic>")
        out.append(line)
    return "\n".join(out)


# ── the whole report ─────────────────────────────────────────────────────────
_DEVICE_KEYS = ("device", "switched_to", "from_device", "to_device")
_DEVICE_LIST_KEYS = ("devices", "candidates")
_LOG_KEYS = ("log_tail", "native_trace", "trace", "traceback")


def scrub_detail(detail):
    """A detail dict with device names as kinds and logs scrubbed. Only the
    top level holds device names (nested dicts such as the privacy-switch
    state use "device" for something else and are left alone)."""
    if not isinstance(detail, dict):
        return detail
    out = dict(detail)
    for k in _DEVICE_KEYS:
        if isinstance(out.get(k), str):
            out[k] = device_kind(out[k])
    for k in _DEVICE_LIST_KEYS:
        if isinstance(out.get(k), (list, tuple)):
            out[k] = [device_kind(v) if isinstance(v, str) else v for v in out[k]]
    # Injection failures name the foreground app and its window class.
    if "fg_exe" in out:
        out["fg_app_kind"] = app_kind(str(out.pop("fg_exe") or "").strip("?"))
    if "fg_class" in out:
        out["fg_window_family"] = window_family(str(out.pop("fg_class") or ""))
    for k in _LOG_KEYS:
        if isinstance(out.get(k), str):
            out[k] = scrub_log_text(out[k])
    # Any other text (exception messages, paths) loses user folders and emails.
    for k, v in list(out.items()):
        if isinstance(v, str) and k not in _LOG_KEYS:
            out[k] = _EMAIL.sub("<email>", _USER_DIR.sub(r"\1<user>", v))
    return out


def scrub_event(payload: dict) -> dict:
    """An error_events row ready to send: app name, exe and window class
    replaced by their category inside detail, device names by their kind."""
    out = dict(payload)
    exe = out.pop("app_exe", "") or ""
    name = out.pop("app_name", "") or ""
    cls = out.pop("window_class", "") or ""
    detail = out.get("detail")
    detail = dict(detail) if isinstance(detail, dict) else (
        {"message": str(detail)[:500]} if detail else {})
    kind = app_kind(exe, name)
    if kind:
        detail["app_kind"] = kind
    fam = window_family(cls)
    if fam:
        detail["window_family"] = fam
    out["detail"] = scrub_detail(detail)
    return out
