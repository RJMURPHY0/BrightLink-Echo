"""The installed layout (v1.8.0): how the app tells onedir from onefile, what
a whole version looks like, who may migrate, and what may be cleaned up.

Both directions of each rule, like the rest of the suite: a onefile build is
never mistaken for the installed layout (it would stop copying itself to the
canonical path), and a onedir build is never mistaken for onefile (it would
copy a bare exe there without its folder, and nothing would start).
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand  # noqa: E402
import install_layout as il  # noqa: E402


def _exe_with_contents(path: str, contents: str, size: int = 200_000) -> None:
    """MZ, filler, then an archive table naming *contents*, as PyInstaller's
    bootloader exe carries it."""
    with open(path, "wb") as f:
        f.write(b"MZ" + b"\0" * (size - 2))
        f.write(b"\0\0\0" + b"pyi-contents-directory " + contents.encode() + b"\0" * 9)


class RunningLayoutTests(unittest.TestCase):
    def test_source_run(self):
        self.assertEqual("source", il.running_layout(frozen=False))

    def test_onedir_has_its_files_beside_the_exe(self):
        exe = r"C:\Users\x\AppData\Local\FTC Whisper\FTC Whisper.exe"
        meipass = r"C:\Users\x\AppData\Local\FTC Whisper\app-1.8.0"
        self.assertEqual("onedir", il.running_layout(True, meipass, exe))

    def test_onefile_unpacks_elsewhere(self):
        exe = r"C:\Users\x\AppData\Local\FTC Whisper\FTC Whisper.exe"
        meipass = r"C:\Users\x\AppData\Local\FTC Whisper\runtime\_MEI12345"
        self.assertEqual("onefile", il.running_layout(True, meipass, exe))
        # ...even when the copy runs from Downloads with %TEMP% unpacking.
        self.assertEqual("onefile", il.running_layout(
            True, r"C:\Users\x\AppData\Local\Temp\_MEI9", r"C:\Users\x\Downloads\a.exe"))


class ExeContentsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.exe = os.path.join(self.dir, brand.CANONICAL_EXE_NAME)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_reads_the_versioned_contents_folder(self):
        _exe_with_contents(self.exe, "app-1.8.0")
        self.assertEqual("app-1.8.0", il.exe_contents_dir(self.exe))
        self.assertTrue(il.is_installed_layout_exe(self.exe))

    def test_a_onefile_build_is_not_the_installed_layout(self):
        # PyInstaller onefile builds record the default "_internal".
        _exe_with_contents(self.exe, "_internal")
        self.assertFalse(il.is_installed_layout_exe(self.exe))
        self.assertTrue(il.layout_ok(self.exe))     # judged by its own archive

    def test_unreadable_is_not_onedir(self):
        self.assertEqual("", il.exe_contents_dir(os.path.join(self.dir, "none.exe")))

    def _onedir(self, version="1.8.0"):
        _exe_with_contents(self.exe, il.contents_dir_name(version))
        c = os.path.join(self.dir, il.contents_dir_name(version))
        os.makedirs(os.path.join(c, "sub"))
        for rel in ("a.dll", os.path.join("sub", "b.pyd")):
            with open(os.path.join(c, rel), "wb") as f:
                f.write(os.urandom(300))
        il.write_manifest(self.dir, version)
        return c

    def test_a_whole_onedir_install_is_ok(self):
        self._onedir()
        self.assertTrue(il.layout_ok(self.exe))

    def test_a_onedir_exe_without_its_folder_is_not_ok(self):
        # What _ensure_installed_copy would leave if a onedir build copied its
        # exe alone to the canonical path.
        c = self._onedir()
        shutil.rmtree(c)
        self.assertFalse(il.layout_ok(self.exe))

    def test_a_onedir_install_missing_a_file_is_not_ok(self):
        c = self._onedir()
        os.remove(os.path.join(c, "sub", "b.pyd"))
        self.assertFalse(il.layout_ok(self.exe))


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, brand.CANONICAL_EXE_NAME), "wb") as f:
            f.write(b"MZexe")
        c = os.path.join(self.dir, "app-2.0.0", "deep", "er")
        os.makedirs(c)
        with open(os.path.join(c, "x.pyd"), "wb") as f:
            f.write(b"pyd")
        self.path = il.write_manifest(self.dir, "v2.0.0")
        self.m = il.load_manifest(self.path)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_shape(self):
        self.assertEqual("2.0.0", self.m["version"])
        self.assertEqual("app-2.0.0", self.m["contents"])
        self.assertEqual(brand.CANONICAL_EXE_NAME, self.m["exe"]["path"])
        self.assertEqual(["app-2.0.0/deep/er/x.pyd"], [f["path"] for f in self.m["files"]])

    def test_the_manifest_never_lists_itself(self):
        self.assertNotIn("app-2.0.0/manifest.json", [f["path"] for f in self.m["files"]])

    def test_whole_tree_verifies(self):
        self.assertEqual([], il.verify_tree(self.dir, self.m))

    def test_changed_bytes_of_the_same_size_fail_the_hash_check_only(self):
        with open(os.path.join(self.dir, "app-2.0.0", "deep", "er", "x.pyd"), "wb") as f:
            f.write(b"PYD")
        self.assertEqual(["sha256 app-2.0.0/deep/er/x.pyd"], il.verify_tree(self.dir, self.m))
        self.assertEqual([], il.verify_tree(self.dir, self.m, full_hash=False))

    def test_a_changed_exe_fails(self):
        with open(os.path.join(self.dir, brand.CANONICAL_EXE_NAME), "ab") as f:
            f.write(b"!")
        self.assertTrue(il.verify_tree(self.dir, self.m))
        self.assertEqual([], il.verify_tree(self.dir, self.m, include_exe=False))

    def test_a_path_escaping_the_install_is_refused(self):
        bad = dict(self.m, files=[{"path": "../../Windows/x.dll", "size": 1, "sha256": ""}])
        self.assertEqual(["bad manifest path '../../Windows/x.dll'"],
                         il.verify_tree(self.dir, bad, include_exe=False))

    def test_garbage_is_no_manifest(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual({}, il.load_manifest(self.path))


class RolloutTests(unittest.TestCase):
    MID = "00000005abcd"          # bucket 5

    def test_absent_or_broken_means_no(self):
        for r in (None, "", [], {"migrate_percent": "lots"}, {}):
            self.assertFalse(il.rollout_allows(r, self.MID), r)

    def test_percentage_by_stable_bucket(self):
        self.assertFalse(il.rollout_allows({"migrate_percent": 5}, self.MID))
        self.assertTrue(il.rollout_allows({"migrate_percent": 6}, self.MID))
        self.assertTrue(il.rollout_allows({"migrate_percent": 100}, "ffffffffffff"))
        self.assertFalse(il.rollout_allows({"migrate_percent": 0}, "000000000000"))

    def test_an_allow_listed_machine_goes_first(self):
        self.assertTrue(il.rollout_allows({"migrate_percent": 0, "machines": [self.MID.upper()]},
                                          self.MID))

    def test_machine_id_is_stable_and_anonymous(self):
        a, b = il.machine_id(), il.machine_id()
        self.assertEqual(a, b)
        self.assertEqual(12, len(a))
        int(a, 16)


class MarkerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_health_names_the_version(self):
        il.write_health("v1.8.0", self.dir)
        with open(os.path.join(self.dir, il.HEALTH_FILE)) as f:
            self.assertEqual("1.8.0", json.load(f)["version"])

    def test_bad_version_tolerates_powershells_bom(self):
        with open(os.path.join(self.dir, il.BAD_VERSION_FILE), "w", encoding="utf-8-sig") as f:
            f.write("1.8.1\r\n")
        self.assertEqual("1.8.1", il.read_bad_version(self.dir))

    def test_migration_failures_count_per_version(self):
        self.assertEqual(0, il.migration_failures("1.8.0", self.dir))
        il.record_migration_failure("1.8.0", "no network", self.dir)
        self.assertEqual(2, il.record_migration_failure("1.8.0", "", self.dir))
        # A newer release starts the count again.
        self.assertEqual(0, il.migration_failures("1.8.1", self.dir))


class StalePathTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for d in ("app-1.7.9", "app-1.8.0", "app-1.8.1", "pending-1.8.2", "models",
                  os.path.join("runtime", "_MEI123"), "phrases"):
            os.makedirs(os.path.join(self.dir, d))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _names(self, own):
        return sorted(os.path.relpath(p, self.dir) for p in il.stale_paths(self.dir, own))

    def test_other_versions_pending_and_unpacks_go(self):
        self.assertEqual(sorted(["app-1.7.9", "app-1.8.0", "pending-1.8.2",
                                 os.path.join("runtime", "_MEI123")]),
                         self._names("app-1.8.1"))

    def test_the_model_and_user_folders_never_do(self):
        names = self._names("app-1.8.1")
        self.assertNotIn("models", names)
        self.assertNotIn("phrases", names)

    def test_a_legacy_leftover_goes_only_once_this_folder_replaced_it(self):
        import brand
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        new = os.path.join(base, brand.DATA_DIR_NAME)
        legacy = os.path.join(base, brand.LEGACY_DATA_DIR_NAME)
        os.makedirs(os.path.join(legacy, "runtime"))
        os.makedirs(new)
        # Not migrated (no marker): the legacy folder may be what is in use.
        self.assertNotIn(legacy, il.stale_paths(new, "app-1.8.1"))
        with open(os.path.join(new, brand.MIGRATED_MARKER), "w") as f:
            f.write("{}")
        self.assertIn(legacy, il.stale_paths(new, "app-1.8.1"))
        # Never from any other folder.
        self.assertNotIn(legacy, il.stale_paths(self.dir, "app-1.8.1"))

    def test_the_folder_a_pending_rollback_needs_is_kept(self):
        _exe_with_contents(il.canonical_exe(self.dir) + il.PREVIOUS_SUFFIX, "app-1.8.0")
        self.assertNotIn("app-1.8.0", self._names("app-1.8.1"))
        # ...but not forever: a day-old backup is a leftover.
        old = time.time() - 2 * 86400
        os.utime(il.canonical_exe(self.dir) + il.PREVIOUS_SUFFIX, (old, old))
        self.assertIn("app-1.8.0", self._names("app-1.8.1"))


if __name__ == "__main__":
    unittest.main()
