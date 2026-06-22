; Inno Setup script for Lumen (Windows installer).
;
; Build steps:
;   1. python scripts/build.py          (produces dist/Lumen.exe)
;   2. iscc installer/windows/lumen.iss  (produces installer/windows/Output/LumenSetup.exe)
;
; The installer offers an optional "Launch Lumen at Windows startup" task that
; writes an HKCU Run entry, matching the in-app autostart toggle.

#define AppName "Lumen"
#define AppVersion "1.0.3"
#define AppPublisher "JirkaachS"
#define AppURL "https://github.com/JirkaachS/Lumen"
#define AppExe "Lumen.exe"

[Setup]
AppId={{8F3C1A52-9D44-4E0B-9A1E-A1B2C3D4E5F6}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=LumenSetup-{#AppVersion}
SetupIconFile=..\..\lumen\assets\lumen.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Launch {#AppName} automatically when Windows starts"; GroupDescription: "Startup:"

[Files]
Source: "..\..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Autostart (per-user) — only created when the user ticks the startup task.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "Lumen"; ValueData: """{app}\{#AppExe}"" --minimized"; \
    Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName} now"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\Lumen"
