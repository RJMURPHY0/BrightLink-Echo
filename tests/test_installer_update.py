"""Updating through the installer (v1.8.0): the installed layout updates by
running the signed installer in stage-only mode, then handing over to the new
version's activate.ps1. The onefile bridge migrates the same way, but only
when the release's rollout file says so.

Pinned, each against the real code:
  * the release lookup still describes the onefile asset exactly as every
    older build reads it, and adds the installer and the rollout file;
  * the installer runs only with GitHub's SHA-256 (required on this path) and
    our Authenticode signer;
  * which route a process takes, for every layout and release shape;
  * staging happens BEFORE the idle wait (the app keeps working while files
    are laid out), and a staged file lost during the wait stops the install;
  * a failed migration is counted, and after three the bridge uses the
    onefile swap;
  * one update run per process still holds on this path;
  * the installer and activate.ps1 are launched like the swap script: clean
    environment, CREATE_NO_WINDOW, never DETACHED_PROCESS.
"""

import inspect
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand  # noqa: E402
import install_layout as il  # noqa: E402
import updater  # noqa: E402

_VALID = lambda _p: ("Valid", brand.SIGNER_SUBJECT)  # noqa: E731


def _release_json(setup=True, rollout=True, digest=True):
    def a(name, size):
        d = {"name": name, "size": size,
             "browser_download_url": f"https://github.com/x/releases/download/v1.8.0/{name}"}
        if digest:
            d["digest"] = "sha256:" + "ab" * 32
        return d
    assets = [a(brand.UPDATE_ASSET, 130_000_000), a(brand.DOWNLOAD_ASSET, 90_000_000)]
    if setup:
        assets.append(a(brand.SETUP_UPDATE_ASSET, 90_000_000))
    if rollout:
        assets.append(a(brand.ROLLOUT_ASSET, 40))
    return {"tag_name": "v1.8.0", "assets": assets}


class ParseReleaseTests(unittest.TestCase):
    def test_the_onefile_fields_are_unchanged(self):
        info = updater.parse_release(_release_json())
        self.assertEqual("v1.8.0", info["version"])
        self.assertTrue(info["download_url"].endswith("/" + brand.UPDATE_ASSET))
        self.assertEqual(130_000_000, info["size"])
        self.assertEqual("ab" * 32, info["sha256"])

    def test_installer_and_rollout(self):
        info = updater.parse_release(_release_json())
        self.assertTrue(info["setup"]["url"].endswith("/" + brand.SETUP_UPDATE_ASSET))
        self.assertEqual(90_000_000, info["setup"]["size"])
        self.assertTrue(info["rollout"]["url"].endswith("/" + brand.ROLLOUT_ASSET))

    def test_an_older_release_has_no_installer(self):
        info = updater.parse_release(_release_json(setup=False, rollout=False))
        self.assertEqual({}, info["setup"])
        self.assertEqual({}, info["rollout"])

    def test_the_download_asset_is_never_mistaken_for_the_installer(self):
        # BrightLink-Echo.exe is the same bytes as the installer, but updaters
        # find the installer only by its frozen name.
        data = _release_json(setup=False)
        info = updater.parse_release(data)
        self.assertEqual({}, info["setup"])

    def test_no_onefile_asset_is_no_release(self):
        data = _release_json()
        data["assets"] = [a for a in data["assets"] if a["name"] != brand.UPDATE_ASSET]
        self.assertIsNone(updater.parse_release(data))


class VerifyInstallerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "setup.exe")
        self.data = b"MZ" + os.urandom(2 * 1024 * 1024)
        with open(self.path, "wb") as f:
            f.write(self.data)
        self.sha = updater.file_sha256(self.path)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_signed_matching_installer_passes(self):
        updater.verify_installer(self.path, len(self.data), self.sha, signer=_VALID)

    def test_no_published_checksum_means_no_install(self):
        with self.assertRaises(IOError):
            updater.verify_installer(self.path, len(self.data), "", signer=_VALID)

    def test_a_different_file_is_refused(self):
        with self.assertRaises(IOError):
            updater.verify_installer(self.path, len(self.data), "0" * 64, signer=_VALID)

    def test_a_truncated_file_is_refused(self):
        with self.assertRaises(IOError):
            updater.verify_installer(self.path, len(self.data) + 1, self.sha, signer=_VALID)

    def test_unsigned_or_someone_elses_signature_is_refused(self):
        for sig in (("NotSigned", ""), ("HashMismatch", brand.SIGNER_SUBJECT),
                    ("Valid", "CN=Someone Else"), ("", "")):
            with self.assertRaises(IOError, msg=sig):
                updater.verify_installer(self.path, len(self.data), self.sha,
                                         signer=lambda _p, s=sig: s)

    def test_not_an_exe_is_refused(self):
        with open(self.path, "wb") as f:
            f.write(b"<html>" + b"x" * 2 * 1024 * 1024)
        with self.assertRaises(IOError):
            updater.verify_installer(self.path, 0, updater.file_sha256(self.path),
                                     signer=_VALID)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        p = mock.patch.object(updater, "_cached_release",
                              updater.parse_release(_release_json()))
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _route(self, layout, rollout=None, version="1.8.0"):
        return updater.update_route(version, layout, rollout_fetch=lambda _r: rollout,
                                    root=self.dir)

    def test_the_installed_layout_always_uses_the_installer(self):
        self.assertEqual("installer", self._route("onedir", rollout=None))

    def test_the_installed_layout_never_takes_the_onefile_exe(self):
        with mock.patch.object(updater, "_cached_release",
                               updater.parse_release(_release_json(setup=False))):
            self.assertEqual("none", self._route("onedir"))
        # Nor an installer without a published checksum.
        with mock.patch.object(updater, "_cached_release",
                               updater.parse_release(_release_json(digest=False))):
            self.assertEqual("none", self._route("onedir"))

    def test_the_bridge_waits_for_the_rollout(self):
        self.assertEqual("onefile", self._route("onefile", rollout=None))
        self.assertEqual("onefile", self._route("onefile", rollout={"migrate_percent": 0}))
        self.assertEqual("installer", self._route("onefile", rollout={"migrate_percent": 100}))
        self.assertEqual("installer", self._route(
            "onefile", rollout={"machines": [il.machine_id()]}))

    def test_the_bridge_falls_back_after_three_failures(self):
        for _ in range(updater._MIGRATION_ATTEMPTS):
            il.record_migration_failure("1.8.0", "x", self.dir)
        self.assertEqual("onefile", self._route("onefile", rollout={"migrate_percent": 100}))

    def test_a_release_without_an_installer_keeps_the_bridge_on_onefile(self):
        with mock.patch.object(updater, "_cached_release",
                               updater.parse_release(_release_json(setup=False))):
            self.assertEqual("onefile", self._route("onefile", rollout={"migrate_percent": 100}))

    def test_a_different_cached_release_is_not_used(self):
        self.assertEqual("none", self._route("onedir", version="1.9.0"))

    def test_the_bridge_migrates_at_its_own_version(self):
        # latest == the bridge's version: nothing is "newer", yet the machine
        # must still move to the installed layout when the rollout says so.
        yes = {"migrate_percent": 100}
        self.assertTrue(updater.migration_due("1.8.0", "onefile", lambda _r: yes, self.dir))
        self.assertFalse(updater.migration_due("1.8.0", "onefile", lambda _r: None, self.dir))
        # Never for the installed layout itself, a source run, or a version
        # the release is not about (newer ones take the normal update path).
        self.assertFalse(updater.migration_due("1.8.0", "onedir", lambda _r: yes, self.dir))
        self.assertFalse(updater.migration_due("1.8.0", "source", lambda _r: yes, self.dir))
        self.assertFalse(updater.migration_due("1.7.3", "onefile", lambda _r: yes, self.dir))

    def test_a_rolled_back_version_is_skipped_until_a_newer_one(self):
        with open(os.path.join(self.dir, il.BAD_VERSION_FILE), "w") as f:
            f.write("1.8.0")
        self.assertTrue(updater.is_known_bad("v1.8.0", self.dir))
        self.assertFalse(updater.is_known_bad("1.8.1", self.dir))


class InstallerRunTests(unittest.TestCase):
    """run_auto_update on the installer route, with the download, staging and
    hand-over captured."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.setup_bytes = b"MZ" + os.urandom(2 * 1024 * 1024)
        info = updater.parse_release(_release_json())
        info["setup"]["size"] = len(self.setup_bytes)
        import hashlib
        info["setup"]["sha256"] = hashlib.sha256(self.setup_bytes).hexdigest()
        self.events, self.order, self.activated = [], [], []
        for p in (mock.patch.object(updater, "_app_data_dir", lambda: self.dir),
                  mock.patch.object(updater, "_cached_release", info),
                  mock.patch.object(updater, "download_update", self._download)):
            p.start()
            self.addCleanup(p.stop)
        updater._run_active = False
        updater._apply_now.clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _download(self, url, dest, progress, expected_bytes=0):
        self.order.append(("download", os.path.basename(dest)))
        with open(dest, "wb") as f:
            f.write(self.setup_bytes)

    def _stage(self, setup, version, root=""):
        self.order.append(("stage", os.path.basename(setup)))
        self.assertTrue(os.path.exists(setup))
        pending = os.path.join(root, il.pending_dir_name(version))
        c = os.path.join(pending, il.contents_dir_name(version))
        os.makedirs(c)
        with open(os.path.join(pending, brand.CANONICAL_EXE_NAME), "wb") as f:
            f.write(b"MZnew")
        with open(os.path.join(c, "a.dll"), "wb") as f:
            f.write(b"dll")
        il.write_manifest(pending, version)
        return pending

    def _idle(self):
        self.order.append(("idle",))
        return True

    def _run(self, layout="onedir", stage=None, idle=None, **kw):
        return updater.run_auto_update(
            "v1.8.0", "https://x/FTC-Whisper.exe", r"C:\x\FTC Whisper.exe",
            is_idle=idle or self._idle, poll_interval=0.0, idle_samples=2,
            on_event=lambda *e: self.events.append(e), layout=layout,
            stage_fn=stage or self._stage, signer=_VALID,
            activate_fn=lambda v, root: self.activated.append((v, root)), **kw)

    def test_stage_then_idle_then_hand_over(self):
        self.assertFalse(self._run())
        self.assertEqual([("1.8.0", self.dir)], self.activated)
        kinds = [o[0] for o in self.order]
        self.assertEqual(["download", "stage", "idle", "idle"], kinds)
        self.assertEqual(["download_start", "download_ok", "stage_ok", "swap_started"],
                         [e[0] for e in self.events])

    def test_each_run_downloads_to_its_own_file_and_removes_it(self):
        self._run()
        name = self.order[0][1]
        self.assertTrue(name.startswith(updater._SETUP_PREFIX + "-"))
        self.assertFalse(os.path.exists(os.path.join(self.dir, name)))

    def test_a_refused_installer_is_never_staged(self):
        with mock.patch.object(updater.time, "sleep", lambda _s: None):
            ok = updater.run_auto_update(
                "v1.8.0", "u", "c", is_idle=self._idle, poll_interval=0.0,
                idle_samples=1, layout="onedir", stage_fn=self._stage,
                signer=lambda _p: ("NotSigned", ""),
                activate_fn=lambda v, root: self.activated.append(v))
        self.assertFalse(ok)
        self.assertNotIn("stage", [o[0] for o in self.order])
        self.assertEqual([], self.activated)

    def test_a_failed_stage_installs_nothing_and_counts_for_the_bridge(self):
        def boom(setup, version, root=""):
            raise IOError("Installer exited with code 5")
        with mock.patch.object(updater, "fetch_rollout",
                               lambda _r: {"migrate_percent": 100}):
            self.assertFalse(self._run(layout="onefile", stage=boom))
        self.assertEqual([], self.activated)
        self.assertEqual(1, il.migration_failures("1.8.0", self.dir))
        self.assertIn("stage_fail", [e[0] for e in self.events])

    def test_a_staged_file_lost_while_waiting_stops_the_install(self):
        def idle():
            # Antivirus quarantines a DLL while the app waits for idle.
            p = os.path.join(self.dir, "pending-1.8.0", "app-1.8.0", "a.dll")
            if os.path.exists(p):
                os.remove(p)
            return True
        self.assertFalse(self._run(idle=idle))
        self.assertEqual([], self.activated)

    def test_a_changed_staged_exe_stops_the_install(self):
        def idle():
            with open(os.path.join(self.dir, "pending-1.8.0", brand.CANONICAL_EXE_NAME), "wb") as f:
                f.write(b"MZold")                                  # same size, other bytes
            return True
        self.assertFalse(self._run(idle=idle))
        self.assertEqual([], self.activated)

    def test_a_second_caller_joins_the_run_in_flight(self):
        gate = threading.Event()
        started = threading.Event()

        def slow_stage(setup, version, root=""):
            started.set()
            gate.wait(10)
            return self._stage(setup, version, root)
        t = threading.Thread(target=lambda: self._run(stage=slow_stage))
        t.start()
        self.assertTrue(started.wait(10))
        self.assertTrue(self._run(apply_now=True))                # joined, no second download
        gate.set()
        t.join(20)
        self.assertEqual(1, [o[0] for o in self.order].count("download"))
        self.assertEqual(1, len(self.activated))


class LaunchContractTests(unittest.TestCase):
    def test_installer_and_activation_launch_like_the_swap_script(self):
        for fn in (updater.stage_installer, updater.spawn_activation):
            src = inspect.getsource(fn)
            self.assertIn("clean_launch_env()", src, fn.__name__)
            self.assertIn("_launch_flags()", src, fn.__name__)
            self.assertNotIn("DETACHED_PROCESS", src, fn.__name__)
        flags = inspect.getsource(updater._launch_flags)
        self.assertIn("CREATE_NO_WINDOW", flags)
        self.assertNotIn("DETACHED_PROCESS", flags.split('"""')[-1])

    def test_staging_is_silent_and_stage_only(self):
        captured = {}

        class _P:
            def wait(self, timeout=None):
                return 0

        def popen(cmd, **kw):
            captured["cmd"], captured["kw"] = cmd, kw
            return _P()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(updater.subprocess, "Popen", popen), \
                mock.patch.object(updater, "verify_pending", lambda v, root: "ok"):
            updater.stage_installer(r"C:\x\setup.exe", "1.8.0", root=tmp)
        for switch in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/STAGEONLY"):
            self.assertIn(switch, captured["cmd"])
        self.assertEqual("1", captured["kw"]["env"]["PYINSTALLER_RESET_ENVIRONMENT"])
        self.assertFalse([k for k in captured["kw"]["env"] if k.upper().startswith("_PYI_")])

    def test_activation_runs_the_new_versions_script_from_a_copy(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        src = os.path.join(tmp, "pending-1.8.0", "app-1.8.0")
        os.makedirs(src)
        with open(os.path.join(src, "activate.ps1"), "w") as f:
            f.write("# new version's script")
        captured = {}
        with mock.patch.object(updater.subprocess, "Popen",
                               lambda cmd, **kw: captured.update(cmd=cmd, kw=kw)):
            script = updater.spawn_activation("v1.8.0", 4242, root=tmp)
        self.assertEqual(os.path.join(tmp, "activate-1.8.0.ps1"), script)
        cmd = captured["cmd"]
        self.assertEqual(script, cmd[cmd.index("-File") + 1])
        for pair in (("-InstallDir", tmp), ("-Version", "1.8.0"), ("-Mode", "Update"),
                     ("-WaitPid", "4242")):
            self.assertEqual(pair[1], cmd[cmd.index(pair[0]) + 1])
        self.assertIn("-Relaunch", cmd)


if __name__ == "__main__":
    unittest.main()
