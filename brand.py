"""
Product identity: every name this app shows, and every name it must never change.

DISPLAY names are what people see: window titles, the tray, notifications,
shortcuts, the Installed apps entry, the exe's Properties and the download
file. Renaming the product is an edit to that block and nothing else.
Installed copies pick a new name up on their next auto-update: shortcuts and
the Installed apps entry are re-registered from these values on every launch
(app_install.register), and the first launch after a rename says so
(app.py _announce_update_if_any).

FROZEN identifiers are plumbing that installed copies, other apps and the
auto-updater find by name. They keep their original "FTC Whisper" values on
purpose:
  * the data folders hold the ~660 MB model, the encrypted session, history
    and recordings, and every version looks for them by name;
  * taskbar pins point at the canonical exe path;
  * every installed updater downloads UPDATE_ASSET from GITHUB_REPO, and the
    BrightLink CRM links to that asset, opens URL_SCHEME and calls the local
    server;
  * the mutex, the logon task and the registry keys are how a new version
    finds what an older one left behind.
Changing any of them strands existing installs. tests/test_brand.py pins them.

Nothing is imported from the project here: the PyInstaller spec, the
uninstaller and app.py's pre-import startup guard all read this module.
"""

# ── Display: change these to rename the product ─────────────────────────────

PRODUCT_NAME = "BrightLink Echo"

# The product's own name, as the BrightLink | Echo lockup and the post-dictation
# badge show it (the text fallback when the artwork in assets/brand cannot load).
PRODUCT_SHORT_NAME = "Echo"

# The window's title bar (and the taskbar's hover text): the company, then the
# product. Shortcuts, Installed apps and the exe keep PRODUCT_NAME.
WINDOW_TITLE = "BrightLink - " + PRODUCT_SHORT_NAME

# The registered legal name, exactly as Companies House shows it (company
# 17459281): Publisher in Installed apps and CompanyName in the exe's
# Properties. Keep it identical to the name on the code-signing certificate.
COMPANY_NAME = "BRIGHTLINK (OS) LTD"

SHORTCUT_DESCRIPTION = "Push-to-talk dictation for Windows"

# "More information" and support links in Installed apps.
WEBSITE_URL = "https://brightlink.io"

# Every name the product has shipped under before, oldest first. Anything that
# finds a shortcut, a launcher or a history row by name must accept these too.
LEGACY_PRODUCT_NAMES = ("FTC Whisper",)

# The file people download: "BrightLink Echo" gives "BrightLink-Echo.exe".
DOWNLOAD_ASSET = "-".join(PRODUCT_NAME.split()) + ".exe"


# ── Frozen: never change these (see the module docstring) ───────────────────

DATA_DIR_NAME = "FTC Whisper"             # %LOCALAPPDATA%\<this>, %APPDATA%\<this>
EXE_BASENAME = "FTC Whisper"              # PyInstaller name=, so dist\FTC Whisper.exe
CANONICAL_EXE_NAME = EXE_BASENAME + ".exe"  # the installed exe every launcher targets
MUTEX_NAME = "Global\\FTC_Whisper_SingleInstance"
TASK_NAME = "FTC Whisper"                 # Task Scheduler logon task
RUN_VALUE_NAME = "FTC Whisper"            # HKCU Run fallback launcher
URL_SCHEME = "ftcwhisper"                 # the CRM opens ftcwhisper://launch
UNINSTALL_KEY_NAME = "FTCWhisper"         # HKCU ...\Uninstall\<this>
UPDATE_ASSET = "FTC-Whisper.exe"          # what every installed updater downloads
GITHUB_REPO = "RJMURPHY0/FTC_Whisper"
HTTP_USER_AGENT = "FTC-Whisper"
UPDATER_USER_AGENT = "FTC-Whisper-Updater/1.0"
# The name every build shipped under before builds recorded their own name
# (last-product-name.txt). An update from one of those announces a rename from
# this, whatever LEGACY_PRODUCT_NAMES grows into later.
UNRECORDED_PRODUCT_NAME = "FTC Whisper"


def product_names() -> tuple:
    """The current display name first, then every older one, without repeats."""
    names = []
    for name in (PRODUCT_NAME,) + tuple(reversed(LEGACY_PRODUCT_NAMES)):
        if name and name not in names:
            names.append(name)
    return tuple(names)


def version_strings(year: int) -> dict:
    """The name strings in the exe's version resource: Explorer's Properties,
    Task Manager and the Windows microphone prompt all read these."""
    return {
        "CompanyName": COMPANY_NAME,
        "FileDescription": PRODUCT_NAME,
        "InternalName": "".join(PRODUCT_NAME.split()),
        "LegalCopyright": f"Copyright {year} {COMPANY_NAME}. All rights reserved.",
        # The file the resource is attached to, which is the installed exe.
        "OriginalFilename": CANONICAL_EXE_NAME,
        "ProductName": PRODUCT_NAME,
        "LegalTrademarks": f"{PRODUCT_NAME} is a trademark of {COMPANY_NAME}.",
    }


def render_version_info(template: str, year: int) -> str:
    """version_info.txt with its name strings taken from this module.

    The version NUMBERS are left exactly as written. Bumping them stays the
    manual release step CLAUDE.md describes; only the names come from here.
    Raises if a name string is missing, so the build fails instead of shipping
    an exe that still carries an old name.
    """
    import re

    out = template
    for key, value in version_strings(year).items():
        pattern = re.compile(r"(StringStruct\('" + re.escape(key) + r"',\s*)'[^']*'")
        if not pattern.search(out):
            raise ValueError(f"version_info.txt has no {key} string")
        literal = "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
        out = pattern.sub(lambda m: m.group(1) + literal, out, count=1)
    return out
