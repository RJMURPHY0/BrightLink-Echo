"""
Windows audio engine health and recovery.

When the Windows audio engine (audiodg.exe under the Audiosrv service) hangs,
every app gets an open input stream that carries nothing, and no amount of
reopening our own stream helps (observed 2026-10-05: five dead dictations in a
row, then Windows killed Audiosrv for hanging while the hung audiodg.exe lived
on). The only cure is killing audiodg.exe and restarting Audiosrv, which needs
admin rights, so restart() asks once through the normal Windows UAC prompt.
"""

import base64
import subprocess
import sys

# Exit codes from restart(): 0 = restarted, 1223 = the user declined the UAC
# prompt (ERROR_CANCELLED), anything else = the restart itself failed.
RESTARTED = 0
CANCELLED = 1223

_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW

# Runs elevated. audiodg.exe is killed explicitly because a hung one can
# outlive its service (it did on 2026-10-05), and a fresh Audiosrv then hands
# every new stream to the corpse. A hung service can also make Restart-Service
# wait forever, so its host process is killed instead, but only when that
# svchost hosts Audiosrv alone (low-RAM machines share hosts between services).
_ELEVATED_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
Stop-Process -Name audiodg -Force
$svc = Get-CimInstance Win32_Service -Filter "Name='Audiosrv'"
if ($svc -and $svc.ProcessId -gt 0) {
  $shared = @(Get-CimInstance Win32_Service -Filter "ProcessId=$($svc.ProcessId)").Count
  if ($shared -eq 1) { Stop-Process -Id $svc.ProcessId -Force }
  else { Stop-Service Audiosrv -Force -NoWait }
}
for ($i = 0; $i -lt 40 -and (Get-Service Audiosrv).Status -ne 'Stopped'; $i++) { Start-Sleep -Milliseconds 250 }
# A service that never stopped was never restarted: it is still 'Running' below,
# which would otherwise report success for a restart that did not happen.
if ((Get-Service Audiosrv).Status -ne 'Stopped') { exit 3 }
Start-Service Audiosrv
for ($i = 0; $i -lt 40 -and (Get-Service Audiosrv).Status -ne 'Running'; $i++) { Start-Sleep -Milliseconds 250 }
if ((Get-Service Audiosrv).Status -eq 'Running') { exit 0 } else { exit 2 }
"""


def _encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def service_running(timeout: float = 5.0) -> bool:
    """True when the Windows Audio service reports RUNNING. Needs no admin.
    Any failure to ask counts as running, so a broken query never escalates a
    healthy machine."""
    if sys.platform != "win32":
        return True
    try:
        out = subprocess.run(
            ["sc.exe", "query", "Audiosrv"], capture_output=True, text=True,
            timeout=timeout, creationflags=_NO_WINDOW,
        ).stdout
    except Exception as e:
        print(f"[AudioEngine] Service query failed: {e}")
        return True
    return "RUNNING" in out.upper() if "STATE" in out.upper() else True


def restart(timeout: float = 300.0) -> int:
    """Kill the hung audio engine and restart Windows Audio, via one UAC
    prompt. Blocks until done; call it off the UI thread. Returns RESTARTED,
    CANCELLED, or another non-zero code on failure."""
    if sys.platform != "win32":
        return 1
    inner = _encoded(_ELEVATED_SCRIPT)
    # Start-Process throws when the user says No to the UAC prompt.
    outer = (
        "try { $p = Start-Process powershell -Verb RunAs -WindowStyle Hidden "
        "-Wait -PassThru -ErrorAction Stop -ArgumentList "
        "'-NoProfile -NonInteractive -EncodedCommand " + inner + "'; "
        "exit $p.ExitCode } catch { exit " + str(CANCELLED) + " }"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-EncodedCommand", _encoded(outer)],
            capture_output=True, timeout=timeout, creationflags=_NO_WINDOW,
        )
        return proc.returncode
    except subprocess.TimeoutExpired:
        print("[AudioEngine] Restart timed out waiting for the UAC prompt.")
        return CANCELLED
    except Exception as e:
        print(f"[AudioEngine] Restart failed to launch: {e}")
        return 1
