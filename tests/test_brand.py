"""Guards for the product name split in brand.py.

Three things must never regress:
  1. Renaming the product changes only what people SEE. The on-disk names
     (folders, exe, launchers, registry keys) moved once, in v1.8.1, through a
     migration in installer/activate.ps1; the legacy values stay pinned here
     so that migration and clean-up can always find them.
  2. What older installed copies find by name (release assets, the CRM's URL
     scheme, the taskbar id, the signer) never changes.
  3. Nothing shown to a person hard-codes a product name. The name lives in
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
    def test_on_disk_names_are_the_products(self):
        # Moved in v1.8.1 (activate.ps1 migrates every installed copy). What a
        # person sees in Explorer, Task Manager, Startup apps and Installed apps.
        self.assertEqual("BrightLink Echo", brand.DATA_DIR_NAME)
        self.assertEqual("BrightLink Echo", brand.EXE_BASENAME)
        self.assertEqual("BrightLink Echo.exe", brand.CANONICAL_EXE_NAME)
        self.assertEqual("Global\\BrightLink_Echo_SingleInstance", brand.MUTEX_NAME)
        self.assertEqual("BrightLink Echo", brand.TASK_NAME)
        self.assertEqual("BrightLink Echo", brand.RUN_VALUE_NAME)
        self.assertEqual("brightlinkecho", brand.URL_SCHEME)
        self.assertEqual("BrightLinkEcho", brand.UNINSTALL_KEY_NAME)
        self.assertEqual("migrated.json", brand.MIGRATED_MARKER)

    def test_legacy_names_stay_findable(self):
        # What v1.8.0 and older left on every machine. The migration, the
        # clean-up and the uninstaller find them by exactly these names.
        self.assertEqual("FTC Whisper", brand.LEGACY_DATA_DIR_NAME)
        self.assertEqual("FTC Whisper.exe", brand.LEGACY_CANONICAL_EXE_NAME)
        self.assertEqual("Global\\FTC_Whisper_SingleInstance", brand.LEGACY_MUTEX_NAME)
        self.assertEqual("FTC Whisper", brand.LEGACY_TASK_NAME)
        self.assertEqual("FTC Whisper", brand.LEGACY_RUN_VALUE_NAME)
        self.assertEqual("ftcwhisper", brand.LEGACY_URL_SCHEME)
        self.assertEqual("FTCWhisper", brand.LEGACY_UNINSTALL_KEY_NAME)
        self.assertEqual("FTCWhisperSetup", brand.LEGACY_SETUP_MUTEX)

    def test_plumbing_keeps_its_original_values(self):
        # Each is found BY NAME by older installed copies, the CRM or Windows
        # itself. Changing one strands every copy that looks for it.
        self.assertEqual("FTC-Whisper.exe", brand.UPDATE_ASSET)
        self.assertEqual("FTC-Whisper-Setup.exe", brand.LEGACY_SETUP_UPDATE_ASSET)
        self.assertEqual("FTC-Whisper-rollout.json", brand.LEGACY_ROLLOUT_ASSET)
        self.assertEqual("BrightLink-Echo-Setup.exe", brand.SETUP_UPDATE_ASSET)
        self.assertEqual("BrightLink-Echo-rollout.json", brand.ROLLOUT_ASSET)
        # Taskbar pins and notifications group under it; its visible name is
        # registered separately, so the id itself never has to move.
        self.assertEqual("FTC.Whisper", brand.APP_USER_MODEL_ID)
        # Renamed 2026-09-22; older builds reach it through GitHub's redirect
        # from RJMURPHY0/FTC_Whisper, so that name must never be reused.
        self.assertEqual("RJMURPHY0/BrightLink-Echo", brand.GITHUB_REPO)
        self.assertEqual("FTC Whisper", brand.UNRECORDED_PRODUCT_NAME)
        # The installed-layout names (v1.8.0): every installed copy finds its
        # next version, its own files and its pending update by these.
        self.assertEqual("app-", brand.CONTENTS_DIR_PREFIX)
        self.assertEqual("pending-", brand.PENDING_DIR_PREFIX)
        # SmartScreen reputation is bound to this exact subject.
        self.assertEqual("CN=BRIGHTLINK (OS) LTD, O=BRIGHTLINK (OS) LTD, L=Syston, "
                         "S=Leicester, C=GB", brand.SIGNER_SUBJECT)

    def test_update_channels_never_collide(self):
        # The bridge, the installer, the rollout switch and the download are
        # four different files; two sharing a name would make a pre-1.8
        # updater install the installer as if it were the app.
        names = {brand.UPDATE_ASSET, brand.SETUP_UPDATE_ASSET, brand.ROLLOUT_ASSET,
                 brand.LEGACY_SETUP_UPDATE_ASSET, brand.LEGACY_ROLLOUT_ASSET}
        self.assertEqual(5, len(names))
        self.assertNotIn(brand.DOWNLOAD_ASSET, names)

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


class ModulesUseTheDataFolderTests(unittest.TestCase):
    """Every data path resolves through data_paths: the current folders on a
    new or migrated machine, the legacy ones on a machine not moved yet, and
    none of it follows the display name."""

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

    def _check(self, paths, folder="BrightLink Echo", exe="BrightLink Echo.exe"):
        local_dir = os.path.join(self.local, folder)
        roaming_dir = os.path.join(self.roaming, folder)
        self.assertEqual(local_dir, paths["app data"])
        self.assertEqual(os.path.join(local_dir, exe), paths["canonical exe"])
        self.assertEqual(local_dir, paths["install dir"])
        self.assertEqual(roaming_dir, paths["user data"])
        for key in ("models", "phrases"):
            self.assertTrue(paths[key].startswith(local_dir + os.sep), key)
        for key in ("audio", "session", "stats", "history"):
            self.assertTrue(paths[key].startswith(roaming_dir + os.sep), key)

    def test_a_new_machine_uses_the_current_folders(self):
        self._check(self._paths())

    def test_a_machine_not_moved_yet_keeps_its_legacy_folders(self):
        # A pre-1.8 copy on the bridge, or an update that has not run: moving
        # its data under it would lose the model, the session and history.
        os.makedirs(os.path.join(self.local, "FTC Whisper"))
        os.makedirs(os.path.join(self.roaming, "FTC Whisper"))
        self._check(self._paths(), "FTC Whisper", "FTC Whisper.exe")

    def test_a_migrated_machine_ignores_a_legacy_leftover(self):
        # activate.ps1 marks the new folder once it holds everything; a locked
        # file may still keep a legacy folder alive for a while.
        os.makedirs(os.path.join(self.local, "FTC Whisper"))
        os.makedirs(os.path.join(self.local, "BrightLink Echo"))
        with open(os.path.join(self.local, "BrightLink Echo", "migrated.json"), "w") as f:
            f.write("{}")
        os.makedirs(os.path.join(self.roaming, "BrightLink Echo"))
        self._check(self._paths())

    def test_a_folder_holding_the_current_exe_is_home_without_a_marker(self):
        # A fresh install, before any legacy folder existed; an old exe run
        # later recreates one, and must not pull the app back to it.
        os.makedirs(os.path.join(self.local, "BrightLink Echo"))
        with open(os.path.join(self.local, "BrightLink Echo", "BrightLink Echo.exe"), "w") as f:
            f.write("exe")
        os.makedirs(os.path.join(self.local, "FTC Whisper", "runtime"))
        os.makedirs(os.path.join(self.roaming, "BrightLink Echo"))
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
            "https://api.github.com/repos/RJMURPHY0/BrightLink-Echo/releases/latest",
            updater._GITHUB_API,
        )
        self.assertTrue(app_install.UNINSTALL_KEY.endswith("\\Uninstall\\BrightLinkEcho"))
        self.assertTrue(app_install.APP_PATHS_KEY.endswith("\\App Paths\\BrightLink Echo.exe"))
        self.assertEqual("Software\\Classes\\brightlinkecho", app_install.URL_PROTOCOL_KEY)
        self.assertEqual("BrightLink Echo", app_install.TASK_NAME)
        # What register() removes, and the uninstaller removes too.
        self.assertTrue(app_install.LEGACY_UNINSTALL_KEY.endswith("\\Uninstall\\FTCWhisper"))
        self.assertTrue(app_install.LEGACY_APP_PATHS_KEY.endswith("\\App Paths\\FTC Whisper.exe"))
        self.assertEqual("Software\\Classes\\ftcwhisper", app_install.LEGACY_URL_PROTOCOL_KEY)


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
        files.append("echo.spec")
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
        self.assertEqual(brand.CANONICAL_EXE_NAME, after["OriginalFilename"])
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
        spec = open(os.path.join(ROOT, "echo.spec"), encoding="utf-8").read()
        self.assertIn("name=_brand.EXE_BASENAME", spec)       # frozen, never the display name
        self.assertIn("_brand.render_version_info(", spec)
        self.assertIn("version=_version_file", spec)
        # The bridge only ever runs as a pre-1.8 copy's exe, in the legacy folder.
        self.assertIn("_brand.LEGACY_DATA_DIR_NAME + '\\\\runtime'", spec)
        self.assertIn("'brand',", spec)                        # hidden import

    def test_spec_builds_the_bridge_and_the_installed_layout(self):
        spec = open(os.path.join(ROOT, "echo.spec"), encoding="utf-8").read()
        # The installed layout's contents folder is named after the version.
        self.assertIn("_contents = _brand.CONTENTS_DIR_PREFIX + _APP_VERSION", spec)
        self.assertIn("contents_directory=_contents", spec)
        self.assertIn("COLLECT(", spec)
        self.assertIn("name=_brand.EXE_BASENAME,", spec.split("COLLECT(", 1)[1])
        # activate.ps1 ships inside each version, and only in the onedir build.
        self.assertIn("'installer', 'activate.ps1'", spec.split("COLLECT(", 1)[1])
        onefile_block = spec.split("if _BUILD in ('both', 'onefile'):", 1)[1] \
                            .split("if _BUILD in ('both', 'onedir'):", 1)[0]
        self.assertNotIn("activate.ps1", onefile_block)
        self.assertIn("write_manifest(", spec)
        # Neither build is ever packed: both EXEs and the COLLECT say so.
        self.assertNotIn("upx=True", spec)
        self.assertGreaterEqual(spec.count("upx=False,"), 3)

    def test_the_installer_leaves_one_installed_apps_entry_and_no_admin(self):
        iss = open(os.path.join(ROOT, "installer", "echo.iss"), encoding="utf-8").read()
        for line in ("PrivilegesRequired=lowest", "Uninstallable=no", "CreateUninstallRegKey=no",
                     "CloseApplications=no", "DefaultDirName={code:InstallRoot}",
                     "SetupMutex={#SetupMutex},{#LegacySetupMutex}"):
            self.assertIn(line, iss)
        # Staging runs while the app is open, so no AppMutex directive.
        self.assertNotIn("\nAppMutex=", iss)
        self.assertIn("VersionInfoOriginalFileName={#OutputBase}.exe", iss)
        self.assertIn("/STAGEONLY", iss)
        self.assertIn("-Mode Install -KillCopiesElsewhere", iss)
        self.assertTrue(all(ord(c) < 128 for c in iss))
        import tools.build_installer as bi
        d = bi.defines("dist", "out", "w.png", "s.png", "1.8.0")
        self.assertEqual("BrightLink-Echo-Setup", d["OutputBase"])
        self.assertNotEqual(d["OutputBase"] + ".exe", brand.CANONICAL_EXE_NAME)
        self.assertEqual("app-1.8.0", d["ContentsDir"])
        self.assertEqual("pending-1.8.0", d["PendingDir"])
        self.assertEqual(brand.PRODUCT_NAME, d["AppName"])
        self.assertEqual(brand.DATA_DIR_NAME, d["DataDir"])
        self.assertEqual(brand.LEGACY_DATA_DIR_NAME, d["LegacyDataDir"])
        self.assertEqual(brand.LEGACY_CANONICAL_EXE_NAME, d["LegacyExeName"])
        # A v1.8.0 updater stages without /DIR and checks the legacy exe name.
        self.assertIn("if IsStageOnly and not HasDirParam then", iss)
        self.assertIn('DestName: "{#LegacyExeName}"', iss)
        self.assertEqual("1.8.0.0", d["FileVersion"])


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

    # ── The installed layout (v1.8.0) ─────────────────────────────────────

    def _order(self):
        return [s.get("name") for s in self.wf["jobs"]["build-windows"]["steps"]]

    def test_every_release_carries_all_six_assets(self):
        # v1.8.0 copies fetch the installer and rollout file under the legacy
        # names; a release without them strands every one of them.
        files = self.steps["Publish versioned release"]["with"]["files"]
        check = self.steps["Check the release has every asset"]["env"]["FILES"]
        for out in ("UPDATE_ASSET", "SETUP_ASSET", "DOWNLOAD_ASSET", "ROLLOUT_ASSET",
                    "LEGACY_SETUP_ASSET", "LEGACY_ROLLOUT_ASSET"):
            self.assertIn(f"steps.version.outputs.{out}", files)
            self.assertIn(f"steps.version.outputs.{out}", check)
        read = self.steps["Read version and product names"]["run"]
        for name in ("brand.SETUP_UPDATE_ASSET", "brand.ROLLOUT_ASSET", "brand.SIGNER_SUBJECT",
                     "brand.LEGACY_SETUP_UPDATE_ASSET", "brand.LEGACY_ROLLOUT_ASSET"):
            self.assertIn(name, read)
        copy = self.steps["Name the release assets"]["run"]
        # The download people get is the installer, under the name every
        # existing link already uses.
        self.assertIn('"dist\\installer\\$env:SETUP_ASSET" "dist\\$env:DOWNLOAD_ASSET"', copy)

    def test_every_shipped_exe_is_signed_and_checked_for_our_signer(self):
        order = self._order()
        for step in ("Sign executable (Azure Artifact Signing)",
                     "Sign installed-layout executable", "Sign installer"):
            self.assertTrue(self.steps[step]["uses"].startswith("azure/artifact-signing-action@"))
        # The onedir exe is signed before the manifest describes it and before
        # the installer packs it; the installer after it is built.
        self.assertLess(order.index("Sign installed-layout executable"),
                        order.index("Write the installed-layout manifest"))
        self.assertLess(order.index("Write the installed-layout manifest"), order.index("Build installer"))
        self.assertLess(order.index("Build installer"), order.index("Sign installer"))
        verify = self.steps["Verify signature"]["run"]
        for f in ("$env:UPDATE_ASSET", "$env:SETUP_ASSET", "$env:LEGACY_SETUP_ASSET",
                  "$env:DOWNLOAD_ASSET", "$env:DIST_DIR\\$env:DIST_EXE"):
            self.assertIn(f, verify)
        self.assertIn("$env:SIGNER", verify)

    def test_inno_setup_is_pinned_by_version_and_hash(self):
        env = self.wf["jobs"]["build-windows"]["env"]
        self.assertRegex(env["INNO_VERSION"], r"^\d+\.\d+\.\d+$")
        self.assertIn(env["INNO_VERSION"], env["INNO_URL"])
        self.assertRegex(env["INNO_SHA256"], r"^[0-9a-f]{64}$")
        self.assertIn("$env:INNO_SHA256", self.steps["Install Inno Setup (pinned)"]["run"])

    def test_the_installed_build_is_proven_before_anything_is_published(self):
        order = self._order()
        self.assertIn("tools/selftest_install.py", self.steps["Install and self-test"]["run"])
        self.assertNotIn("continue-on-error", self.steps["Install and self-test"])
        for later in ("Check the release has every asset", "Publish versioned release"):
            self.assertLess(order.index("Install and self-test"), order.index(later))
        self.assertLess(order.index("Check the release has every asset"),
                        order.index("Publish versioned release"))

    def test_releases_never_build_concurrently(self):
        self.assertIs(False, self.wf["concurrency"]["cancel-in-progress"])

    def test_the_rollout_file_starts_closed(self):
        with open(os.path.join(ROOT, "rollout.json"), encoding="utf-8") as f:
            import json
            rollout = json.load(f)
        self.assertIn("migrate_percent", rollout)
        self.assertIsInstance(rollout["migrate_percent"], int)


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
