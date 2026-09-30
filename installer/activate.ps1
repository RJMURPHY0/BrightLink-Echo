<#
Switches an installed BrightLink Echo (%LOCALAPPDATA%\FTC Whisper) to the version
laid out in pending-<Version>\, all or nothing.

Ships INSIDE each version (app-<Version>\activate.ps1), so the new version
installs itself. Until v1.7.x the OLD version's swap script installed the new
one, which is how v1.6.79 came to run on another build's files.

Run by the installer (-Mode Install) and by the app's updater (-Mode Update),
always from a copy outside pending-<Version>, because the folder is moved.

  1. wait for -WaitPid, stop our processes that run from the install folder
  2. repair: a canonical exe missing beside a .previous is put back
  3. check pending-<Version> against its manifest (every file, the exe's hash);
     anything wrong installs NOTHING
  4. move app-<Version> into place (one rename; the running version's folder
     is never touched)
  5. swap the exe with File.Replace, keeping FTC Whisper.exe.previous, re-hash,
     restore on mismatch
  6. Install: register with Windows (the new exe's own --install /S)
  7. Relaunch: start it and watch; if it EXITS without writing health.json
     the previous exe (and its still-present folder) is put back

Exit codes: 0 done, 2 pending incomplete (nothing changed), 3 exe swap failed
(previous restored), 4 registration failed (rolled back), 5 new version died
at start (rolled back).

Names here are brand.py's FROZEN values (tests/test_activation.py pins them).
#>
param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [Parameter(Mandatory = $true)][string]$Version,
    [ValidateSet('Install', 'Update')][string]$Mode = 'Update',
    [int]$WaitPid = 0,
    [switch]$Relaunch,
    [switch]$NoDesktopShortcut,
    [int]$StartWithWindows = -1,
    [switch]$KillCopiesElsewhere,
    [int]$HealthTimeout = 180,
    [int]$Attempts = 30,
    [string]$LaunchWith = ''
)

$ErrorActionPreference = 'Stop'
$Version = $Version.TrimStart('v', 'V')
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$ExeName = 'FTC Whisper.exe'
$Canonical = Join-Path $InstallDir $ExeName
$Backup = "$Canonical.previous"
$Contents = "app-$Version"
$Pending = Join-Path $InstallDir "pending-$Version"
$PendingExe = Join-Path $Pending $ExeName
$PendingContents = Join-Path $Pending $Contents
$Target = Join-Path $InstallDir $Contents
$Log = Join-Path $InstallDir 'update.log'
$Health = Join-Path $InstallDir 'health.json'
$Bad = Join-Path $InstallDir 'bad-version.txt'

function Log([string]$msg) {
    try { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [activate $Version] $msg" | Add-Content -LiteralPath $Log -Encoding UTF8 } catch {}
}
function HashOf([string]$p) {
    try { (Get-FileHash -LiteralPath $p -Algorithm SHA256 -ErrorAction Stop).Hash.ToLower() } catch { '' }
}
function Test-ExeHash([string]$p, [string]$want) {
    # A freshly written exe is often held by an antivirus scan for a few
    # seconds, and a read in that window fails. Retry before calling it wrong,
    # and log what was actually seen when it stays wrong.
    $why = ''
    for ($i = 0; $i -lt [Math]::Min($Attempts, 15); $i++) {
        try {
            $got = (Get-FileHash -LiteralPath $p -Algorithm SHA256 -ErrorAction Stop).Hash.ToLower()
            if ($got -eq $want) {
                if ($i -gt 0) { Log "Exe hash matched on attempt $($i + 1)." }
                return $true
            }
            $len = (Get-Item -LiteralPath $p -ErrorAction SilentlyContinue).Length
            $why = "got $got ($len bytes), want $want"
        } catch {
            $why = "unreadable: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds 1
    }
    Log "Exe hash check failed for ${p}: $why"
    return $false
}
function Finish([int]$code) {
    Log "Exit $code."
    if ($PSCommandPath -and ([System.IO.Path]::GetFileName($PSCommandPath) -like 'activate-*.ps1')) {
        Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
    }
    exit $code
}
function Start-Echo([string[]]$argv) {
    $cmd = $Canonical
    $all = @()
    if ($LaunchWith) { $cmd = $LaunchWith; $all += "`"$Canonical`"" }
    $all += $argv
    if ($all.Count -gt 0) {
        $p = Start-Process -FilePath $cmd -ArgumentList $all -WorkingDirectory $InstallDir -PassThru
    } else {
        $p = Start-Process -FilePath $cmd -WorkingDirectory $InstallDir -PassThru
    }
    # Windows PowerShell only keeps ExitCode for a process whose handle was
    # opened while it ran.
    $null = $p.Handle
    return $p
}
function Stop-Ours {
    # Only what runs from the install folder (the canonical exe, a pending or
    # previous copy). Copies elsewhere (an old Downloads exe holding the
    # single-instance mutex) only when the installer asks: those are found by
    # the exe's own OriginalFilename, never by leaf name alone.
    $root = $InstallDir + '\'
    foreach ($proc in @(Get-Process -ErrorAction SilentlyContinue)) {
        if ($proc.Id -eq $PID) { continue }
        $p = $null
        try { $p = $proc.Path } catch {}
        if (-not $p) { continue }
        $ours = $p.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase) -and
                $p.EndsWith('.exe', [System.StringComparison]::OrdinalIgnoreCase)
        if (-not $ours -and $KillCopiesElsewhere) {
            try { $ours = ([System.Diagnostics.FileVersionInfo]::GetVersionInfo($p).OriginalFilename -eq $ExeName) } catch {}
        }
        if ($ours) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Log "Stopped $($proc.Id) $p"
        }
    }
}
function Restore-Previous([string]$why) {
    if (-not (Test-Path -LiteralPath $Backup)) { Log "Nothing to restore ($why)."; return $false }
    for ($i = 0; $i -lt 10; $i++) {
        try {
            if (Test-Path -LiteralPath $Canonical) {
                [System.IO.File]::Replace($Backup, $Canonical, "$Canonical.failed")
                Remove-Item -LiteralPath "$Canonical.failed" -Force -ErrorAction SilentlyContinue
            } else {
                [System.IO.File]::Move($Backup, $Canonical)
            }
            Log "Restored the previous exe ($why)."
            return $true
        } catch {
            Log "Restore attempt $($i + 1) failed: $_"
            Start-Sleep -Seconds 1
        }
    }
    return $false
}
function Launch-Current {
    if ($Relaunch -and (Test-Path -LiteralPath $Canonical)) {
        try { [void](Start-Echo @()); Log "Relaunched the installed version." } catch { Log "Relaunch failed: $_" }
    }
}

Log "Started. Mode=$Mode WaitPid=$WaitPid Relaunch=$Relaunch Dir=$InstallDir"

# 1. The caller must be gone before anything moves.
if ($WaitPid -gt 0) {
    $deadline = (Get-Date).AddMinutes(10)
    while ((Get-Process -Id $WaitPid -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {
        Start-Sleep -Milliseconds 400
    }
}
Stop-Ours
Start-Sleep -Milliseconds 800

# 2. A kill between File.Replace's two renames leaves only the backup.
if (-not (Test-Path -LiteralPath $Canonical) -and (Test-Path -LiteralPath $Backup)) {
    try { [System.IO.File]::Move($Backup, $Canonical); Log 'Repaired: canonical exe was missing, restored .previous.' } catch { Log "Repair failed: $_" }
}

# 3. What is about to be switched in must be exactly what CI built.
$source = if (Test-Path -LiteralPath $PendingContents) { $PendingContents } else { $Target }
$manifestPath = Join-Path $source 'manifest.json'
$manifest = $null
try { $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
if (-not $manifest -or $manifest.version -ne $Version) {
    Log "NOT installing: no manifest for $Version at $manifestPath."
    Launch-Current
    Finish 2
}
$wantExe = ([string]$manifest.exe.sha256).ToLower()
$already = ((HashOf $Canonical) -eq $wantExe) -and (Test-Path -LiteralPath $Target) -and -not (Test-Path -LiteralPath $PendingContents)
if ($already) {
    Log 'This version is already in place (an earlier run finished the switch).'
} else {
    $problems = @()
    $base = if ($source -eq $PendingContents) { $Pending } else { $InstallDir }
    foreach ($f in $manifest.files) {
        $full = Join-Path $base (([string]$f.path) -replace '/', '\')
        $item = Get-Item -LiteralPath $full -ErrorAction SilentlyContinue
        if (-not $item) { $problems += "missing $($f.path)" }
        elseif ($item.Length -ne [int64]$f.size) { $problems += "size $($f.path)" }
        if ($problems.Count -ge 5) { break }
    }
    if (-not (Test-ExeHash $PendingExe $wantExe)) { $problems += "exe hash $PendingExe" }
    if ($problems.Count -gt 0) {
        Log "NOT installing: pending-$Version is incomplete: $($problems -join '; ')"
        Launch-Current
        Finish 2
    }

    # 4. Move the new folder in. Never the running version's: its name differs.
    if ($source -eq $PendingContents) {
        $moved = $false
        for ($i = 0; $i -lt [Math]::Min($Attempts, 15) -and -not $moved; $i++) {
            try {
                if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
                [System.IO.Directory]::Move($PendingContents, $Target)
                $moved = $true
            } catch {
                Log "Folder move attempt $($i + 1) failed: $_"
                Start-Sleep -Seconds 2
            }
        }
        if (-not $moved) { Log 'NOT installing: could not move the new folder into place.'; Launch-Current; Finish 3 }
        Log "Moved $Contents into place."
    }

    # 5. One exe swap, the same primitive the onefile updater proved.
    $swapped = $false
    for ($i = 0; $i -lt $Attempts -and -not $swapped; $i++) {
        try {
            if (Test-Path -LiteralPath $Canonical) {
                Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue
                [System.IO.File]::Replace($PendingExe, $Canonical, $Backup)
            } else {
                [System.IO.File]::Move($PendingExe, $Canonical)
            }
            if (-not (Test-ExeHash $Canonical $wantExe)) { throw 'installed exe does not match the manifest' }
            $swapped = $true
        } catch {
            Log "Exe swap attempt $($i + 1) failed: $_"
            if ((Test-Path -LiteralPath $Backup) -and ((HashOf $Canonical) -ne $wantExe)) { [void](Restore-Previous 'swap failed') }
            Stop-Ours
            Start-Sleep -Seconds 2
        }
    }
    if (-not $swapped) { Log 'NOT installed: exe swap failed; previous version kept.'; Launch-Current; Finish 3 }
    # Older onefile copies (before v1.6.15) copy themselves over a canonical exe
    # whose mtime is older than theirs. Now is newer than any of them.
    try { (Get-Item -LiteralPath $Canonical).LastWriteTime = Get-Date } catch {}
    Log "Switched to $Version."
}

# 6. Register with Windows, through the new exe's own code.
if ($Mode -eq 'Install') {
    $argv = @('--install', '/S')
    if ($NoDesktopShortcut) { $argv += '--no-desktop-shortcut' }
    if ($StartWithWindows -ge 0) { $argv += "--start-with-windows=$StartWithWindows" }
    $code = -1
    try {
        $p = Start-Echo $argv
        if ($p.WaitForExit(180000)) { $code = $p.ExitCode } else { try { $p.Kill() } catch {} }
    } catch { Log "Registration could not start: $_" }
    if ($code -ne 0) {
        Log "Registration failed (exit $code)."
        if (Restore-Previous 'registration failed') { Launch-Current }
        Finish 4
    }
    Log 'Registered with Windows.'
}

# 7. Start it, and give the old version back if the new one dies at start.
if ($Relaunch) {
    Remove-Item -LiteralPath $Health -Force -ErrorAction SilentlyContinue
    $proc = $null
    try { $proc = Start-Echo @() } catch { Log "Launch failed: $_" }
    $healthy = $false
    $deadline = (Get-Date).AddSeconds($HealthTimeout)
    while ((Get-Date) -lt $deadline) {
        try {
            $h = Get-Content -LiteralPath $Health -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
            if ($h.version -eq $Version) { $healthy = $true; break }
        } catch {}
        if ($proc -and $proc.HasExited) {
            Start-Sleep -Seconds 2
            try {
                $h = Get-Content -LiteralPath $Health -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
                if ($h.version -eq $Version) { $healthy = $true }
            } catch {}
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $healthy -and $proc -and $proc.HasExited) {
        Log "The new version exited at start (code $($proc.ExitCode)) without reporting health: rolling back."
        Stop-Ours
        if (Restore-Previous 'new version died at start') {
            try { [System.IO.File]::WriteAllText($Bad, $Version) } catch {}
            Launch-Current
        }
        Finish 5
    }
    if (-not $healthy) {
        Log "No health report after $HealthTimeout s but the new version is still running: keeping it."
        Finish 0
    }
    Log 'The new version reported healthy.'
}

Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Pending -Recurse -Force -ErrorAction SilentlyContinue
Finish 0
