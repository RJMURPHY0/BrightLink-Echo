"""
FTC Whisper post-install script.
Called by install.bat after the venv and pip dependencies are ready.
  - Creates config.json from template if it does not exist
  - Generates logo.ico from the BrightLink chain mark (assets/brand)
  - Creates / updates the desktop shortcut
"""

import os
import shutil
import subprocess
import sys

import brand

APP_DIR = os.path.dirname(os.path.abspath(__file__))
NAME = brand.PRODUCT_NAME
_PS_NAME = NAME.replace("'", "''")  # inside PowerShell single quotes
PYTHON  = os.path.join(APP_DIR, "venv", "Scripts", "pythonw.exe")
APP_PY  = os.path.join(APP_DIR, "app.py")
LOGO_ICO = os.path.join(APP_DIR, "logo.ico")


def _banner(msg: str) -> None:
    print(f"\n  {msg}")


def setup_config() -> None:
    config  = os.path.join(APP_DIR, "config.json")
    example = os.path.join(APP_DIR, "config.example.json")
    if not os.path.exists(config):
        if os.path.exists(example):
            shutil.copy(example, config)
            print("  [OK] config.json created from template.")
            print()
            print("  *** Optional: open config.json to add your API keys ***")
            print("    anthropic_api_key  — enables AI text refinement")
            print("    supabase_url/key   — enables transcription history & sync")
        else:
            print("  [WARN] config.example.json not found — skipping config setup.")
    else:
        print("  [OK] config.json already present.")


def create_icon() -> str:
    """Build logo.ico from the BrightLink chain mark, through the same code
    that produced the shipped logo.ico / exe_icon.ico, so a source install
    and a release show the same icon."""
    try:
        import logo_cache
        if logo_cache.write_icon(LOGO_ICO):
            print("  [OK] logo.ico created.")
            return LOGO_ICO
        print("  [WARN] assets/brand/brightlink-mark.png not found; "
              "shortcut will use the default icon.")
    except Exception as e:
        print(f"  [WARN] Icon creation failed: {e}")
    return ""


def create_shortcut(icon_path: str) -> None:
    """Create (or replace) the desktop shortcut via PowerShell."""
    icon_loc = f"{icon_path},0" if icon_path else f"{PYTHON},0"

    ps = (
        "$sh = New-Object -ComObject WScript.Shell; "
        "$d  = $sh.SpecialFolders('Desktop'); "
        f"$lnk = $sh.CreateShortcut($d + '\\{_PS_NAME}.lnk'); "
        f"$lnk.TargetPath       = '{PYTHON}'; "
        f"$lnk.Arguments        = '\"{APP_PY}\"'; "
        f"$lnk.WorkingDirectory = '{APP_DIR}'; "
        f"$lnk.IconLocation     = '{icon_loc}'; "
        f"$lnk.Description      = '{_PS_NAME} - Voice-to-Text'; "
        "$lnk.Save()"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            print(f"  [OK] Desktop shortcut created: '{NAME}'")
        else:
            print(f"  [WARN] Shortcut creation failed:\n{result.stderr.strip()}")
    except Exception as e:
        print(f"  [WARN] Shortcut creation failed: {e}")


def add_to_startup() -> None:
    """Add FTC Whisper to Windows startup via the user Startup folder."""
    try:
        import winreg
        # Resolve %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion"
                            r"\Explorer\Shell Folders") as k:
            startup_dir, _ = winreg.QueryValueEx(k, "Startup")
    except Exception:
        startup_dir = os.path.join(os.environ.get("APPDATA", ""),
                                   r"Microsoft\Windows\Start Menu\Programs\Startup")

    icon_loc = f"{LOGO_ICO},0" if os.path.exists(LOGO_ICO) else f"{PYTHON},0"
    ps = (
        "$sh = New-Object -ComObject WScript.Shell; "
        f"$lnk = $sh.CreateShortcut('{startup_dir}\\{_PS_NAME}.lnk'); "
        f"$lnk.TargetPath       = '{PYTHON}'; "
        f"$lnk.Arguments        = '\"{APP_PY}\"'; "
        f"$lnk.WorkingDirectory = '{APP_DIR}'; "
        f"$lnk.IconLocation     = '{icon_loc}'; "
        f"$lnk.Description      = '{_PS_NAME} - Voice-to-Text'; "
        "$lnk.Save()"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            print("  [OK] Added to Windows startup folder.")
        else:
            print(f"  [WARN] Startup shortcut failed:\n{result.stderr.strip()}")
    except Exception as e:
        print(f"  [WARN] Startup shortcut failed: {e}")


def register_url_protocol() -> None:
    """Register ftcwhisper:// URL protocol so browsers can launch the app."""
    try:
        import winreg
        cmd = f'"{PYTHON}" "{APP_PY}" "%1"'
        base = "Software\\Classes\\" + brand.URL_SCHEME
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
            winreg.SetValueEx(k, "",             0, winreg.REG_SZ, f"URL:{NAME}")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        print("  [OK] Registered ftcwhisper:// URL protocol.")
    except Exception as e:
        print(f"  [WARN] URL protocol registration failed: {e}")


def main() -> None:
    print()
    print("  ==============================================")
    print(f"   {NAME}  |  Post-install setup")
    print("  ==============================================")

    _banner("Setting up config...")
    setup_config()

    _banner("Creating application icon...")
    icon = create_icon()

    _banner("Creating desktop shortcut...")
    create_shortcut(icon)

    # Auto-launch is now owned entirely by the running app (app.py
    # _ensure_startup_task → Task Scheduler, with stable %LOCALAPPDATA% exe
    # path and legacy-launcher reconciliation). The old Startup-folder shortcut
    # pointed at venv\Scripts\pythonw.exe + app.py, which never exists for a
    # user running the built exe, and competed with the task at boot.
    # add_to_startup() intentionally no longer called.

    _banner("Registering browser launch protocol...")
    register_url_protocol()

    print()
    print("  ==============================================")
    print(f"   All done!  Double-click '{NAME}'")
    print("   on your desktop to launch the app.")
    print("  ==============================================")
    print()


if __name__ == "__main__":
    main()
