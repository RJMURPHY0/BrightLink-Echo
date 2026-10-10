; A tiny Setup built around installer/single_instance.isi, so the second-launch
; behaviour is tested for real (tests/test_installer_single_instance.py).
#define AppName "Echo Single Instance Test"
#define AppVersion "0.0.1"
#define SetupMutex "EchoSingleInstanceTestA"
#define LegacySetupMutex "EchoSingleInstanceTestB"
#ifndef TestHoldMs
  #define TestHoldMs 6000
#endif
#ifndef OutDir
  #define OutDir "."
#endif

[Setup]
AppId={{0B1F9E52-6D1A-4C7B-9B53-5C2D7E4A1F10}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={tmp}\single-instance-test
Uninstallable=no
CreateUninstallRegKey=no
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=single-instance-test
Compression=none

[Files]
Source: "{srcexe}"; DestDir: "{tmp}"; Flags: external

[Code]
#include "..\..\installer\single_instance.isi"
