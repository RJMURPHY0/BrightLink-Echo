; BrightLink Echo installer (Inno Setup 6.7.3, pinned in CI).
;
; Built by tools/build_installer.py, which passes every name from brand.py and
; the version from app.py as /D defines: nothing product-specific is typed here.
;
; What it does, and deliberately does not do:
;   * per-user, no admin, no UAC prompt: %LOCALAPPDATA%\FTC Whisper
;   * lays the new version out in pending-<version>\ ONLY. It never writes into
;     the running version's files, so it can run while the app is open (the
;     updater stages with /STAGEONLY and switches when the user is idle)
;   * then runs that version's own activate.ps1, which checks every file
;     against the manifest, moves the folder in, swaps the one exe with a
;     backup, and registers with Windows through the app's own --install /S
;   * no uninstaller and no Installed apps entry of its own
;     (Uninstallable=no): the app's own entry, "FTCWhisper", is the only one,
;     and its "<exe> --uninstall" removes everything
;   * no AppMutex: staging must be allowed while the app runs
;   * the speech model is NOT in here: the app downloads it once, with its own
;     retry, resume and per-file SHA-256 check
;
; Exit codes: Inno's own (0 success, 1-8), plus 10 when the files installed
; but activation failed (the previous version is left running).

#ifndef AppVersion
  #error Build with tools/build_installer.py: AppVersion is not defined
#endif

[Setup]
AppId={{6E0C51D2-8A4B-4F0E-9C37-2B1D5E8F7A63}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppCopyright={#Copyright}
VersionInfoVersion={#FileVersion}
VersionInfoCompany={#Publisher}
VersionInfoDescription={#AppName} installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoCopyright={#Copyright}
; Never the app's own OriginalFilename: activate.ps1 stops copies of the APP
; found by that name, and must never stop the installer running it.
VersionInfoOriginalFileName={#OutputBase}.exe
DefaultDirName={localappdata}\{#DataDir}
DisableDirPage=yes
UsePreviousAppDir=no
DirExistsWarning=no
DisableProgramGroupPage=yes
DisableWelcomePage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Uninstallable=no
CreateUninstallRegKey=no
CloseApplications=no
RestartApplications=no
SetupMutex=FTCWhisperSetup
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
SetupIconFile={#IconFile}
WizardStyle=modern dark hidebevels
WizardImageFile={#WizardImage}
WizardSmallImageFile={#WizardSmallImage}
Compression=lzma2/max
SolidCompression=yes
SetupLogging=yes
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
SelectTasksLabel2=Choose how {#AppName} starts, then click Install.
FinishedHeadingLabel={#AppName} is ready
FinishedLabelNoIcons=Hold Alt+V in any app and speak: your words appear where you are typing.%n%nThe first launch downloads the speech model (about 660 MB) once.
FinishedLabel=Hold Alt+V in any app and speak: your words appear where you are typing.%n%nThe first launch downloads the speech model (about 660 MB) once.

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"
; Store policy 10.2.8: starting at sign-in needs the user's consent. This tick
; is it, and it is written to the app's start_with_windows setting.
Name: "startup"; Description: "&Start {#AppName} when I sign in to Windows"

[InstallDelete]
; A half-written pending folder from an interrupted run is never reused.
Type: filesandordirs; Name: "{app}\{#PendingPrefix}*"

[Files]
Source: "{#SourceDir}\{#ExeName}"; DestDir: "{app}\{#PendingDir}"; Flags: ignoreversion
Source: "{#SourceDir}\{#ContentsDir}\*"; DestDir: "{app}\{#PendingDir}\{#ContentsDir}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Run]
Filename: "{app}\{#ExeName}"; Description: "Open {#AppName} now"; Flags: postinstall nowait skipifsilent; Check: Activated

[Code]
var
  ActivationDone: Boolean;
  ActivationCode: Integer;

function IsStageOnly: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/STAGEONLY') = 0 then
      Result := True;
end;

function Activated: Boolean;
begin
  Result := ActivationDone and (ActivationCode = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Script, Params: String;
begin
  if (CurStep <> ssPostInstall) or IsStageOnly then
    Exit;
  // Run a copy: activate.ps1 moves the folder it ships in.
  Script := ExpandConstant('{app}\activate-{#AppVersion}.ps1');
  if not FileCopy(ExpandConstant('{app}\{#PendingDir}\{#ContentsDir}\activate.ps1'), Script, False) then
  begin
    ActivationDone := True;
    ActivationCode := -2;
    Log('Could not copy activate.ps1');
  end
  else
  begin
    Params := '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + Script +
              '" -InstallDir "' + ExpandConstant('{app}') + '" -Version {#AppVersion}' +
              ' -Mode Install -KillCopiesElsewhere';
    if not WizardIsTaskSelected('desktopicon') then
      Params := Params + ' -NoDesktopShortcut';
    if WizardIsTaskSelected('startup') then
      Params := Params + ' -StartWithWindows 1'
    else
      Params := Params + ' -StartWithWindows 0';
    WizardForm.StatusLabel.Caption := 'Finishing installation...';
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params,
                ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ActivationCode) then
      ActivationCode := -1;
    ActivationDone := True;
    Log(Format('activate.ps1 exited with %d', [ActivationCode]));
  end;
  if (ActivationCode <> 0) and not WizardSilent then
    MsgBox(Format('{#AppName} could not finish installing (code %d).'#13#10#13#10 +
                  'Nothing you had installed was changed. Details are in' + #13#10 +
                  '%s', [ActivationCode, ExpandConstant('{app}\update.log')]),
           mbError, MB_OK);
end;

function GetCustomSetupExitCode: Integer;
begin
  if ActivationDone and (ActivationCode <> 0) then
    Result := 10
  else
    Result := 0;
end;
