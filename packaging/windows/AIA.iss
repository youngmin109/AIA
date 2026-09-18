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
WizardStyle=modern
#ifdef AIA_SIGNTOOL
SignTool=AIA
SignedUninstaller=yes
#endif

[Files]
Source: "..\..\dist\windows\AIA\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\..\dist\windows\aia-cli\*"; DestDir: "{app}\aia-cli"; Flags: recursesubdirs ignoreversion
Source: "..\..\README.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\INSTALL.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}\docs"; Flags: ignoreversion
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
