"""app.py and the installed (onedir) layout.

The dangerous line in the migration: until v1.7.x any frozen copy of the app
that ran from somewhere else copied ITSELF to the canonical path, because the
exe was the whole app. A onedir exe is not: copied alone, without its
app-<version> folder, it cannot start, and every shortcut, the logon task and
the URL protocol point at that copy.

Pinned, both directions:
  * a onedir build never copies itself to the canonical path;
  * a onefile copy never overwrites a whole installed layout (it would undo
    the migration), but still repairs or refreshes a onefile install as before;
  * a onefile copy hands off to the installed layout at the same version, and
    never to an installed exe whose folder is missing;
  * the installer's choices (desktop shortcut, Start with Windows) reach the
    installed files without going through Config.load();
  * health is reported where activate.ps1 needs it.
"""

import inspect
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_mod  # noqa: E402
import brand  # noqa: E402
import install_layout as il  # noqa: E402


def _fake_exe(path: str, contents: str, tag: bytes = b"") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"MZ" + tag + b"\0" * 5000 + b"pyi-contents-directory "
                + contents.encode() + b"\0" * 8)


def _installed_layout(root: str, version: str = "1.8.0") -> str:
    exe = os.path.join(root, brand.CANONICAL_EXE_NAME)
    _fake_exe(exe, il.contents_dir_name(version), b"installed")
    c = os.path.join(root, il.contents_dir_name(version))
    os.makedirs(c, exist_ok=True)
    with open(os.path.join(c, "python311.dll"), "wb") as f:
        f.write(b"dll")
    il.write_manifest(root, version)
    return exe


class _Frozen(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.install = os.path.join(self.dir, "install")
        self.target = os.path.join(self.install, brand.CANONICAL_EXE_NAME)
        os.makedirs(self.install)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _patches(self, current: str, layout: str):
        return [mock.patch.object(sys, "frozen", True, create=True),
                mock.patch.object(sys, "executable", current),
                mock.patch.object(app_mod, "_stable_exe_path", lambda: self.target),
                mock.patch.object(il, "running_layout", lambda *a, **k: layout),
                mock.patch("updater.pyi_archive_intact", lambda p: os.path.exists(p))]

    def _with(self, current, layout, fn):
        ps = self._patches(current, layout)
        for p in ps:
            p.start()
        try:
            return fn()
        finally:
            for p in reversed(ps):
                p.stop()

    def _bytes(self, path):
        with open(path, "rb") as f:
            return f.read()


class EnsureInstalledCopyTests(_Frozen):
    def test_a_onedir_build_never_copies_itself(self):
        dev = os.path.join(self.dir, "dist", "FTC Whisper", brand.CANONICAL_EXE_NAME)
        _fake_exe(dev, "app-1.8.0")
        got = self._with(dev, "onedir", app_mod._ensure_installed_copy)
        self.assertEqual(dev, got)
        self.assertFalse(os.path.exists(self.target))   # no bare exe at the canonical path

    def test_a_onedir_build_registers_a_whole_install(self):
        _installed_layout(self.install)
        before = self._bytes(self.target)
        dev = os.path.join(self.dir, "dist", "FTC Whisper", brand.CANONICAL_EXE_NAME)
        _fake_exe(dev, "app-1.8.1", b"dev")
        got = self._with(dev, "onedir", app_mod._ensure_installed_copy)
        self.assertEqual(self.target, got)
        self.assertEqual(before, self._bytes(self.target))

    def test_a_onefile_copy_never_overwrites_the_installed_layout(self):
        _installed_layout(self.install)
        before = self._bytes(self.target)
        dl = os.path.join(self.dir, "Downloads", "BrightLink-Echo.exe")
        _fake_exe(dl, "_internal", b"onefile")
        future = time.time() + 3600                       # newer mtime than the install
        os.utime(dl, (future, future))
        got = self._with(dl, "onefile", app_mod._ensure_installed_copy)
        self.assertEqual(self.target, got)
        self.assertEqual(before, self._bytes(self.target))

    def test_a_onefile_copy_still_refreshes_a_onefile_install(self):
        # Unchanged behaviour for every machine not yet migrated.
        _fake_exe(self.target, "_internal", b"old")
        old = time.time() - 3600
        os.utime(self.target, (old, old))
        dl = os.path.join(self.dir, "Downloads", "BrightLink-Echo.exe")
        _fake_exe(dl, "_internal", b"new")
        got = self._with(dl, "onefile", app_mod._ensure_installed_copy)
        self.assertEqual(self.target, got)
        self.assertEqual(self._bytes(dl), self._bytes(self.target))

    def test_a_onefile_copy_repairs_an_installed_exe_missing_its_folder(self):
        # The layout is unrecoverable without its folder; a whole onefile app
        # at the canonical path is the next best thing, and it migrates again.
        _installed_layout(self.install)
        shutil.rmtree(os.path.join(self.install, "app-1.8.0"))
        dl = os.path.join(self.dir, "Downloads", "BrightLink-Echo.exe")
        _fake_exe(dl, "_internal", b"onefile")
        got = self._with(dl, "onefile", app_mod._ensure_installed_copy)
        self.assertEqual(self.target, got)
        self.assertEqual(self._bytes(dl), self._bytes(self.target))


class HandoffTests(_Frozen):
    def _handoff(self, current, layout, cur_v, tgt_v):
        launched = []
        versions = {os.path.abspath(current): cur_v, self.target: tgt_v}

        class _Exit(Exception):
            pass

        def _exit(code):
            raise _Exit()
        with mock.patch.object(app_mod, "_file_version_tuple", lambda p: versions.get(p, (0,) * 4)), \
                mock.patch("subprocess.Popen", lambda cmd, **kw: launched.append(cmd)), \
                mock.patch.object(os, "_exit", _exit):
            try:
                self._with(current, layout, app_mod._handoff_to_canonical_if_newer)
            except _Exit:
                pass
        return launched

    def test_a_onefile_copy_defers_to_the_installed_layout_at_the_same_version(self):
        _installed_layout(self.install)
        dl = os.path.join(self.dir, "Downloads", "BrightLink-Echo.exe")
        _fake_exe(dl, "_internal")
        self.assertEqual(1, len(self._handoff(dl, "onefile", (1, 8, 0, 0), (1, 8, 0, 0))))

    def test_same_version_onefile_installs_are_left_alone(self):
        _fake_exe(self.target, "_internal")
        dl = os.path.join(self.dir, "Downloads", "BrightLink-Echo.exe")
        _fake_exe(dl, "_internal")
        self.assertEqual([], self._handoff(dl, "onefile", (1, 7, 3, 0), (1, 7, 3, 0)))

    def test_never_to_an_installed_exe_missing_its_folder(self):
        _installed_layout(self.install)
        shutil.rmtree(os.path.join(self.install, "app-1.8.0"))
        dl = os.path.join(self.dir, "Downloads", "BrightLink-Echo.exe")
        _fake_exe(dl, "_internal")
        self.assertEqual([], self._handoff(dl, "onefile", (1, 7, 3, 0), (1, 8, 0, 0)))

    def test_a_newer_install_still_takes_over(self):
        _installed_layout(self.install)
        dl = os.path.join(self.dir, "Downloads", "BrightLink-Echo.exe")
        _fake_exe(dl, "_internal")
        self.assertEqual(1, len(self._handoff(dl, "onefile", (1, 7, 3, 0), (1, 8, 0, 0))))


class InstallerChoicesTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.meipass = os.path.join(self.dir, "app-1.8.0")
        os.makedirs(self.meipass)
        with open(os.path.join(self.meipass, "config.json"), "w") as f:
            json.dump({"supabase_url": "https://shared", "start_with_windows": True,
                       "hotkey": "alt+v"}, f)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _apply(self, *argv):
        with mock.patch.object(sys, "argv", ["FTC Whisper.exe", "--install", "/S", *argv]), \
                mock.patch.object(sys, "_MEIPASS", self.meipass, create=True), \
                mock.patch.object(app_mod, "_app_data_dir", lambda: self.dir):
            app_mod._apply_installer_choices()

    def _config(self):
        with open(os.path.join(self.dir, "config.json")) as f:
            return json.load(f)

    def test_start_with_windows_off_on_a_fresh_install_keeps_every_default(self):
        self._apply("--start-with-windows=0")
        cfg = self._config()
        self.assertIs(False, cfg["start_with_windows"])
        self.assertEqual("https://shared", cfg["supabase_url"])   # bundled defaults kept

    def test_an_existing_config_is_merged_not_replaced(self):
        with open(os.path.join(self.dir, "config.json"), "w") as f:
            json.dump({"hotkey": "ctrl+space", "custom_vocabulary": "Ryan"}, f)
        self._apply("--start-with-windows=1")
        cfg = self._config()
        self.assertEqual("ctrl+space", cfg["hotkey"])
        self.assertEqual("Ryan", cfg["custom_vocabulary"])
        self.assertIs(True, cfg["start_with_windows"])

    def test_no_choice_touches_nothing(self):
        self._apply()
        self.assertFalse(os.path.exists(os.path.join(self.dir, "config.json")))

    def test_no_desktop_shortcut_latches_the_shortcut(self):
        import app_install
        self._apply("--no-desktop-shortcut")
        self.assertTrue(app_install.load_state(self.dir)["desktop_shortcut"])
        # ...which is exactly what stops registration creating one.
        wanted = app_install.shortcuts_needed(app_install.load_state(self.dir), "x",
                                              os.path.join(self.dir, "s.lnk"),
                                              os.path.join(self.dir, "d.lnk"))
        self.assertNotIn(os.path.join(self.dir, "d.lnk"), wanted)


class InstalledSizeTests(unittest.TestCase):
    def test_transient_files_are_not_counted(self):
        import app_install
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        for rel, kb in (("app-1.8.0/a.dll", 100), ("models/m.onnx", 300),
                        ("runtime/_MEI1/x.dll", 1000), ("pending-1.8.1/app-1.8.1/y.dll", 1000),
                        ("FTC Whisper.exe", 10), ("FTC Whisper.exe.previous", 1000)):
            p = os.path.join(d, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(b"\0" * kb * 1024)
        self.assertEqual(410, app_install._dir_size_kb(d))


class HealthTests(unittest.TestCase):
    def test_health_is_reported_when_the_core_has_loaded(self):
        src = inspect.getsource(app_mod.WhisperFlowApp._init_core)
        body = src.split("finally:")[0]
        self.assertIn("_report_healthy()", body)       # inside try: only on success

    def test_a_duplicate_launch_reports_health_before_exiting(self):
        src = inspect.getsource(app_mod._ensure_single_instance)
        self.assertLess(src.index("_report_healthy(cleanup=False)"), src.index("os._exit(0)"))

    def test_updates_are_checked_without_signing_in(self):
        # Until v1.7.x the check started only in _on_authenticated, so a
        # machine whose session had expired never updated (or migrated).
        src = inspect.getsource(app_mod.WhisperFlowApp._init_core).split("finally:")[0]
        self.assertIn("self._start_update_check()", src)

    def test_the_update_check_starts_once(self):
        started = []
        fake = mock.Mock()
        fake._update_check_lock = __import__("threading").Lock()
        fake._update_check_started = False
        with mock.patch("threading.Thread", lambda **kw: mock.Mock(start=lambda: started.append(kw))):
            app_mod.WhisperFlowApp._start_update_check(fake)
            app_mod.WhisperFlowApp._start_update_check(fake)   # sign-in, later
        self.assertEqual(1, len(started))

    def test_source_runs_write_nothing(self):
        with mock.patch.object(sys, "frozen", False, create=True), \
                mock.patch.object(il, "write_health") as w:
            app_mod._report_healthy()
        w.assert_not_called()


if __name__ == "__main__":
    unittest.main()
