"""Install the real build on a clean Windows machine and prove it works.

    python tools/selftest_install.py --setup dist\\FTC-Whisper-Setup.exe
                                     --onefile "dist\\FTC Whisper.exe"
                                     --report dist\\selftest

RUN ONLY ON A THROWAWAY MACHINE (the CI runner, Windows Sandbox, a clean VM):
it installs into the real %LOCALAPPDATA%\\FTC Whisper, registers with Windows,
stops every running copy of the app, and uninstalls at the end.

What it does, in the order an existing user meets it:

  1. the onefile bridge's --selftest, measuring what it unpacks per launch
  2. the onefile bridge started normally: it installs itself at the canonical
     path the way every release up to v1.7.x did, and answers /ping
  3. a setting is written into that install's config.json
  4. the installer is run silently while that copy is still running: it must
     stop it, switch the machine to the installed layout, keep the setting,
     and leave exactly ONE Installed apps entry
  5. the installed app started normally: /ping, health.json, and what it
     writes per launch (nothing unpacked)
  6. the installed exe's --selftest (real model, the bundle's own onnxruntime)
  7. "<exe> --uninstall /S": every registration gone, the folder gone
     (the speech model is set aside first and put back, for the CI cache)

Writes report.json plus every log into --report. Exit 0 only when all pass.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import brand  # noqa: E402
import install_layout  # noqa: E402

PING = "http://127.0.0.1:47832/ping"
NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PHRASE = "Revenue was up this quarter and the team did well."


def annotate(title: str, text: str, limit: int = 1500) -> None:
    """A GitHub error annotation: shown on the run page and readable through
    the public checks API, so a failed gate can be diagnosed without the
    (login-only) job log. Printed only on CI."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    body = (text or "(no detail)")[-limit:]
    body = body.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    title = title.replace(",", ";").replace("::", ":")
    print(f"::error title={title}::{body}", flush=True)


def log_tail(path: str, lines: int = 25) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return "\n".join(f.read().splitlines()[-lines:])
    except OSError as e:
        return f"unreadable: {e}"


class Report:
    def __init__(self, out: str):
        self.out = out
        self.data = {"checks": [], "measurements": {}}
        os.makedirs(out, exist_ok=True)

    def check(self, name: str, ok: bool, detail="") -> bool:
        self.data["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:2000]})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail and not ok else ""))
        if not ok:
            annotate(f"selftest: {name}", str(detail))
        return ok

    def measure(self, key: str, value) -> None:
        self.data["measurements"][key] = value
        print(f"[measure] {key} = {value}")

    def save(self) -> bool:
        passed = all(c["ok"] for c in self.data["checks"])
        self.data["passed"] = passed
        with open(os.path.join(self.out, "report.json"), "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        return passed


def make_wav(path: str) -> None:
    """16 kHz mono 16-bit speech from Windows' own synthesiser: no personal
    recording in the repo, and the words are known."""
    p = path.replace("'", "''")
    ps = ("Add-Type -AssemblyName System.Speech; "
          "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
          "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
          "[System.Speech.AudioFormat.AudioChannel]::Mono); "
          f"$s.SetOutputToWaveFile('{p}', $f); $s.Speak('{PHRASE}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=120)


def tree_stats(path: str, skip=("models",)) -> tuple:
    files = size = 0
    for root, dirs, names in os.walk(path):
        if root == path:
            dirs[:] = [d for d in dirs if d not in skip]
        for n in names:
            try:
                size += os.path.getsize(os.path.join(root, n))
                files += 1
            except OSError:
                pass
    return files, size


def stop_all() -> None:
    for image in ("FTC Whisper.exe", brand.DOWNLOAD_ASSET, brand.UPDATE_ASSET):
        subprocess.run(["taskkill", "/F", "/IM", image], capture_output=True, creationflags=NO_WIN)
    time.sleep(2)


def wait_ping(timeout: float) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(PING, timeout=2) as r:
                if json.loads(r.read().decode()).get("ok"):
                    return time.time() - t0
        except Exception:
            time.sleep(0.25)
    return -1.0


def selftest(exe: str, wav: str, out: str, watch: str) -> tuple:
    """Run --selftest, watching *watch* for what the launch writes. Returns
    (report dict, seconds, peak files, peak MB)."""
    t0 = time.time()
    p = subprocess.Popen([exe, "--selftest", wav, out])
    peak_f = peak_b = 0
    while p.poll() is None:
        f, b = tree_stats(watch, skip=())
        peak_f, peak_b = max(peak_f, f), max(peak_b, b)
        time.sleep(0.25)
    secs = time.time() - t0
    try:
        with open(out, "r", encoding="utf-8") as f:
            rep = json.load(f)
    except Exception as e:
        rep = {"error": f"no report: {e}"}
    return rep, round(secs, 1), peak_f, round(peak_b / 1e6, 1)


def reg_value(path: str, name: str = ""):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def uninstall_entries() -> list:
    """Every HKCU uninstall entry that is ours by name or by Inno's suffix."""
    import winreg
    base = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    found = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                name = reg_value(base + "\\" + sub, "DisplayName") or ""
                if sub == brand.UNINSTALL_KEY_NAME or sub.lower().endswith("_is1") \
                        or name in brand.product_names():
                    found.append(sub)
    except OSError:
        pass
    return found


def task_exists() -> bool:
    r = subprocess.run(["schtasks", "/query", "/tn", brand.TASK_NAME], capture_output=True,
                       creationflags=NO_WIN)
    return r.returncode == 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", required=True)
    ap.add_argument("--onefile", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args(argv)
    rep = Report(os.path.abspath(args.report))
    root = install_layout.install_dir()
    exe = install_layout.canonical_exe(root)
    wav = os.path.join(rep.out, "selftest.wav")
    make_wav(wav)
    stop_all()

    # 1. The onefile bridge, as every pre-1.8 client runs.
    r, secs, pf, pmb = selftest(os.path.abspath(args.onefile), wav,
                                os.path.join(rep.out, "selftest-onefile.json"),
                                os.path.join(root, "runtime"))
    rep.check("onefile --selftest transcribes", r.get("passed"), r)
    rep.check("onefile build reports its layout", r.get("layout") == "onefile", r.get("layout"))
    rep.measure("onefile_selftest_seconds", secs)
    rep.measure("onefile_unpacked_files_per_launch", pf)
    rep.measure("onefile_unpacked_mb_per_launch", pmb)

    # 2. The bridge started normally installs itself, like v1.7.x.
    t0 = time.time()
    subprocess.Popen([os.path.abspath(args.onefile)])
    ping = wait_ping(180)
    rep.check("onefile app answers /ping", ping >= 0)
    rep.measure("onefile_seconds_to_ping", round(ping, 1))
    deadline = time.time() + 60
    while time.time() < deadline and not (os.path.exists(exe) and uninstall_entries()):
        time.sleep(1)
    rep.check("onefile app installed itself at the canonical path",
              os.path.exists(exe) and not install_layout.is_installed_layout_exe(exe))

    # 3. A setting that must survive the migration.
    cfg_path = os.path.join(root, "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["custom_vocabulary"] = "Selftestword"
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        rep.check("wrote a setting into the onefile install", True)
    except Exception as e:
        rep.check("wrote a setting into the onefile install", False, e)

    # 4. The installer, silently, while that copy is running.
    t0 = time.time()
    p = subprocess.run([os.path.abspath(args.setup), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                        "/NORESTART", f"/LOG={os.path.join(rep.out, 'setup.log')}"],
                       timeout=900)
    rep.measure("install_seconds", round(time.time() - t0, 1))
    rep.check("installer exits 0", p.returncode == 0, p.returncode)
    for name in ("update.log",):
        try:
            shutil.copy(os.path.join(root, name), os.path.join(rep.out, name))
        except OSError:
            pass
    rep.check("canonical exe is the installed layout", install_layout.is_installed_layout_exe(exe))
    manifest = install_layout.load_manifest(os.path.join(
        root, install_layout.exe_contents_dir(exe), install_layout.MANIFEST_NAME))
    problems = install_layout.verify_tree(root, manifest) if manifest else ["no manifest"]
    rep.check("installed files match the manifest", not problems, problems)
    rep.check("no pending folder left", not [d for d in os.listdir(root)
                                             if d.startswith(brand.PENDING_DIR_PREFIX)])
    entries = uninstall_entries()
    rep.check("exactly one Installed apps entry, ours", entries == [brand.UNINSTALL_KEY_NAME], entries)
    us = reg_value(r"Software\Microsoft\Windows\CurrentVersion\Uninstall\\" + brand.UNINSTALL_KEY_NAME,
                   "UninstallString") or ""
    rep.check("uninstall entry runs the canonical exe", us.lower() == f'"{exe}" --uninstall'.lower(), us)
    cmd = reg_value("Software\\Classes\\" + brand.URL_SCHEME + r"\shell\open\command") or ""
    rep.check("URL protocol opens the canonical exe", exe.lower() in cmd.lower(), cmd)
    rep.check("logon task registered (Start with Windows ticked)", task_exists())
    try:
        import app_install
        rep.check("Start menu entry exists", os.path.exists(app_install.start_menu_link()))
    except Exception as e:
        rep.check("Start menu entry exists", False, e)
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            kept = json.load(f).get("custom_vocabulary")
    except Exception as e:
        kept = f"unreadable: {e}"
    rep.check("the user's setting survived", kept == "Selftestword", kept)

    # 5. The installed app, started normally.
    stop_all()
    # The onefile copy of step 2 reported health too; only this launch counts.
    try:
        os.remove(os.path.join(root, install_layout.HEALTH_FILE))
    except OSError:
        pass
    before = tree_stats(root)
    # Leftover unpack folders from steps 1-2 may still be there (the new app
    # deletes them once healthy): what matters is that this launch adds none.
    rt_before = tree_stats(os.path.join(root, "runtime"), skip=())[0]
    peak_rt = rt_before
    subprocess.Popen([exe], cwd=root)
    ping = wait_ping(180)
    rep.check("installed app answers /ping", ping >= 0)
    rep.measure("onedir_seconds_to_ping", round(ping, 1))
    deadline = time.time() + 120
    health = {}
    while time.time() < deadline:
        try:
            with open(os.path.join(root, install_layout.HEALTH_FILE), encoding="utf-8") as f:
                health = json.load(f)
            if health.get("version"):
                break
        except Exception:
            pass
        peak_rt = max(peak_rt, tree_stats(os.path.join(root, "runtime"), skip=())[0])
        time.sleep(0.5)
    rep.check("installed app reports health", bool(health.get("version")), health)
    time.sleep(5)
    after = tree_stats(root)
    rep.measure("onedir_new_files_per_launch", after[0] - before[0])
    rep.measure("onedir_new_mb_per_launch", round((after[1] - before[1]) / 1e6, 2))
    rep.check("installed app unpacks nothing", peak_rt <= rt_before,
              f"runtime files {rt_before} -> peak {peak_rt}")
    stop_all()

    # 6. The installed exe's own engine.
    r, secs, _pf, _pmb = selftest(exe, wav, os.path.join(rep.out, "selftest-installed.json"),
                                  os.path.join(root, "runtime"))
    rep.check("installed --selftest transcribes", r.get("passed"), r)
    rep.check("installed build reports the onedir layout", r.get("layout") == "onedir", r.get("layout"))
    rep.measure("onedir_selftest_seconds", secs)

    # 7. Uninstall. The model is set aside so the CI cache keeps it.
    models = os.path.join(root, "models")
    parked = os.path.join(os.environ.get("RUNNER_TEMP") or os.environ.get("TEMP", root + "-"),
                          "models-parked")
    if os.path.isdir(models):
        shutil.rmtree(parked, ignore_errors=True)
        shutil.move(models, parked)
    subprocess.run([exe, "--uninstall", "/S"], timeout=120)
    deadline = time.time() + 60
    while time.time() < deadline and os.path.exists(root):
        time.sleep(1)
    rep.check("uninstall removed the install folder", not os.path.exists(root))
    rep.check("uninstall removed the Installed apps entry", not uninstall_entries(), uninstall_entries())
    rep.check("uninstall removed the logon task", not task_exists())
    rep.check("uninstall removed the URL protocol",
              reg_value("Software\\Classes\\" + brand.URL_SCHEME) is None)
    if os.path.isdir(parked):
        os.makedirs(root, exist_ok=True)
        shutil.move(parked, models)

    ok = rep.save()
    print("ALL PASSED" if ok else "FAILED: see report.json")
    if not ok:
        for name in ("update.log", "setup.log"):
            annotate(f"selftest log: {name}", log_tail(os.path.join(rep.out, name)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
