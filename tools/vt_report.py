"""Read VirusTotal's verdict on the files a build just uploaded.

    python tools/vt_report.py --out dist/selftest/virustotal.json FILE [FILE ...]

The upload step (crazy-max/ghaction-virustotal) only submits the files and
prints links; nobody reads them. This waits for each file's analysis, writes
every engine that flagged it to the job summary and a JSON report, and:

  * warns (never fails) on any detection, so a false positive is seen on the
    build that caused it, not in a customer's email weeks later;
  * fails when an engine in VT_BLOCK_ENGINES (default: Microsoft) calls a file
    malicious. Defender quarantines on almost every Windows PC, so publishing
    such a build breaks installs and the updater for the whole fleet.

VirusTotal being down, slow or over quota never fails the build: the step
warns and exits 0. Public API limits are 4 requests a minute and 500 a day,
so it polls slowly; a release run makes a few dozen requests at most.
Needs VT_API_KEY in the environment. Standard library only.
"""

import argparse
import hashlib
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://www.virustotal.com/api/v3/files/"
GUI = "https://www.virustotal.com/gui/file/"
# 4 requests a minute on the Public API.
REQUEST_GAP = 16.0
DEFAULT_TIMEOUT = 900


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(sha, key):
    """The file object's attributes, or None while VirusTotal has no report."""
    req = urllib.request.Request(API + sha, headers={"x-apikey": key,
                                                     "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["data"]["attributes"]
    except urllib.error.HTTPError as e:
        if e.code == 404:   # uploaded, not processed yet
            return None
        raise


def analysis_done(attrs, since):
    """True once the report covers this upload, not an older analysis."""
    return bool(attrs and attrs.get("last_analysis_results")
                and attrs.get("last_analysis_date", 0) >= since)


def summarise(name, sha, attrs, block_engines):
    stats = attrs.get("last_analysis_stats", {})
    flagged = []
    for engine, res in sorted(attrs.get("last_analysis_results", {}).items()):
        if res.get("category") in ("malicious", "suspicious"):
            flagged.append({"engine": engine, "category": res["category"],
                            "result": res.get("result") or ""})
    blocking = [f for f in flagged
                if f["category"] == "malicious" and f["engine"] in block_engines]
    return {"file": name, "sha256": sha, "url": GUI + sha,
            "malicious": stats.get("malicious", 0),
            "suspicious": stats.get("suspicious", 0),
            "undetected": stats.get("undetected", 0),
            "flagged": flagged, "blocking": blocking}


def markdown(results, pending):
    lines = ["## VirusTotal", "",
             "| File | Malicious | Suspicious | Clean | Report |",
             "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['file']} | {r['malicious']} | {r['suspicious']} | "
                     f"{r['undetected']} | [open]({r['url']}) |")
    for name, sha in pending:
        lines.append(f"| {name} | ? | ? | ? | [not ready]({GUI + sha}) |")
    for r in results:
        if r["flagged"]:
            lines += ["", f"**{r['file']}** flagged by:", ""]
            lines += [f"- {f['engine']}: {f['category']} `{f['result']}`"
                      for f in r["flagged"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", help="write the JSON report here")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = ap.parse_args(argv)

    key = os.environ.get("VT_API_KEY", "")
    if not key:
        print("::warning title=VirusTotal::VT_API_KEY not set, skipped")
        return 0
    block_engines = {e.strip() for e in
                     os.environ.get("VT_BLOCK_ENGINES", "Microsoft").split(",")
                     if e.strip()}

    # The upload step ran just before; anything analysed before this run
    # started belongs to an older, identical upload and is still valid, so
    # allow a day of slack rather than demanding a fresh scan.
    since = int(time.time()) - 86400
    waiting = {os.path.basename(p): sha256_of(p) for p in args.files}
    results, deadline = [], time.monotonic() + args.timeout
    warned, refused = set(), False
    while waiting and not refused and time.monotonic() < deadline:
        for name, sha in list(waiting.items()):
            try:
                attrs = fetch(sha, key)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):   # bad or revoked key: waiting won't help
                    # Stop asking, but keep what was already read: a Microsoft
                    # detection on an earlier file must still block.
                    print(f"::warning title=VirusTotal::API refused the key "
                          f"(HTTP {e.code}); stopped polling")
                    refused = True
                    break
                attrs = None               # 429 quota, 5xx: keep polling slowly
                if (name, e.code) not in warned:
                    warned.add((name, e.code))
                    print(f"::warning title=VirusTotal::{name}: HTTP {e.code}")
            except (urllib.error.URLError, http.client.HTTPException, OSError,
                    ValueError, KeyError) as e:
                attrs = None
                if (name, type(e)) not in warned:
                    warned.add((name, type(e)))
                    print(f"::warning title=VirusTotal::{name}: {e}")
            if analysis_done(attrs, since):
                results.append(summarise(name, sha, attrs, block_engines))
                del waiting[name]
            time.sleep(REQUEST_GAP)

    pending = list(waiting.items())
    summary = markdown(results, pending)
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(summary)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"results": results,
                       "pending": [{"file": n, "sha256": s} for n, s in pending]},
                      f, indent=2)

    for name, _ in pending:
        print(f"::warning title=VirusTotal::{name}: no report before the timeout")
    blocked = False
    for r in results:
        for f in r["flagged"]:
            level = "error" if f in r["blocking"] else "warning"
            print(f"::{level} title=VirusTotal {f['engine']}::{r['file']} "
                  f"{f['category']} ({f['result']}) {r['url']}")
        blocked = blocked or bool(r["blocking"])
    if blocked:
        print("::error title=VirusTotal::a blocking engine flags this build; "
              "not publishing. Submit it to that vendor as a false positive "
              "(docs/FALSE_POSITIVE_REPORTING.md), then re-run.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
