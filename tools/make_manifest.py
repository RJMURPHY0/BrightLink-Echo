"""Rewrite the installed layout's manifest after the exe is signed.

    python tools/make_manifest.py ["dist\\BrightLink Echo"]

Signing changes the exe's bytes, so the manifest the spec wrote describes an
exe that no longer exists. CI runs this between signing and building the
installer; activate.ps1 and the updater then refuse anything that differs
from it.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import brand  # noqa: E402
import install_layout  # noqa: E402
from tools.build_installer import app_version  # noqa: E402


# Windows' MAX_PATH is 260 including the terminator. The deepest installed file
# sits under pending-<version>\ while an update is staged, below a user profile
# whose name can be long (a 32-character domain user is the budget here). A
# file past the limit fails to copy and the version never installs, so the
# build fails first. Found 2026-09-29: anthropic ships a 104-character module
# path, and a local build from a deep scratch folder crossed the line.
# Both folder names count: a v1.8.0 to v1.8.4 copy stages in the legacy folder and
# activate.ps1 then moves it into the new one.
_PROFILE_BUDGET = (len(r"C:\Users\\") + 32 + len("\\AppData\\Local\\")
                   + max(len(brand.DATA_DIR_NAME), len(brand.LEGACY_DATA_DIR_NAME)) + 1)
_MAX_PATH = 259


def worst_installed_path(manifest: dict) -> tuple:
    """(length, relative path) of the longest path a staged update creates."""
    pending = brand.PENDING_DIR_PREFIX + manifest["version"] + "\\"
    worst = max((f["path"] for f in manifest["files"]), key=len)
    return _PROFILE_BUDGET + len(pending) + len(worst), worst


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dist = argv[0] if argv else os.path.join(ROOT, "dist", brand.EXE_BASENAME)
    version = app_version()
    path = install_layout.write_manifest(dist, version)
    manifest = install_layout.load_manifest(path)
    problems = install_layout.verify_tree(dist, manifest)
    if problems:
        raise SystemExit(f"manifest does not verify: {problems[:5]}")
    length, worst = worst_installed_path(manifest)
    print(f"[manifest] deepest installed path: {length} of {_MAX_PATH} ({worst})")
    if length > _MAX_PATH:
        raise SystemExit(f"{worst} would be {length} characters deep once installed "
                         f"(Windows allows {_MAX_PATH}): the update could never install")
    print(f"[manifest] {path}: {len(manifest['files'])} files + exe "
          f"{manifest['exe']['sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
