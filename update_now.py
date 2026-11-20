"""What the Update Now button installs (Settings > Updates).

Kept out of updater.py on purpose: it only reads the release cache and, when
that is stale, the latest release. It never touches download, staging or the
swap, so it cannot change how an update installs.
"""
from typing import Callable, Optional

import updater


def release_ready(rel: Optional[dict], version: str) -> bool:
    """True when *rel* is the release for *version* and carries a usable
    installer (what updater.update_route needs for the installed layout)."""
    if not rel:
        return False
    if str(rel.get("version", "")).lstrip("vV") != version.lstrip("vV"):
        return False
    setup = rel.get("setup") or {}
    return bool(setup.get("url") and setup.get("sha256"))


def update_target(version: str, url: str,
                  fetch: Callable[[], Optional[dict]] = None) -> tuple:
    """(version, onefile url) the Update Now button should install.

    The release cache can be stale or empty when the button is pressed (a
    banner from an earlier check, a check that failed since): the installer
    route then refused at once and the button fell back to the browser
    (Ryan, 2026-11-20). Re-read the latest release when the cache does not
    hold a usable one for *version*; a newer release replaces the banner's
    version, an older or failed read keeps it. Blocking (one GitHub call):
    call from a worker thread."""
    cached = updater.cached_release()
    if release_ready(cached, version):
        return version, url
    fresh = (fetch or updater.get_latest_release)()
    # A refresh that failed leaves the cache as it was: a usable release there
    # still installs in the app instead of failing at once.
    for rel in (fresh, cached if fresh is None else None):
        if (rel and not updater.is_newer(version, rel["version"])
                and not updater.is_known_bad(rel["version"])):
            if fresh is None and not release_ready(rel, rel["version"]):
                continue
            return rel["version"], rel["download_url"]
    return version, url
