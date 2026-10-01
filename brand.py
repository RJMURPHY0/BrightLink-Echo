"""
Product identity: every name this app shows, and every name it must never change.

DISPLAY names are what people see: window titles, the tray, notifications,
shortcuts, the Installed apps entry, the exe's Properties and the download
file. Renaming the product is an edit to that block and nothing else.
Installed copies pick a new name up on their next auto-update: shortcuts and
the Installed apps entry are re-registered from these values on every launch
(app_install.register), and the first launch after a rename says so
(app.py _announce_update_if_any).

ON-DISK names (folders, exe, launchers, registry keys, mutex) moved from the
old product name to the current one in v1.8.1, and installed copies moved
with them: installer/activate.ps1 renames the old folders during the update
(and puts them back if anything fails), and every launch replaces the old
launchers and registry entries (app_install.register). The old values stay in
the LEGACY block only so migration and clean-up can find what an older
version left behind. data_paths.py picks the folder a machine really uses.

FROZEN identifiers are plumbing that older copies, other apps and the
auto-updater find by name, so they never change:
  * every pre-1.8 updater downloads UPDATE_ASSET from GITHUB_REPO, and v1.8.0
    copies download LEGACY_SETUP_UPDATE_ASSET and LEGACY_ROLLOUT_ASSET, so all
    three stay published on every release;
  * the BrightLink CRM opens LEGACY_URL_SCHEME (both schemes are registered);
  * taskbar pins group under APP_USER_MODEL_ID;
  * SmartScreen reputation is bound to SIGNER_SUBJECT.
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


# ── On-disk identity (moved from the LEGACY names below in v1.8.1) ──────────

DATA_DIR_NAME = "BrightLink Echo"         # %LOCALAPPDATA%\<this>, %APPDATA%\<this>
EXE_BASENAME = "BrightLink Echo"          # PyInstaller name=, so dist\BrightLink Echo.exe
CANONICAL_EXE_NAME = EXE_BASENAME + ".exe"  # the installed exe every launcher targets
MUTEX_NAME = "Global\\BrightLink_Echo_SingleInstance"
TASK_NAME = "BrightLink Echo"             # logon task: the early sign-in launcher
RUN_VALUE_NAME = "BrightLink Echo"        # HKCU Run entry: what Task Manager lists
URL_SCHEME = "brightlinkecho"             # brightlinkecho://launch
UNINSTALL_KEY_NAME = "BrightLinkEcho"     # HKCU ...\Uninstall\<this>
SETUP_MUTEX = "BrightLinkEchoSetup"       # the installer's own single-instance mutex
FILE_SLUG = "brightlink_echo"             # temp scripts and logs the updater writes
# Written into the new local data folder once the legacy one has moved into it
# (installer/activate.ps1). Its presence makes the new folder authoritative
# even if a locked leftover of the old one survived.
MIGRATED_MARKER = "migrated.json"

# ── Legacy on-disk identity: what v1.8.0 and older left behind ──────────────
# Read only by migration, clean-up and the pre-1.8 onefile bridge (which runs
# inside the legacy folder until the rollout moves it). Never name anything new
# after these.

LEGACY_DATA_DIR_NAME = "FTC Whisper"
LEGACY_EXE_BASENAME = "FTC Whisper"
LEGACY_CANONICAL_EXE_NAME = LEGACY_EXE_BASENAME + ".exe"
LEGACY_MUTEX_NAME = "Global\\FTC_Whisper_SingleInstance"
LEGACY_TASK_NAME = "FTC Whisper"
LEGACY_RUN_VALUE_NAME = "FTC Whisper"
LEGACY_URL_SCHEME = "ftcwhisper"          # the CRM still opens ftcwhisper://launch
LEGACY_UNINSTALL_KEY_NAME = "FTCWhisper"
LEGACY_SETUP_MUTEX = "FTCWhisperSetup"
LEGACY_FILE_SLUG = "ftc_whisper"

# ── Frozen: never change these (see the module docstring) ───────────────────

UPDATE_ASSET = "FTC-Whisper.exe"          # what every pre-1.8 updater downloads
# From v1.8.0 UPDATE_ASSET is the "bridge": a whole onefile app that every
# pre-1.8 updater can still install, and that then moves the machine to the
# installed (onedir) layout. Installed copies update through the installer.
SETUP_UPDATE_ASSET = "BrightLink-Echo-Setup.exe"   # the installer, as v1.8.1+ fetches it
ROLLOUT_ASSET = "BrightLink-Echo-rollout.json"     # how much of the fleet the bridge may migrate
# The same two files under the names v1.8.0 copies fetch. CI publishes them on
# every release for as long as a v1.8.0 copy may still be out there.
LEGACY_SETUP_UPDATE_ASSET = "FTC-Whisper-Setup.exe"
LEGACY_ROLLOUT_ASSET = "FTC-Whisper-rollout.json"
# The installed layout: <DATA_DIR>\<CANONICAL_EXE_NAME> runs on
# <DATA_DIR>\app-<version>\ (PyInstaller contents_directory). An update is laid
# out in pending-<version>\ first and only then moved into place.
CONTENTS_DIR_PREFIX = "app-"
PENDING_DIR_PREFIX = "pending-"
# Every exe we ship is signed by exactly this certificate subject. SmartScreen
# reputation is bound to it, and the updater refuses an installer signed by
# anything else.
SIGNER_SUBJECT = ("CN=BRIGHTLINK (OS) LTD, O=BRIGHTLINK (OS) LTD, L=Syston, "
                  "S=Leicester, C=GB")
# Windows groups the taskbar button, pins and notifications under this id.
# Its visible name comes from HKCU\Software\Classes\AppUserModelId\<this>
# (app_install.register_notification_identity), so it never needs to change,
# and changing it would split every existing taskbar pin into a second button.
APP_USER_MODEL_ID = "FTC.Whisper"
# Renamed from RJMURPHY0/FTC_Whisper on 2026-09-22. Builds up to v1.6.86 still
# ask for the old name and reach this repo through GitHub's redirect, which
# lasts only while nothing else is ever called FTC_Whisper on this account.
GITHUB_REPO = "RJMURPHY0/BrightLink-Echo"
HTTP_USER_AGENT = "BrightLink-Echo"
UPDATER_USER_AGENT = "BrightLink-Echo-Updater/1.0"
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
