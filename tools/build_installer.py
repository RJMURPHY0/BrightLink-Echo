"""Build the BrightLink Echo installer from the onedir build.

    python tools/build_installer.py [--dist "dist\\BrightLink Echo"] [--out dist\\installer]
                                    [--iscc path\\to\\ISCC.exe] [--print]

Every name comes from brand.py and the version from app.py, passed to
installer/echo.iss as /D defines, so the installer can never carry a stale
product name or version. The wizard artwork is drawn here from assets/brand
(the app's own near-black and BrightLink orange). Output:
<out>\\<brand.SETUP_UPDATE_ASSET>.

Run after the onedir exe is signed and tools/make_manifest.py has rewritten
the manifest: the installer ships those exact bytes.
"""

import argparse
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import brand  # noqa: E402
import install_layout  # noqa: E402

ISS = os.path.join(ROOT, "installer", "echo.iss")
BG = (13, 13, 13)          # app_window C["bg"]


def app_version() -> str:
    with open(os.path.join(ROOT, "app.py"), "r", encoding="utf-8") as f:
        return re.search(r'^APP_VERSION = "(.+?)"', f.read(), re.M).group(1)


def file_version(version: str) -> str:
    parts = (version.split(".") + ["0"] * 4)[:4]
    return ".".join(str(int(re.match(r"\d*", p).group() or 0)) for p in parts)


def make_artwork(out_dir: str) -> tuple:
    """(wizard image, small image) PNGs: the chain mark on the app's
    background, sized for 200% DPI so they stay sharp."""
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    mark = Image.open(os.path.join(ROOT, "assets", "brand", "brightlink-mark.png")).convert("RGBA")
    word = Image.open(os.path.join(ROOT, "assets", "brand", "echo-wordmark.png")).convert("RGBA")

    big = Image.new("RGBA", (480, 918), BG + (255,))
    m = mark.resize((320, 320), Image.LANCZOS)
    big.alpha_composite(m, ((480 - 320) // 2, 250))
    w = word.resize((word.width * 2, word.height * 2), Image.LANCZOS)
    big.alpha_composite(w, ((480 - w.width) // 2, 600))
    wizard = os.path.join(out_dir, "wizard.png")
    big.convert("RGB").save(wizard)

    small = Image.new("RGBA", (116, 116), BG + (255,))
    small.alpha_composite(mark.resize((100, 100), Image.LANCZOS), (8, 8))
    small_path = os.path.join(out_dir, "wizard-small.png")
    small.convert("RGB").save(small_path)
    return wizard, small_path


def defines(dist: str, out: str, wizard: str, small: str, version: str = "") -> dict:
    version = version or app_version()
    output_base = os.path.splitext(brand.SETUP_UPDATE_ASSET)[0]
    return {
        "AppVersion": version,
        "FileVersion": file_version(version),
        "AppName": brand.PRODUCT_NAME,
        "Publisher": brand.COMPANY_NAME,
        "AppURL": brand.WEBSITE_URL,
        "Copyright": f"Copyright {time.localtime().tm_year} {brand.COMPANY_NAME}",
        "DataDir": brand.DATA_DIR_NAME,
        "ExeName": brand.CANONICAL_EXE_NAME,
        "LegacyDataDir": brand.LEGACY_DATA_DIR_NAME,
        "LegacyExeName": brand.LEGACY_CANONICAL_EXE_NAME,
        "SetupMutex": brand.SETUP_MUTEX,
        "LegacySetupMutex": brand.LEGACY_SETUP_MUTEX,
        "ContentsDir": install_layout.contents_dir_name(version),
        "PendingDir": install_layout.pending_dir_name(version),
        "PendingPrefix": brand.PENDING_DIR_PREFIX,
        "SourceDir": os.path.abspath(dist),
        "OutputDir": os.path.abspath(out),
        "OutputBase": output_base,
        "IconFile": os.path.join(ROOT, "exe_icon.ico"),
        "WizardImage": wizard,
        "WizardSmallImage": small,
    }


def find_iscc(explicit: str = "") -> str:
    candidates = [explicit, os.environ.get("ISCC", "")]
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            candidates.append(os.path.join(base, "Inno Setup 6", "ISCC.exe"))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise SystemExit("ISCC.exe not found: install Inno Setup 6.7.3 or pass --iscc")


def command(iscc: str, d: dict) -> list:
    return [iscc, "/Q"] + [f"/D{k}={v}" for k, v in d.items()] + [ISS]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dist", default=os.path.join(ROOT, "dist", brand.EXE_BASENAME))
    p.add_argument("--out", default=os.path.join(ROOT, "dist", "installer"))
    p.add_argument("--iscc", default="")
    p.add_argument("--print", action="store_true", help="print the command, build nothing")
    args = p.parse_args(argv)

    version = app_version()
    manifest = install_layout.load_manifest(os.path.join(
        args.dist, install_layout.contents_dir_name(version), install_layout.MANIFEST_NAME))
    problems = install_layout.verify_tree(args.dist, manifest) if manifest else ["no manifest"]
    if problems:
        raise SystemExit(f"{args.dist} does not match its manifest: {problems[:5]}")

    wizard, small = make_artwork(os.path.join(ROOT, "build", "installer"))
    cmd = command(args.iscc or "ISCC.exe", defines(args.dist, args.out, wizard, small, version))
    if args.print:
        print(subprocess.list2cmdline(cmd))
        return 0
    cmd[0] = find_iscc(args.iscc)
    os.makedirs(args.out, exist_ok=True)
    subprocess.run(cmd, check=True)
    out = os.path.join(args.out, brand.SETUP_UPDATE_ASSET)
    print(f"[installer] {out} ({os.path.getsize(out):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
