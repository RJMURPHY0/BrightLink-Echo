# Handling antivirus false positives

Until releases are code-signed (see `docs/CODE_SIGNING.md`), an unsigned onefile
PyInstaller exe will occasionally be flagged by Windows Defender/SmartScreen or a
third-party antivirus. These are **false positives** — the app is not malware —
but they still block users. This is how to clear them.

> Once code signing is live, flags drop dramatically and this becomes a rare
> stopgap. Signing is the real fix; the steps below are the free interim measures.

---

## 1. Check the current detection rate

Every CI release now runs a **VirusTotal scan** (see the "Scan with VirusTotal"
step in the workflow) if the `VT_API_KEY` secret is set. The workflow log prints
an analysis URL — open it to see which engines flag the installer
(`FTC-Whisper-Setup.exe`, the same bytes as the `BrightLink-Echo.exe`
download), the onefile bridge (`FTC-Whisper.exe`) and the installed exe.

To enable it: get a free API key at <https://www.virustotal.com/gui/my-apikey>
and add it as a repo secret named `VT_API_KEY` (Settings → Secrets and variables
→ Actions). No key = the step just skips.

You can also scan any exe manually by dragging it onto
<https://www.virustotal.com>.

---

## 2. Report the false positive to the vendors flagging it

Submit the exe (or its SHA-256, shown on VirusTotal) as a false positive. The two
that matter most for reach:

- **Microsoft Defender / SmartScreen** — the big one on Windows.
  Submit at <https://www.microsoft.com/en-us/wdsi/filesubmission>
  → choose "Software developer" → "Incorrectly detected as malware" (false
  positive). Turnaround is usually a day or two. This also helps SmartScreen
  reputation.

- **Any third-party AV that flagged it** — each has its own false-positive form:
  - Avast/AVG: <https://www.avast.com/false-positive-file-form.php>
  - Bitdefender: <https://www.bitdefender.com/consumer/support/answer/29358/>
  - Kaspersky: <https://opentip.kaspersky.com/>
  - Malwarebytes: <https://www.malwarebytes.com/false-positive>
  - McAfee/Trellix, Norton/Gen, ESET: submit via their researcher/false-positive
    portals (search "<vendor> false positive submission").

Attach the release exe and note it's a legitimate open-source dictation tool.

---

## 3. What the build already does (v1.6.29, installed layout v1.8.0)

Don't undo these — each one exists to keep the detection rate down:

- **Installed, not self-extracting (v1.8.0).** Installed copies run a
  PyInstaller *onedir* build from `%LOCALAPPDATA%\FTC Whisper\app-<version>\`,
  laid down once by a signed Inno Setup installer. Nothing is unpacked at
  launch: measured on 2026-09-29, 0 files written per start, against 5,278
  files / 305 MB for the onefile build. See
  `docs/decisions/release-updater.md`, 2026-09-29.
- **The onefile build still exists** as `FTC-Whisper.exe`, the bridge that
  pre-1.8 clients install before migrating. It keeps the measures below.
- **No UPX / no packer** (`upx=False`) on every build. Packed exes trigger
  *more* heuristics.
- **The onefile bridge unpacks outside `%TEMP%`** (`runtime_tmpdir` in
  `echo.spec`). Unpacking DLLs into `%TEMP%\_MEIxxxxxx` looks exactly
  like malware staging, and several products block the DLL loads *even after
  the user allows the exe*. It unpacks to `%LOCALAPPDATA%\FTC Whisper\runtime\`,
  a **stable path** an admin can exclude once. The installed layout empties
  that folder once it is healthy.
- **Signed:** the bridge, the installed exe and the installer, all by
  BRIGHTLINK (OS) LTD. Bundled third-party DLLs are not re-signed (see the
  2026-09-29 decision).
- **Full version metadata** (`version_info.txt`, including Comments and
  LegalTrademarks) on the app and the installer. Sparse or blank metadata
  scores against you.
- **Runs as `asInvoker`**, and the installer is per-user (`PrivilegesRequired=lowest`).
  Nothing ever requests admin.
- **No `-WindowStyle Hidden` on any PowerShell start (v1.8.0).** The installer's
  `activate.ps1`, the update swap and the uninstall cleanup are already
  windowless (`CREATE_NO_WINDOW` / `SW_HIDE`), so the flag did nothing except
  match the "hidden PowerShell" pattern behaviour shields score. Pinned in
  `tests/test_av_hardening.py`.
- **`activate.ps1` is Authenticode-signed** with the same certificate (v1.8.0,
  best effort: the "Report the activation script's signature" step warns if it
  was not), so AMSI and AV engines see a publisher-vouched script.

### After every release that changes the installer or the bundle

1. Open the VirusTotal links in the release run's log (the installer, the
   bridge and the installed exe).
2. For each engine that flags a file, submit it on that vendor's form (section
   2). For **Avast/AVG** submit `BrightLink-Echo.exe` *and* the installed
   `%LOCALAPPDATA%\FTC Whisper\FTC Whisper.exe`: their detections are per file
   hash, so every release's new bytes start fresh.
3. Submit the installer to Microsoft (section 2) even when nothing flags it:
   it builds SmartScreen reputation for the new file faster.

### Not done yet, on purpose

- **Compiling PyInstaller's bootloader from source.** The stock prebuilt
  bootloader is shared with a lot of malware, so some engines (Avast among
  them) flag it on sight; a bootloader built in CI has bytes of its own. It
  also changes the bridge every pre-1.8 client installs, whose exact 6.22.3
  bootloader is what recovers v1.6.79 installs (`tests/test_pyi_runtime.py`).
  Do it only with a dry run proven by `migration-e2e.yml` (the v1.6.79 job)
  before it is published.

### If a user is still blocked

Ask them to allow-list the two stable paths rather than the exe alone:

```
%LOCALAPPDATA%\FTC Whisper\
```

That single folder covers the exe, the unpack folder and the model.

---

## 4. What NOT to do

- **Don't add UPX** or any packer — see above.
- **Don't obfuscate** the code to "hide" from AV — that makes detection worse.

---

## 5. Onedir + an installer: done in v1.8.0

Switching from **onefile to onedir + an Inno Setup installer** removed the
self-extraction step, the strongest heuristic left after signing. The updater
was redesigned for it (versioned `app-<version>` folders, `activate.ps1`, a
staged and verified switch, rollback), and `FTC-Whisper.exe` stays a onefile
bridge, so every older client still reaches the new layout. The design, the
per-version transition and the measurements are in
`docs/decisions/release-updater.md` (2026-09-29). CI's VirusTotal step scans
the installer, the bridge and the installed exe on every build; compare those
counts with the last onefile release's `BrightLink-Echo.exe` when judging
whether a flag is new.
