<#
Switches an installed BrightLink Echo to the version laid out in
pending-<Version>\, all or nothing.

Ships INSIDE each version (app-<Version>\activate.ps1), so the new version
installs itself. Until v1.7.x the OLD version's swap script installed the new
one, which is how v1.6.79 came to run on another build's files.

Run by the installer (-Mode Install) and by the app's updater (-Mode Update),
always from a copy outside pending-<Version>, because the folder is moved.

  1. wait for -WaitPid, stop our processes that run from either data folder
  M. migrate (v1.8.5): when the legacy folders exist (%LOCALAPPDATA% and
     %APPDATA%\<LegacyDirName>), move them to the current names, the whole
     folder in one rename where it can, and rename the legacy exe to the
     current one. Every move is recorded; any later failure moves everything
     back, so the previous version runs exactly where it did before
  2. repair: a canonical exe missing beside a .previous is put back
  3. check pending-<Version> against its manifest (every file, the exe's hash);
     anything wrong installs NOTHING
  4. move app-<Version> into place (one rename; the running version's folder
     is never touched)
  5. swap the exe with File.Replace, keeping <exe>.previous, re-hash,
     restore on mismatch
  6. Install: register with Windows (the new exe's own --install /S)
  7. Relaunch: start it and watch; if it EXITS without writing health.json
     the previous exe (and its still-present folder) is put back

Exit codes: 0 done, 2 pending incomplete (nothing changed), 3 exe swap failed
(previous restored), 4 registration failed (rolled back), 5 new version died
at start (rolled back), 6 the legacy folders could not be moved (nothing
changed; the caller tries again on its next update check).

Names here are brand.py's on-disk values (tests/test_activation.py pins them).
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
    [string]$LaunchWith = '',
    # Tests only: never touch this user's real logon task, registry or links.
    [switch]$NoSystemChanges
)

$ErrorActionPreference = 'Stop'
$Version = $Version.TrimStart('v', 'V')
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$ExeName = 'BrightLink Echo.exe'
$DirName = 'BrightLink Echo'
$LegacyExeName = 'FTC Whisper.exe'
$LegacyDirName = 'FTC Whisper'
$MarkerName = 'migrated.json'
# What a new version registers under the current names, removed again if a
# migration is rolled back (the previous version re-registers its own).
$TaskName = 'BrightLink Echo'
$RunValueName = 'BrightLink Echo'
$UninstallKeyName = 'BrightLinkEcho'
$UrlScheme = 'brightlinkecho'
$LegacyTaskName = 'FTC Whisper'
$LegacyRunValueName = 'FTC Whisper'
# Start with Windows: the Run entry Task Manager lists, and its on/off record.
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$ApprovedKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'

# A folder that is any process's current directory cannot be renamed, and the
# updater that starts this script may have been started inside the legacy one.
try { [System.IO.Directory]::SetCurrentDirectory([System.IO.Path]::GetTempPath()); Set-Location -LiteralPath ([System.IO.Path]::GetTempPath()) } catch {}

$Leaf = [System.IO.Path]::GetFileName($InstallDir)
$LocalBase = [System.IO.Path]::GetDirectoryName($InstallDir)
# Only a real data folder migrates. Anything else (a test folder, a dev path)
# is activated exactly as it is.
$Migrating = ($Leaf -ieq $LegacyDirName) -or ($Leaf -ieq $DirName)
$NewDir = if ($Migrating) { Join-Path $LocalBase $DirName } else { $InstallDir }
$LegacyDir = Join-Path $LocalBase $LegacyDirName
$RoamBase = $env:APPDATA
$NewRoam = if ($RoamBase) { Join-Path $RoamBase $DirName } else { '' }
$LegacyRoam = if ($RoamBase) { Join-Path $RoamBase $LegacyDirName } else { '' }
$script:Moves = New-Object System.Collections.ArrayList
# True only when the previous version ran from the legacy folder and this run
# moved it. Only then does a rollback send the machine back there; a failed
# update on a machine already moved never goes near the legacy folder.
$script:PrevHomeLegacy = $false
$script:ForceLaunch = $false

function Set-Paths([string]$dir) {
    $script:InstallDir = $dir
    $script:Canonical = Join-Path $dir $ExeName
    $script:Backup = "$($script:Canonical).previous"
    $script:Contents = "app-$Version"
    $script:Pending = Join-Path $dir "pending-$Version"
    $script:PendingExe = Join-Path $script:Pending $ExeName
    $script:PendingContents = Join-Path $script:Pending $script:Contents
    $script:Target = Join-Path $dir $script:Contents
    $script:Log = Join-Path $dir 'update.log'
    $script:Health = Join-Path $dir 'health.json'
    $script:Bad = Join-Path $dir 'bad-version.txt'
}
Set-Paths $InstallDir
# The copy of this script the caller runs, as it is named after any move.
$ScriptLeaf = if ($PSCommandPath) { [System.IO.Path]::GetFileName($PSCommandPath) } else { '' }

function Log([string]$msg) {
    # Into whichever data folder exists: the paths switch to the new folder
    # before a failed move is known, and a log written there was lost (CI
    # 2026-10-08: the reason for a refused migration was nowhere).
    $path = $script:Log
    try {
        if (-not (Test-Path -LiteralPath ([System.IO.Path]::GetDirectoryName($path)))) {
            foreach ($d in @($LegacyDir, $NewDir)) {
                if ($d -and (Test-Path -LiteralPath $d -PathType Container)) { $path = Join-Path $d 'update.log'; break }
            }
        }
        "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [activate $Version] $msg" | Add-Content -LiteralPath $path -Encoding UTF8
    } catch {}
}
# SHA-256 through .NET, never Get-FileHash: in Windows PowerShell 5.1 that is a
# script function of a module, and a powershell.exe started from PowerShell 7
# (a CI step, or a user's pwsh terminal running the installer) inherits pwsh's
# PSModulePath and cannot load it ("Get-FileHash is not recognized"). Found in
# CI run 36682309186, where it refused every install.
function Sha256Of([string]$p) {
    $s = [System.IO.File]::Open($p, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $h = [System.Security.Cryptography.SHA256]::Create()
        try { return ([System.BitConverter]::ToString($h.ComputeHash($s)) -replace '-', '').ToLower() }
        finally { $h.Dispose() }
    } finally { $s.Dispose() }
}
function HashOf([string]$p) {
    try { Sha256Of $p } catch { '' }
}
function Test-ExeHash([string]$p, [string]$want) {
    # A freshly written exe is often held by an antivirus scan for a few
    # seconds, and a read in that window fails. Retry before calling it wrong,
    # and log what was actually seen when it stays wrong.
    $why = ''
    for ($i = 0; $i -lt [Math]::Min($Attempts, 15); $i++) {
        try {
            $got = Sha256Of $p
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
    if ($ScriptLeaf -like 'activate-*.ps1') {
        # Wherever the folder it came in now is.
        foreach ($d in @($script:InstallDir, $NewDir, $LegacyDir)) {
            Remove-Item -LiteralPath (Join-Path $d $ScriptLeaf) -Force -ErrorAction SilentlyContinue
        }
    }
    exit $code
}
function Start-Echo([string[]]$argv) {
    $cmd = $script:Canonical
    $all = @()
    if ($LaunchWith) { $cmd = $LaunchWith; $all += "`"$($script:Canonical)`"" }
    $all += $argv
    if ($all.Count -gt 0) {
        $p = Start-Process -FilePath $cmd -ArgumentList $all -WorkingDirectory $script:InstallDir -PassThru
    } else {
        $p = Start-Process -FilePath $cmd -WorkingDirectory $script:InstallDir -PassThru
    }
    # Windows PowerShell only keeps ExitCode for a process whose handle was
    # opened while it ran.
    $null = $p.Handle
    return $p
}
function Stop-Ours {
    # Only what runs from our data folders (the canonical exe, a pending or
    # previous copy). Copies elsewhere (an old Downloads exe holding the
    # single-instance mutex) only when the installer asks: those are found by
    # the exe's own OriginalFilename, never by leaf name alone.
    $roots = @($script:InstallDir + '\')
    if ($Migrating) { $roots += @($NewDir + '\', $LegacyDir + '\') }
    foreach ($proc in @(Get-Process -ErrorAction SilentlyContinue)) {
        if ($proc.Id -eq $PID) { continue }
        $p = $null
        try { $p = $proc.Path } catch {}
        if (-not $p) { continue }
        $ours = $false
        if ($p.EndsWith('.exe', [System.StringComparison]::OrdinalIgnoreCase)) {
            foreach ($r in $roots) {
                if ($p.StartsWith($r, [System.StringComparison]::OrdinalIgnoreCase)) { $ours = $true }
            }
        }
        if (-not $ours -and $KillCopiesElsewhere) {
            try {
                $orig = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($p).OriginalFilename
                $ours = ($orig -eq $ExeName) -or ($orig -eq $LegacyExeName)
            } catch {}
        }
        if ($ours) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Log "Stopped $($proc.Id) $p"
        }
    }
}
function Move-Retry([string]$from, [string]$to, [int]$tries = $Attempts) {
    for ($i = 0; $i -lt $tries; $i++) {
        try {
            # An undo puts items back into a legacy folder Adopt-Folder may
            # have removed once it was empty.
            $parent = [System.IO.Path]::GetDirectoryName($to)
            if ($parent -and -not (Test-Path -LiteralPath $parent)) { [void][System.IO.Directory]::CreateDirectory($parent) }
            if (Test-Path -LiteralPath $from -PathType Container) { [System.IO.Directory]::Move($from, $to) }
            else { [System.IO.File]::Move($from, $to) }
            return $true
        } catch {
            # A move that happened but still threw (an AV filter, a network
            # redirector) counts as done.
            if (-not (Test-Path -LiteralPath $from) -and (Test-Path -LiteralPath $to)) { return $true }
            if ($i -eq 0 -or $i -eq ($tries - 1)) { Log "Move $from -> $to failed (attempt $($i + 1)): $($_.Exception.Message)" }
            Start-Sleep -Seconds 1
        }
    }
    return $false
}
function Record-Move([string]$from, [string]$to) {
    if (Move-Retry $from $to) { [void]$script:Moves.Add(@($from, $to)); return $true }
    return $false
}
function Adopt-Folder([string]$legacy, [string]$new) {
    # Everything in $legacy ends up in $new: one rename of the whole folder
    # when $new is not there yet, otherwise each item $new does not already
    # have. What $new has wins (it is only ever this run's own staging).
    if (-not $legacy -or -not (Test-Path -LiteralPath $legacy -PathType Container)) { return $true }
    if (-not (Test-Path -LiteralPath $new)) {
        if (-not (Record-Move $legacy $new)) { return $false }
        Log "Moved $legacy to $new."
        return $true
    }
    foreach ($item in @(Get-ChildItem -LiteralPath $legacy -Force)) {
        $dest = Join-Path $new $item.Name
        if (Test-Path -LiteralPath $dest) { Log "Kept $dest (left the older $($item.FullName))."; continue }
        if (-not (Record-Move $item.FullName $dest)) { return $false }
    }
    Log "Moved the contents of $legacy into $new."
    # The emptied legacy folder goes too, or %APPDATA%\FTC Whisper stays on
    # every machine whose new folder existed first. A folder still holding
    # something we kept is left alone.
    if (@(Get-ChildItem -LiteralPath $legacy -Force -ErrorAction SilentlyContinue).Count -eq 0) {
        try { [System.IO.Directory]::Delete($legacy); Log "Removed the empty $legacy." }
        catch { Log "Could not remove the empty ${legacy}: $($_.Exception.Message)" }
    }
    return $true
}
function Write-Marker {
    # This folder is the machine's data folder from now on (data_paths.py).
    try {
        [System.IO.File]::WriteAllText((Join-Path $NewDir $MarkerName),
            "{`"from`": `"$($LegacyDir -replace '\\', '\\')`", `"version`": `"$Version`"}")
    } catch { Log "Could not write ${MarkerName}: $_" }
}
function Undo-Adopt {
    # Every recorded move, newest first. When the previous version ran from
    # the legacy folder, that leaves it exactly as it knew the machine. If one
    # move cannot be put back, the ones already put back are redone instead,
    # so the machine is never split between the two folders. $true = back.
    if ($script:Moves.Count -eq 0) {
        if ($script:PrevHomeLegacy) {
            # The very first move failed: nothing left the legacy folder, so
            # the previous version is exactly where it was. Returning $false
            # here kept the paths on the new folder, which does not exist, and
            # the previous version was never started again (CI 2026-10-08).
            Remove-Item -LiteralPath (Join-Path $NewDir $MarkerName) -Force -ErrorAction SilentlyContinue
            $script:PrevHomeLegacy = $false
            Set-Paths $LegacyDir
            Log 'Nothing was moved: the previous version keeps its folders.'
        }
        return $true
    }
    if ($script:PrevHomeLegacy) {
        Remove-Item -LiteralPath (Join-Path $NewDir $MarkerName) -Force -ErrorAction SilentlyContinue
    }
    $undone = New-Object System.Collections.ArrayList
    for ($i = $script:Moves.Count - 1; $i -ge 0; $i--) {
        $m = $script:Moves[$i]
        if (Move-Retry $m[1] $m[0] ([Math]::Max($Attempts * 4, 60))) { [void]$undone.Add($m); continue }
        Log "COULD NOT put back $($m[0]) (still at $($m[1])): keeping the move instead."
        for ($j = $undone.Count - 1; $j -ge 0; $j--) {
            $u = $undone[$j]
            if (-not (Move-Retry $u[0] $u[1])) { Log "COULD NOT redo $($u[0]) -> $($u[1])." }
        }
        if ($script:PrevHomeLegacy) { Write-Marker }
        Set-Paths $NewDir
        return $false
    }
    $script:Moves.Clear()
    if ($script:PrevHomeLegacy) {
        $script:PrevHomeLegacy = $false
        Set-Paths $LegacyDir
        Remove-NewRegistrations
        $old = Join-Path $LegacyDir $LegacyExeName
        if (Test-Path -LiteralPath $old) { Retarget-Links (Join-Path $NewDir $ExeName) $old }
        Log 'Migration rolled back: the previous version keeps its folders.'
    }
    return $true
}
function Remove-NewRegistrations {
    # What the new version may have registered before it failed. The previous
    # version re-registers its own (legacy-named) entries when it starts.
    if ($NoSystemChanges) { return }
    try { & schtasks.exe /delete /tn $TaskName /f 2>$null | Out-Null } catch {}
    foreach ($k in @("HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$UninstallKeyName",
                     "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\$ExeName",
                     "HKCU:\Software\Classes\$UrlScheme")) {
        Remove-Item -LiteralPath $k -Recurse -Force -ErrorAction SilentlyContinue
    }
    foreach ($k in @($RunKey, $ApprovedKey)) {
        Remove-ItemProperty -LiteralPath $k -Name $RunValueName -Force -ErrorAction SilentlyContinue
    }
}
function Retarget-Links([string]$from, [string]$to) {
    # Shortcuts and taskbar/Start pins aimed at $from now open $to.
    if ($NoSystemChanges) { return }
    try {
        $sh = New-Object -ComObject WScript.Shell
        $pinned = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned'
        $dirs = @($sh.SpecialFolders('Desktop'), $sh.SpecialFolders('Programs'),
                  (Join-Path $pinned 'TaskBar'), (Join-Path $pinned 'StartMenu'))
        foreach ($d in $dirs) {
            if (-not $d -or -not (Test-Path -LiteralPath $d)) { continue }
            foreach ($f in @(Get-ChildItem -LiteralPath $d -Filter *.lnk -ErrorAction SilentlyContinue)) {
                try {
                    $l = $sh.CreateShortcut($f.FullName)
                    if ($l.TargetPath -ieq $from) {
                        $l.TargetPath = $to
                        $l.WorkingDirectory = [System.IO.Path]::GetDirectoryName($to)
                        $l.Save()
                        Log "Retargeted $($f.FullName)."
                    }
                } catch {}
            }
        }
    } catch { Log "Shortcut check skipped: $_" }
}
function Restore-Previous([string]$why) {
    if (-not (Test-Path -LiteralPath $script:Backup)) { Log "Nothing to restore ($why)."; return $false }
    for ($i = 0; $i -lt 10; $i++) {
        try {
            if (Test-Path -LiteralPath $script:Canonical) {
                [System.IO.File]::Replace($script:Backup, $script:Canonical, "$($script:Canonical).failed")
                Remove-Item -LiteralPath "$($script:Canonical).failed" -Force -ErrorAction SilentlyContinue
            } else {
                [System.IO.File]::Move($script:Backup, $script:Canonical)
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
    if (($Relaunch -or $script:ForceLaunch) -and (Test-Path -LiteralPath $script:Canonical)) {
        try { [void](Start-Echo @()); Log "Relaunched the installed version." } catch { Log "Relaunch failed: $_" }
    }
}
function Give-Back {
    # Every failure exit: undo a migration first, then start what was there.
    # A migration's previous version was stopped by this run (or by the
    # installer), so it is started again even without -Relaunch.
    $wasLegacy = $script:PrevHomeLegacy
    if ((Undo-Adopt) -and $wasLegacy) {
        $script:Canonical = Join-Path $LegacyDir $LegacyExeName
        $script:ForceLaunch = $true
    }
    Launch-Current
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

# M. The legacy folders become the current ones, before anything else looks
#    for files: from here on the whole activation runs in the new folder.
if ($Migrating) {
    # Already moved (marked, or holding the current exe): the new folder is
    # home, and a legacy folder that has come back (a stray old exe unpacking
    # into it, a leftover a locked file kept) is never adopted or returned to.
    $newIsHome = (Test-Path -LiteralPath (Join-Path $NewDir $MarkerName)) -or
                 (Test-Path -LiteralPath (Join-Path $NewDir $ExeName))
    $hasLegacy = Test-Path -LiteralPath $LegacyDir -PathType Container
    $hasLegacyRoam = $LegacyRoam -and (Test-Path -LiteralPath $LegacyRoam -PathType Container)
    $ok = $true
    if ($newIsHome) {
        if ($Leaf -ieq $LegacyDirName) {
            # A legacy-named copy staged this update in the legacy folder:
            # bring only what it staged home.
            $dest = Join-Path $NewDir "pending-$Version"
            Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
            $ok = Move-Retry (Join-Path $LegacyDir "pending-$Version") $dest
        }
        Set-Paths $NewDir
        # A roaming profile can arrive with only the legacy roaming folder.
        if ($ok -and $hasLegacyRoam -and -not (Test-Path -LiteralPath $NewRoam)) {
            $ok = Adopt-Folder $LegacyRoam $NewRoam
        }
    } elseif ($hasLegacy -or $hasLegacyRoam) {
        $script:PrevHomeLegacy = $hasLegacy
        $ok = Adopt-Folder $LegacyDir $NewDir
        if ($ok) { $ok = Adopt-Folder $LegacyRoam $NewRoam }
        Set-Paths $NewDir
        if ($ok) {
            # The previous version's exe takes the current name, so the swap
            # below keeps it as the .previous it can roll back to.
            $oldExe = Join-Path $NewDir $LegacyExeName
            if ((Test-Path -LiteralPath $oldExe) -and -not (Test-Path -LiteralPath $script:Canonical)) {
                $ok = Record-Move $oldExe $script:Canonical
            }
        }
        if ($ok -and $script:PrevHomeLegacy) { Write-Marker; Log "Migrated $LegacyDirName to $DirName." }
    }
    if (-not $ok) {
        Log 'NOT installing: the legacy folders could not be moved (a file is in use).'
        Give-Back
        Finish 6
    }
}

# 2. A kill between File.Replace's two renames leaves only the backup.
if (-not (Test-Path -LiteralPath $script:Canonical) -and (Test-Path -LiteralPath $script:Backup)) {
    try { [System.IO.File]::Move($script:Backup, $script:Canonical); Log 'Repaired: canonical exe was missing, restored .previous.' } catch { Log "Repair failed: $_" }
}

# 3. What is about to be switched in must be exactly what CI built.
$source = if (Test-Path -LiteralPath $script:PendingContents) { $script:PendingContents } else { $script:Target }
$manifestPath = Join-Path $source 'manifest.json'
$manifest = $null
try { $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
if (-not $manifest -or $manifest.version -ne $Version) {
    Log "NOT installing: no manifest for $Version at $manifestPath."
    Give-Back
    Finish 2
}
$wantExe = ([string]$manifest.exe.sha256).ToLower()
$already = ((HashOf $script:Canonical) -eq $wantExe) -and (Test-Path -LiteralPath $script:Target) -and -not (Test-Path -LiteralPath $script:PendingContents)
if ($already) {
    Log 'This version is already in place (an earlier run finished the switch).'
} else {
    $problems = @()
    $base = if ($source -eq $script:PendingContents) { $script:Pending } else { $script:InstallDir }
    foreach ($f in $manifest.files) {
        $full = Join-Path $base (([string]$f.path) -replace '/', '\')
        $item = Get-Item -LiteralPath $full -ErrorAction SilentlyContinue
        if (-not $item) { $problems += "missing $($f.path)" }
        elseif ($item.Length -ne [int64]$f.size) { $problems += "size $($f.path)" }
        if ($problems.Count -ge 5) { break }
    }
    if (-not (Test-ExeHash $script:PendingExe $wantExe)) { $problems += "exe hash $($script:PendingExe)" }
    if ($problems.Count -gt 0) {
        Log "NOT installing: pending-$Version is incomplete: $($problems -join '; ')"
        Give-Back
        Finish 2
    }

    # 4. Move the new folder in. Never the running version's: its name differs.
    if ($source -eq $script:PendingContents) {
        $moved = $false
        for ($i = 0; $i -lt [Math]::Min($Attempts, 15) -and -not $moved; $i++) {
            try {
                if (Test-Path -LiteralPath $script:Target) { Remove-Item -LiteralPath $script:Target -Recurse -Force }
                [System.IO.Directory]::Move($script:PendingContents, $script:Target)
                $moved = $true
            } catch {
                Log "Folder move attempt $($i + 1) failed: $_"
                Start-Sleep -Seconds 2
            }
        }
        if (-not $moved) { Log 'NOT installing: could not move the new folder into place.'; Give-Back; Finish 3 }
        # Undoing a migration must not strand the new folder in the new place.
        if ($script:PrevHomeLegacy) { [void]$script:Moves.Add(@($script:PendingContents, $script:Target)) }
        Log "Moved $($script:Contents) into place."
    }

    # 5. One exe swap, the same primitive the onefile updater proved.
    $swapped = $false
    for ($i = 0; $i -lt $Attempts -and -not $swapped; $i++) {
        try {
            if (Test-Path -LiteralPath $script:Canonical) {
                Remove-Item -LiteralPath $script:Backup -Force -ErrorAction SilentlyContinue
                [System.IO.File]::Replace($script:PendingExe, $script:Canonical, $script:Backup)
            } else {
                [System.IO.File]::Move($script:PendingExe, $script:Canonical)
            }
            if (-not (Test-ExeHash $script:Canonical $wantExe)) { throw 'installed exe does not match the manifest' }
            $swapped = $true
        } catch {
            Log "Exe swap attempt $($i + 1) failed: $_"
            if ((Test-Path -LiteralPath $script:Backup) -and ((HashOf $script:Canonical) -ne $wantExe)) { [void](Restore-Previous 'swap failed') }
            Stop-Ours
            Start-Sleep -Seconds 2
        }
    }
    if (-not $swapped) { Log 'NOT installed: exe swap failed; previous version kept.'; Give-Back; Finish 3 }
    # Older onefile copies (before v1.6.15) copy themselves over a canonical exe
    # whose mtime is older than theirs. Now is newer than any of them.
    try { (Get-Item -LiteralPath $script:Canonical).LastWriteTime = Get-Date } catch {}
    Log "Switched to $Version."
}
if ($Migrating -and ($script:InstallDir -ieq $NewDir)) { Write-Marker }
if ($script:PrevHomeLegacy -and -not $NoSystemChanges) {
    # Until the new version registers itself, every launcher still names the
    # legacy exe. If the machine sleeps or shuts down before then, the next
    # sign-in must still start the app and every pin must still open it.
    Retarget-Links (Join-Path $LegacyDir $LegacyExeName) $script:Canonical
    # In Windows PowerShell 5.1 with ErrorActionPreference Stop, a native
    # command's stderr line is a terminating error even when redirected: a
    # machine with no legacy task ("cannot find the file") ended the whole
    # activation here with exit 1 (CI self-test, 2026-10-07).
    $legacyTask = $false
    try {
        & schtasks.exe /query /tn $LegacyTaskName 2>$null | Out-Null
        $legacyTask = ($LASTEXITCODE -eq 0)
    } catch { $legacyTask = $false }
    $legacyRun = $null -ne (Get-ItemProperty -LiteralPath $RunKey -Name $LegacyRunValueName -ErrorAction SilentlyContinue)
    if ($legacyTask -or $legacyRun) {
        try {
            New-ItemProperty -LiteralPath $RunKey -Name $RunValueName `
                -Value "`"$($script:Canonical)`" --startup" -PropertyType String -Force | Out-Null
            # Task Manager's on/off record moves with it: a person who switched
            # the legacy entry off there keeps it off (the new exe reads it).
            $approved = (Get-ItemProperty -LiteralPath $ApprovedKey -Name $LegacyRunValueName -ErrorAction SilentlyContinue).$LegacyRunValueName
            if ($null -ne $approved) {
                if (-not (Test-Path -LiteralPath $ApprovedKey)) { New-Item -Path $ApprovedKey -Force | Out-Null }
                New-ItemProperty -LiteralPath $ApprovedKey -Name $RunValueName `
                    -Value ([byte[]]$approved) -PropertyType Binary -Force | Out-Null
            }
            Log 'Start at sign-in bridged to the new exe until it registers itself.'
        } catch { Log "Could not bridge start at sign-in: $_" }
    }
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
        # A failed restore leaves the new exe in place: moving its folders back
        # would strand it without its app folder, so the migration stands.
        if (Restore-Previous 'registration failed') { Give-Back }
        Finish 4
    }
    Log 'Registered with Windows.'
}

# 7. Start it, and give the old version back if the new one dies at start.
if ($Relaunch) {
    Remove-Item -LiteralPath $script:Health -Force -ErrorAction SilentlyContinue
    $proc = $null
    try { $proc = Start-Echo @() } catch { Log "Launch failed: $_" }
    $healthy = $false
    $deadline = (Get-Date).AddSeconds($HealthTimeout)
    while ((Get-Date) -lt $deadline) {
        try {
            $h = Get-Content -LiteralPath $script:Health -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
            if ($h.version -eq $Version) { $healthy = $true; break }
        } catch {}
        if ($proc -and $proc.HasExited) {
            Start-Sleep -Seconds 2
            try {
                $h = Get-Content -LiteralPath $script:Health -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
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
            $wasLegacy = $script:PrevHomeLegacy
            # Wherever the previous version ends up running, it finds the mark.
            if ((Undo-Adopt) -and $wasLegacy) { $script:Canonical = Join-Path $LegacyDir $LegacyExeName }
            try { [System.IO.File]::WriteAllText($script:Bad, $Version) } catch {}
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

# 6b. A migration hands Windows' registrations (Installed apps entry, logon
#     task, App Paths) from the legacy names to the current ones. The new
#     version also does this as it starts, on a background thread that CI saw
#     stall before its first step (2026-10-08, 1 run in 4), leaving the legacy
#     Installed apps entry and logon task behind. Here it runs to the end in
#     its own process before the update is done, as Install mode's does. A
#     failure only logs: the app retries at its next start, and a working
#     update is never undone for it.
if ($script:PrevHomeLegacy -and -not $NoSystemChanges) {
    $code = -1
    try {
        $p = Start-Echo @('--install', '/S')
        if ($p.WaitForExit(180000)) { $code = $p.ExitCode } else { try { $p.Kill() } catch {} }
    } catch { Log "Registration could not start: $_" }
    if ($code -eq 0) { Log 'Registered with Windows under the current names.' }
    else { Log "Registration did not finish (exit $code); the app retries at its next start." }
}

Remove-Item -LiteralPath $script:Backup -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $script:Pending -Recurse -Force -ErrorAction SilentlyContinue
if ($Migrating -and ($script:InstallDir -ieq $NewDir)) {
    # The new folder is home: what only a legacy-named version needed goes.
    foreach ($leftover in @((Join-Path $NewDir $LegacyExeName), (Join-Path $NewDir "$LegacyExeName.previous"))) {
        Remove-Item -LiteralPath $leftover -Force -ErrorAction SilentlyContinue
    }
    # A merge can leave the older copy of a file the new folder already had.
    # Local leftovers are disposable; roaming ones (history, recordings) are
    # never deleted here.
    if (Test-Path -LiteralPath $LegacyDir) {
        Remove-Item -LiteralPath $LegacyDir -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $LegacyDir) { Log "Some of $LegacyDir is still in use; the app removes it later." }
    }
}
Finish 0
