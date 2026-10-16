#define MyAppName "AIA"
#ifndef MyAppVersion
#define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "AIA Project"
#define MyAppExeName "AIA.exe"

[Setup]
AppId={{6B5E32E9-4B3D-4CE8-9AC6-7BA39F3B4A01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\AIA
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputBaseFilename=AIA-{#MyAppVersion}-Setup
OutputDir=..\..\dist\windows\installer
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\AIA.exe
SetupIconFile=aia.ico
WizardStyle=modern
#ifdef AIA_SIGNTOOL
SignTool=AIA
SignedUninstaller=yes
#endif

[Files]
Source: "..\..\dist\windows\AIA\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\..\dist\windows\aia-cli\*"; DestDir: "{app}\aia-cli"; Flags: recursesubdirs ignoreversion
; Codex runs this forwarder for every Hook event. Its fixed path keeps the Hook
; command, and Codex's trust in it, the same across AIA builds and updates.
Source: "..\..\dist\windows\aia-hook\*"; DestDir: "{app}\aia-hook"; Flags: recursesubdirs ignoreversion
Source: "..\..\README.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\README.ko.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\INSTALL.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\SECURITY.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\CONTRIBUTING.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\CHANGELOG.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\docs\WINDOWS-DESKTOP.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\docs\QUICKSTART.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\docs\USER-GUIDE.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\docs\TROUBLESHOOTING.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\docs\DISTRIBUTION.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\docs\PRODUCT-SUPPORT.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\docs\LIMITATIONS.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\docs\WINDOWS-SIGNING.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\AIA"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\AIA"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 AIA 바로가기 만들기"; GroupDescription: "추가 바로가기:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "AIA 실행"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Remove only AIA's handlers from Codex hooks.json before the files go away, so
; Codex is not left calling a deleted aia-cli.exe. User hooks are kept.
Filename: "{app}\aia-cli\aia-cli.exe"; Parameters: "hook uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveAiaCodexHook"
