"""An update may never install a half-written exe.

2026-09-21, v1.6.80 -> v1.6.81 on Ryan's machine: the installed exe came out
as the first 21,299,200 bytes of the 129,595,787-byte release, and it would
not start ("Could not load PyInstaller's embedded PKG archive"). The download
had been complete and verified. A second writer then restarted a download into
the SAME fixed file, the first run installed while that was mid-way, and the
swap script's Copy-Item copied the partial file and logged success.

Pinned here, each against the real code:
  * one update run per process; a second caller joins it (and may only ask it
    to install sooner), it never starts a second download;
  * every run downloads to a file of its own;
  * GitHub's published SHA-256 is enforced, and the file is re-checked right
    before install;
  * the swap script (run for real in PowerShell against dummy files) installs
    only a file that still has the verified hash, through a staged, verified
    copy, and otherwise leaves the installed exe untouched;
  * a PyInstaller exe missing its trailing archive marker is refused
    everywhere, and the app never hands off to one.
"""

import hashlib
import inspect
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fake_exe(size: int = 6 * 1024 * 1024, signature: int = 0, seed: int = 1) -> bytes:
    """MZ header, filler, then a PyInstaller cookie closing an archive that
    spans most of the file, optionally followed by a code-signature blob."""
    body_len = size - 88
    body = b"MZ" + bytes((seed + i) % 251 for i in range(4094)) + b"\0" * (body_len - 4096)
    pkg_len = body_len - 1024 + 88
    cookie = struct.pack("!8sIIII64s", updater._PYI_COOKIE, pkg_len, 100, 200, 311,
                         b"python311.dll")
    return body + cookie + b"\x30" * signature


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ArchiveMarkerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, data: bytes) -> str:
        p = os.path.join(self.dir, "x.exe")
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_a_whole_exe_is_intact(self):
        self.assertTrue(updater.pyi_archive_intact(self._write(_fake_exe())))

    def test_a_signature_after_the_archive_is_fine(self):
        self.assertTrue(updater.pyi_archive_intact(
            self._write(_fake_exe(signature=16 * 1024))))

    def test_the_real_failure_shape_is_refused(self):
        # The first 21,299,200 bytes of a 129,595,787-byte exe: header intact,
        # archive and marker gone.
        data = _fake_exe(size=8 * 1024 * 1024)
        self.assertFalse(updater.pyi_archive_intact(self._write(data[:5 * 1024 * 1024])))

    def test_an_archive_longer_than_the_file_is_refused(self):
        data = bytearray(_fake_exe())
        i = bytes(data).rfind(updater._PYI_COOKIE)
        data[i + 8:i + 12] = struct.pack("!I", len(data) * 2)
        self.assertFalse(updater.pyi_archive_intact(self._write(bytes(data))))

    def test_verify_exe_refuses_a_truncated_download_without_a_size_hint(self):
        data = _fake_exe(size=12 * 1024 * 1024)
        p = self._write(data[:7 * 1024 * 1024])     # MZ, over the 5 MB floor
        with self.assertRaises(IOError):
            updater.verify_exe(p)
        updater.verify_exe(self._write(data))       # the whole file passes


class RunTests(unittest.TestCase):
    """run_auto_update against a fake download, with apply_fn captured."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.data = _fake_exe()
        self.applied = []
        patches = [
            mock.patch.object(updater, "_app_data_dir", lambda: self.dir),
            mock.patch.object(updater, "_cached_release", {
                "version": "v9.9.9", "download_url": "https://x/FTC-Whisper.exe",
                "size": len(self.data), "sha256": _sha(self.data)}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        updater._run_active = False
        updater._apply_now.clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _download(self, data=None, gate=None, paths=None):
        def fake(url, dest, progress_cb, expected_bytes=0):
            if paths is not None:
                paths.append(dest)
            if gate is not None:
                gate.wait(5)
            with open(dest, "wb") as f:
                f.write(self.data if data is None else data)
        return fake

    def _apply(self, new_exe, current_exe, sha256=None):
        self.applied.append((new_exe, sha256, open(new_exe, "rb").read()))

    def _run(self, **kw):
        args = dict(version="v9.9.9", url="https://x/FTC-Whisper.exe",
                    current_exe=os.path.join(self.dir, "cur.exe"),
                    is_idle=lambda: True, apply_fn=self._apply,
                    poll_interval=0.0, idle_samples=1)
        args.update(kw)
        return updater.run_auto_update(**args)

    def test_a_second_caller_joins_instead_of_downloading(self):
        gate = threading.Event()
        paths = []
        with mock.patch.object(updater, "download_update",
                               self._download(gate=gate, paths=paths)):
            t = threading.Thread(target=self._run)
            t.start()
            for _ in range(100):
                if updater._run_active:
                    break
                time.sleep(0.01)
            joined = self._run()                  # the Update Now click
            gate.set()
            t.join(5)
        self.assertTrue(joined)
        self.assertEqual(len(paths), 1)           # one download, not two
        self.assertEqual(len(self.applied), 1)
        self.assertEqual(self.applied[0][2], self.data)

    def test_install_now_cuts_the_idle_wait_short(self):
        gate = threading.Event()
        with mock.patch.object(updater, "download_update", self._download(gate=gate)):
            t = threading.Thread(target=self._run, kwargs=dict(
                is_idle=lambda: False, poll_interval=0.05, idle_samples=6))
            t.start()
            for _ in range(100):
                if updater._run_active:
                    break
                time.sleep(0.01)
            gate.set()
            time.sleep(0.2)
            self.assertEqual(self.applied, [])    # never idle: still waiting
            self.assertTrue(self._run(apply_now=True))
            t.join(5)
        self.assertEqual(len(self.applied), 1)

    def test_every_run_downloads_to_its_own_file(self):
        paths = []
        with mock.patch.object(updater, "download_update", self._download(paths=paths)), \
             mock.patch.object(updater.time, "time", side_effect=[1000.0, 1000.0, 2000.0, 2000.0]):
            self._run()
            self._run()
        self.assertEqual(len(set(paths)), 2)
        for p in paths:
            self.assertNotEqual(os.path.basename(p), "FTC-Whisper-new.exe")

    def test_the_verified_hash_is_what_gets_installed(self):
        with mock.patch.object(updater, "download_update", self._download()):
            self._run()
        self.assertEqual(self.applied[0][1], _sha(self.data))

    def test_a_download_that_is_not_the_published_file_is_refused(self):
        other = _fake_exe(seed=7)                 # same size, different bytes
        with mock.patch.object(updater, "download_update", self._download(data=other)), \
             mock.patch.object(updater.time, "sleep", lambda *_: None):
            self.assertFalse(self._run())
        self.assertEqual(self.applied, [])
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".exe")], [])

    def test_a_download_changed_during_the_idle_wait_is_not_installed(self):
        polls = []

        def is_idle():
            if not polls:                         # someone rewrites the file
                dest = [n for n in os.listdir(self.dir) if n.startswith("FTC-Whisper-new")][0]
                with open(os.path.join(self.dir, dest), "r+b") as f:
                    f.truncate(len(self.data) // 5)
            polls.append(1)
            return True

        with mock.patch.object(updater, "download_update", self._download()):
            self.assertFalse(self._run(is_idle=is_idle))
        self.assertEqual(self.applied, [])

    def test_old_leftovers_are_swept_and_young_ones_kept(self):
        old = os.path.join(self.dir, "FTC-Whisper-new.exe")
        young = os.path.join(self.dir, "FTC-Whisper-new-1-2.exe")
        for p in (old, young):
            with open(p, "wb") as f:
                f.write(b"x")
        os.utime(old, (time.time() - 7200,) * 2)
        updater._sweep_stale_downloads()
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(young))    # may be another run's download


@unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell"),
                     "the swap script is PowerShell")
class SwapScriptTests(unittest.TestCase):
    """The generated script, executed for real against dummy files."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cur = os.path.join(self.dir, "blecho_test_install.exe")
        self.new = os.path.join(self.dir, "blecho_test_download.exe")
        self.old_data = _fake_exe(seed=3)
        self.new_data = _fake_exe(seed=9)
        with open(self.cur, "wb") as f:
            f.write(self.old_data)
        with open(self.new, "wb") as f:
            f.write(self.new_data)
        # A process that has already exited, so the script's wait returns.
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        self.pid = p.pid

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _swap(self, sha256):
        log = os.path.join(self.dir, "swap.log")
        updater.spawn_swap_script(self.new, self.cur, self.pid, sha256=sha256,
                                  ps_file=os.path.join(self.dir, "swap.ps1"),
                                  log_file=log, launch=False)
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                with open(log, encoding="utf-8-sig") as f:
                    text = f.read()
                if "Done." in text:
                    return text
            except OSError:
                pass
            time.sleep(0.25)
        self.fail("swap script did not finish")

    def _read(self, p):
        with open(p, "rb") as f:
            return f.read()

    def test_a_verified_download_is_installed_and_cleaned_up(self):
        log = self._swap(_sha(self.new_data))
        self.assertEqual(self._read(self.cur), self.new_data, log)
        self.assertIn("Installed and verified", log)
        self.assertFalse(os.path.exists(self.new))
        self.assertFalse(os.path.exists(self.cur + ".previous"))
        self.assertFalse(os.path.exists(self.cur + ".staging"))

    def test_a_download_cut_short_after_verification_is_never_installed(self):
        want = _sha(self.new_data)
        with open(self.new, "r+b") as f:          # the 2026-09-21 shape
            f.truncate(len(self.new_data) // 6)
        log = self._swap(want)
        self.assertEqual(self._read(self.cur), self.old_data, log)
        self.assertIn("NOT installing", log)
        self.assertTrue(os.path.exists(self.new))  # kept for diagnosis

    def test_no_hash_means_no_install(self):
        log = self._swap("")
        self.assertEqual(self._read(self.cur), self.old_data, log)

    def test_the_shipped_script_parses(self):
        # The tests above run with launch=False; the app runs launch=True.
        # A parse error anywhere in the file means no update ever installs
        # (one slipped in while this suite was written: "$$false").
        for launch in (True, False):
            ps = os.path.join(self.dir, f"parse-{launch}.ps1")
            with mock.patch.object(subprocess, "Popen"):
                updater.spawn_swap_script(self.new, self.cur, self.pid, sha256="ab" * 32,
                                          ps_file=ps, log_file=os.path.join(self.dir, "p.log"),
                                          launch=launch)
            check = ("$e = $null; [void][System.Management.Automation.Language.Parser]::"
                     f"ParseFile('{ps}', [ref]$null, [ref]$e); $e.Count")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", check],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.stdout.strip(), "0", out.stdout + out.stderr)


class WiringTests(unittest.TestCase):
    def _src(self, name):
        with open(os.path.join(HERE, name), encoding="utf-8-sig") as f:
            return f.read()

    def test_the_crm_route_uses_the_one_update_run(self):
        src = self._src("app.py")
        block = src[src.index('elif self.path.startswith("/update")'):]
        block = block[:block.index("self.send_response(404)")]
        self.assertIn("run_auto_update(", block)
        self.assertIn("apply_now=True", block)
        self.assertNotIn("download_update(", block)

    def test_update_now_joins_rather_than_downloading_again(self):
        src = self._src("app_window.py")
        body = src[src.index("def show_update_banner"):]
        body = body[:body.index("\n    def ", 10)]
        self.assertIn("joined = run_auto_update(", body)
        self.assertIn("apply_now=True", body)
        self.assertIn("if joined:", body)

    def test_no_update_path_writes_the_old_shared_file(self):
        self.assertNotIn('"FTC-Whisper-new.exe"', self._src("updater.py"))

    def test_the_app_never_hands_off_to_an_incomplete_install(self):
        src = self._src("app.py")
        handoff = src[src.index("def _handoff_to_canonical_if_newer"):]
        handoff = handoff[:handoff.index("\ndef ")]
        self.assertIn("pyi_archive_intact(target)", handoff)
        copy = src[src.index("def _ensure_installed_copy"):]
        copy = copy[:copy.index("\ndef ")]
        self.assertIn("pyi_archive_intact(target)", copy)

    def test_apply_update_always_passes_a_hash_to_the_script(self):
        body = inspect.getsource(updater.apply_update)
        self.assertIn("sha256 = file_sha256(new_exe)", body)
        self.assertIn("sha256=sha256", body)


if __name__ == "__main__":
    unittest.main()
