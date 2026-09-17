"""Guards for the product name split in brand.py.

Two things must never regress:
  1. Renaming the product changes only what people SEE. Every folder, exe,
     registry key, scheme and release asset that installed copies find by name
     keeps its original value. Moving one loses users their 660 MB model,
     sign-in, shortcuts or auto-update.
  2. Nothing shown to a person hard-codes a product name. The name lives in
     brand.py alone, so the next rename is a one-line change.
"""

import ast
import inspect
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import brand  # noqa: E402

LEGACY = brand.UNRECORDED_PRODUCT_NAME


class FrozenIdentityTests(unittest.TestCase):
    def test_plumbing_keeps_its_original_values(self):
        # Each is found BY NAME by installed copies, the updater, the CRM or
        # Windows itself. Changing one strands every existing install.
        self.assertEqual("FTC Whisper", brand.DATA_DIR_NAME)
        self.assertEqual("FTC Whisper", brand.EXE_BASENAME)
        self.assertEqual("FTC Whisper.exe", brand.CANONICAL_EXE_NAME)
        self.assertEqual("Global\\FTC_Whisper_SingleInstance", brand.MUTEX_NAME)
        self.assertEqual("FTC Whisper", brand.TASK_NAME)
        self.assertEqual("FTC Whisper", brand.RUN_VALUE_NAME)
        self.assertEqual("ftcwhisper", brand.URL_SCHEME)
        self.assertEqual("FTCWhisper", brand.UNINSTALL_KEY_NAME)
        self.assertEqual("FTC-Whisper.exe", brand.UPDATE_ASSET)
        self.assertEqual("RJMURPHY0/FTC_Whisper", brand.GITHUB_REPO)
        self.assertEqual("FTC Whisper", brand.UNRECORDED_PRODUCT_NAME)

    def test_the_first_name_stays_on_the_legacy_list(self):
        # Shortcut renames, launcher clean-up and history icons all look up
        # older names from this list.
        self.assertIn("FTC Whisper", brand.LEGACY_PRODUCT_NAMES)
        self.assertEqual(brand.PRODUCT_NAME, brand.product_names()[0])
        self.assertIn("FTC Whisper", brand.product_names())
        self.assertEqual(len(set(brand.product_names())), len(brand.product_names()))

    def test_the_update_channel_is_not_the_download(self):
        # Installed updaters fetch UPDATE_ASSET; people download DOWNLOAD_ASSET.
        # Folding them together would rename the channel with the product.
        self.assertTrue(brand.DOWNLOAD_ASSET.endswith(".exe"))
        self.assertNotIn(" ", brand.DOWNLOAD_ASSET)
        if brand.PRODUCT_NAME != LEGACY:
            self.assertNotEqual(brand.UPDATE_ASSET, brand.DOWNLOAD_ASSET)

    def test_brand_imports_nothing_at_module_level(self):
        # The spec, the uninstaller and app.py's pre-import startup guard all
        # read brand.py: a module-level import there would run before the
        # guard that protects against foreign native libraries.
        tree = ast.parse(open(os.path.join(ROOT, "brand.py"), encoding="utf-8").read())
        top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([], top)


class ModulesUseFrozenValuesTests(unittest.TestCase):
    """Every data path and key resolves to the frozen names, and keeps doing
    so when the display name changes."""

    @classmethod
    def setUpClass(cls):
        # Import before any test patches brand: module-level names captured at
        # import time must hold the real values for every later test.
        import app  # noqa: F401
        import app_install  # noqa: F401
        import asr_engine  # noqa: F401

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        local = os.path.join(self._tmp.name, "Local")
        roaming = os.path.join(self._tmp.name, "Roaming")
        os.makedirs(local)
        os.makedirs(roaming)
        self._env = mock.patch.dict(os.environ, {"LOCALAPPDATA": local, "APPDATA": roaming})
        self._env.start()
        self.local, self.roaming = local, roaming

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _paths(self):
        import app
        import app_install
        import asr_engine
        import audio_store
        import auth
        import phrase_learning
        import stats
        import supabase_client

        return {
            "app data": app._app_data_dir(),
            "canonical exe": app._stable_exe_path(),
            "install dir": app_install._install_dir(),
            "user data": app_install._user_data_dir(),
            "models": asr_engine.models_dir(),
            "audio": audio_store.audio_dir(),
            "session": auth._session_path(),
            "stats": stats._stats_path(),
            "history": supabase_client._local_history_path(),
            "phrases": phrase_learning.store_dir(),
        }

    def _check(self, paths):
        local_dir = os.path.join(self.local, "FTC Whisper")
        roaming_dir = os.path.join(self.roaming, "FTC Whisper")
        self.assertEqual(local_dir, paths["app data"])
        self.assertEqual(os.path.join(local_dir, "FTC Whisper.exe"), paths["canonical exe"])
        self.assertEqual(local_dir, paths["install dir"])
        self.assertEqual(roaming_dir, paths["user data"])
        for key in ("models", "phrases"):
            self.assertTrue(paths[key].startswith(local_dir + os.sep), key)
        for key in ("audio", "session", "stats", "history"):
            self.assertTrue(paths[key].startswith(roaming_dir + os.sep), key)

    def test_data_paths_use_the_frozen_folder(self):
        self._check(self._paths())

    def test_a_rename_moves_no_data(self):
        with mock.patch.object(brand, "PRODUCT_NAME", "Some Other Name"), \
                mock.patch.object(brand, "DOWNLOAD_ASSET", "Some-Other-Name.exe"):
            self._check(self._paths())

    def test_keys_and_update_channel_use_frozen_values(self):
        import app_install
        import updater

        self.assertEqual("FTC-Whisper.exe", updater._DOWNLOAD_FILENAME)
        self.assertEqual(
            "https://api.github.com/repos/RJMURPHY0/FTC_Whisper/releases/latest",
            updater._GITHUB_API,
        )
        self.assertTrue(app_install.UNINSTALL_KEY.endswith("\\Uninstall\\FTCWhisper"))
        self.assertTrue(app_install.APP_PATHS_KEY.endswith("\\App Paths\\FTC Whisper.exe"))
        self.assertEqual("Software\\Classes\\ftcwhisper", app_install.URL_PROTOCOL_KEY)
        self.assertEqual("FTC Whisper", app_install.TASK_NAME)


def _docstring_nodes(tree):
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                nodes.add(id(body[0].value))
    return nodes


def _name_literals(path, pattern):
    """(line, text) for every string or bytes literal that matches, skipping
    docstrings and comments (neither is ever shown to a person)."""
    with open(path, encoding="utf-8-sig") as f:
        tree = ast.parse(f.read(), filename=path)
    skip = _docstring_nodes(tree)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or id(node) in skip:
            continue
        value = node.value
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        if isinstance(value, str) and pattern.search(value):
            hits.append((node.lineno, value))
    return hits


class NoHardCodedNameTests(unittest.TestCase):
    def _runtime_files(self):
        files = [f for f in os.listdir(ROOT) if f.endswith(".py") and f != "brand.py"]
        files.append("ftc_whisper.spec")
        return sorted(files)

    def test_no_display_name_outside_brand(self):
        # The display form has a space. Temp-file names like "FTC-Whisper-new.exe"
        # are plumbing no one sees; they are allowed.
        names = list(brand.product_names())
        pattern = re.compile("|".join(re.escape(n).replace("\\ ", r"\s+") for n in names),
                             re.IGNORECASE)
        found = {}
        for name in self._runtime_files():
            hits = _name_literals(os.path.join(ROOT, name), pattern)
            if hits:
                found[name] = hits
        self.assertEqual({}, found,
                         "use brand.PRODUCT_NAME (shown) or a frozen brand constant (plumbing)")

    def test_the_scan_sees_bytes_and_f_strings(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write('"""FTC Whisper docstring is fine."""\n'
                    'a = b"<h2>return to FTC Whisper</h2>"\n'
                    'b = f"FTC  Whisper {1}"\n')
            path = f.name
        try:
            hits = _name_literals(path, re.compile(r"FTC\s+Whisper", re.IGNORECASE))
        finally:
            os.remove(path)
        self.assertEqual([2, 3], sorted(line for line, _ in hits))


class VersionResourceTests(unittest.TestCase):
    def _template(self):
        with open(os.path.join(ROOT, "version_info.txt"), encoding="utf-8-sig") as f:
            return f.read()

    def _strings(self, text):
        return dict(re.findall(r"StringStruct\('([^']+)',\s*'((?:[^'\\]|\\.)*)'\)", text))

    def test_names_come_from_brand_and_numbers_do_not_move(self):
        template = self._template()
        rendered = brand.render_version_info(template, 2026)
        before, after = self._strings(template), self._strings(rendered)
        self.assertEqual(brand.PRODUCT_NAME, after["ProductName"])
        self.assertEqual(brand.PRODUCT_NAME, after["FileDescription"])
        self.assertEqual(brand.COMPANY_NAME, after["CompanyName"])
        self.assertEqual("FTC Whisper.exe", after["OriginalFilename"])
        self.assertNotIn(" ", after["InternalName"])
        self.assertIn("2026", after["LegalCopyright"])
        for key in ("FileVersion", "ProductVersion", "Comments"):
            self.assertEqual(before[key], after[key], key)
        numbers = re.compile(r"(?:filevers|prodvers)=\([^)]*\)")
        self.assertEqual(numbers.findall(template), numbers.findall(rendered))

    def test_pyinstaller_accepts_the_rendered_file(self):
        try:
            from PyInstaller.utils.win32.versioninfo import load_version_info_from_text_file
        except ImportError:
            self.skipTest("PyInstaller not installed")
        with mock.patch.object(brand, "COMPANY_NAME", "O'Neill \\ Sons Ltd"):
            rendered = brand.render_version_info(self._template(), 2026)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(rendered)
            path = f.name
        try:
            info = load_version_info_from_text_file(path)
        finally:
            os.remove(path)

        values = {}

        def walk(obj):
            if hasattr(obj, "name") and hasattr(obj, "val"):
                values[obj.name] = obj.val
            for kid in getattr(obj, "kids", None) or []:
                walk(kid)

        walk(info)
        self.assertEqual("O'Neill \\ Sons Ltd", values["CompanyName"])
        self.assertEqual(brand.PRODUCT_NAME, values["ProductName"])

    def test_a_missing_name_string_fails_the_build(self):
        template = self._template().replace("StringStruct('ProductName'", "StringStruct('Gone'")
        with self.assertRaises(ValueError):
            brand.render_version_info(template, 2026)

    def test_spec_takes_names_from_brand(self):
        spec = open(os.path.join(ROOT, "ftc_whisper.spec"), encoding="utf-8").read()
        self.assertIn("name=_brand.EXE_BASENAME", spec)       # frozen, never the display name
        self.assertIn("_brand.render_version_info(", spec)
        self.assertIn("version=_version_file", spec)
        self.assertIn("_brand.DATA_DIR_NAME + '\\\\runtime'", spec)
        self.assertIn("'brand',", spec)                        # hidden import


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        path = os.path.join(ROOT, ".github", "workflows", "build-release.yml")
        with open(path, encoding="utf-8") as f:
            self.text = f.read()
        self.wf = yaml.safe_load(self.text)
        self.steps = {s.get("name"): s for s in self.wf["jobs"]["build-windows"]["steps"]}

    def test_both_assets_are_published_from_one_build(self):
        files = self.steps["Publish versioned release"]["with"]["files"]
        self.assertIn("steps.version.outputs.UPDATE_ASSET", files)
        self.assertIn("steps.version.outputs.DOWNLOAD_ASSET", files)
        copy = self.steps["Name the release assets"]["run"]
        self.assertIn('"dist\\$env:DIST_EXE" "dist\\$env:UPDATE_ASSET"', copy)
        read = self.steps["Read version and product names"]["run"]
        self.assertIn("brand.UPDATE_ASSET", read)
        self.assertIn("brand.EXE_BASENAME", read)

    def test_manual_runs_are_dry_runs_unless_ticked(self):
        on = self.wf.get("on", self.wf.get(True))
        publish = on["workflow_dispatch"]["inputs"]["publish"]
        self.assertIs(False, publish["default"])
        self.assertIn("inputs.publish", self.steps["Publish versioned release"]["if"])
        self.assertIn("!inputs.publish", self.steps["Keep the build for inspection (dry run)"]["if"])

    def test_signing_uses_oidc_and_no_stored_secret(self):
        self.assertEqual("write", self.wf["permissions"]["id-token"])
        self.assertEqual("release", self.wf["jobs"]["build-windows"]["environment"])
        self.assertTrue(self.steps["Sign executable (Azure Artifact Signing)"]["uses"]
                        .startswith("azure/artifact-signing-action@"))
        self.assertTrue(self.steps["Azure login (GitHub OIDC)"]["uses"].startswith("azure/login@"))
        self.assertNotIn("AZURE_CLIENT_SECRET", self.text)
        self.assertNotIn("trusted-signing-action", self.text)

    def test_partial_or_required_signing_config_fails(self):
        run = self.steps["Decide whether to sign"]["run"]
        self.assertIn("only partly configured", run)
        self.assertIn("REQUIRE_SIGNING", run)


class UpdateAnnouncementTests(unittest.TestCase):
    def setUp(self):
        import updater
        self.announce = updater.update_announcement

    def test_fresh_install_and_non_upgrades_say_nothing(self):
        self.assertIsNone(self.announce("", "", "1.6.81", "BrightLink Echo"))
        self.assertIsNone(self.announce("1.6.81", "BrightLink Echo", "1.6.81", "BrightLink Echo"))
        self.assertIsNone(self.announce("1.6.82", "BrightLink Echo", "1.6.81", "BrightLink Echo"))

    def test_upgrade_from_before_names_were_recorded_announces_the_rename(self):
        notice = self.announce("1.6.80", "", "1.6.81", "BrightLink Echo")
        self.assertEqual(f"{LEGACY} is now BrightLink Echo", notice["title"])
        self.assertIn("v1.6.81", notice["message"])
        self.assertIn(LEGACY, notice["toast"])

    def test_plain_upgrade_is_a_plain_notice(self):
        notice = self.announce("1.6.81", "BrightLink Echo", "1.6.82", "BrightLink Echo")
        self.assertEqual("BrightLink Echo", notice["title"])
        self.assertIn("Updated to v1.6.82", notice["message"])

    def test_a_case_fix_is_not_announced_as_a_rename(self):
        notice = self.announce("1.6.81", "Brightlink Echo", "1.6.82", "BrightLink Echo")
        self.assertNotIn(" is now ", notice["title"])

    def test_app_sends_one_notice_and_records_the_name(self):
        import app

        src = inspect.getsource(app.WhisperFlowApp._announce_update_if_any)
        self.assertEqual(1, src.count("self.tray.notify("))
        self.assertIn("write_last_run_name(brand.PRODUCT_NAME)", src)
        self.assertIn("update_announcement(", src)


class OwnIconTests(unittest.TestCase):
    def test_history_rows_under_any_of_our_names_get_our_icon(self):
        import app_icons

        self.assertEqual(brand.PRODUCT_NAME, app_icons.SELF_APP_NAME)
        for name in brand.product_names():
            self.assertEqual(app_icons.SELF_BRAND_SLUG, app_icons._BRAND_ALIASES[name.lower()])


if __name__ == "__main__":
    unittest.main()
