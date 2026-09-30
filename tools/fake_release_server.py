"""A stand-in for GitHub's release API and downloads, for upgrade tests.

    python tools/fake_release_server.py --control control.json --cert s.pem --key s.key

RUN ONLY ON A THROWAWAY MACHINE, with api.github.com and github.com pointed
at 127.0.0.1 in the hosts file and the test CA trusted (tools/e2e_upgrade.py
does both). Every installed Echo, of any version, then talks to this server
exactly as it would to GitHub: nothing is patched in the app, so an old
client's own updater and swap script do the work.

control.json is re-read on every request, so a test can change what the
"latest release" is, or break it, while the app runs:

    {"version": "1.8.0", "assets": "<folder with the release files>",
     "rollout": {"migrate_percent": 100},
     "fault": "" | "offline" | "bad-digest" | "truncate" | "no-setup"}

  bad-digest  the API reports a wrong SHA-256 for the installer
  truncate    the installer download stops half-way
  no-setup    the release has no installer asset (a mistake in a release)
  offline     every request fails
"""

import argparse
import hashlib
import http.server
import json
import os
import socketserver
import ssl
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import brand  # noqa: E402

CONTROL = ""
LOG = ""
_HASHES = {}


def control() -> dict:
    with open(CONTROL, "r", encoding="utf-8") as f:
        return json.load(f)


def sha256(path: str) -> str:
    key = (path, os.path.getmtime(path), os.path.getsize(path))
    if key not in _HASHES:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        _HASHES[key] = h.hexdigest()
    return _HASHES[key]


SETUP_NAMES = (brand.SETUP_UPDATE_ASSET, brand.LEGACY_SETUP_UPDATE_ASSET)
ROLLOUT_NAMES = (brand.ROLLOUT_ASSET, brand.LEGACY_ROLLOUT_ASSET)


def release(c: dict) -> dict:
    v = c["version"].lstrip("vV")
    assets = []
    # Every name a real release carries, including the installer and rollout
    # file under the names v1.8.0 copies ask for.
    names = [brand.UPDATE_ASSET, brand.SETUP_UPDATE_ASSET, brand.LEGACY_SETUP_UPDATE_ASSET,
             brand.DOWNLOAD_ASSET]
    if c.get("fault") == "no-setup":
        names = [n for n in names if n not in SETUP_NAMES]
    for name in names:
        p = os.path.join(c["assets"], name)
        if not os.path.exists(p):
            continue
        digest = sha256(p)
        if c.get("fault") == "bad-digest" and name in SETUP_NAMES:
            digest = "0" * 64
        assets.append({"name": name, "size": os.path.getsize(p), "digest": "sha256:" + digest,
                       "browser_download_url": f"https://github.com/fake/releases/download/v{v}/{name}"})
    rollout = json.dumps(c.get("rollout") or {}).encode()
    for name in ROLLOUT_NAMES:
        assets.append({"name": name, "size": len(rollout),
                       "digest": "sha256:" + hashlib.sha256(rollout).hexdigest(),
                       "browser_download_url": f"https://github.com/fake/releases/download/v{v}/{name}"})
    return {"tag_name": f"v{v}", "name": f"v{v}", "prerelease": False, "assets": assets}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"{self.headers.get('Host')} {fmt % args}\n")
        except Exception:
            pass

    def _send(self, code: int, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        c = control()
        if c.get("fault") == "offline":
            self.close_connection = True
            return
        path = self.path.split("?", 1)[0]
        if path.startswith("/repos/") and path.endswith("/releases/latest"):
            return self._send(200, json.dumps(release(c)).encode())
        if path.startswith("/fake/releases/download/"):
            name = path.rsplit("/", 1)[1]
            if name in ROLLOUT_NAMES:
                return self._send(200, json.dumps(c.get("rollout") or {}).encode())
            p = os.path.join(c["assets"], name)
            if not os.path.isfile(p):
                return self._send(404, b"{}")
            size = os.path.getsize(p)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            limit = size // 2 if (c.get("fault") == "truncate"
                                  and name in SETUP_NAMES) else size
            with open(p, "rb") as f:
                sent = 0
                while sent < limit:
                    chunk = f.read(min(1 << 20, limit - sent))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    sent += len(chunk)
            if limit < size:
                self.close_connection = True
            return
        self._send(404, b"{}")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv=None) -> int:
    global CONTROL, LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", required=True)
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--port", type=int, default=443)
    ap.add_argument("--log", default="")
    a = ap.parse_args(argv)
    CONTROL, LOG = os.path.abspath(a.control), a.log or os.path.abspath(a.control) + ".log"
    httpd = Server(("127.0.0.1", a.port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(a.cert, a.key)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print(f"[fake-github] serving on 127.0.0.1:{a.port}", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
