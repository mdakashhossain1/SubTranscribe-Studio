; Script generated for SubTranscribe Studio Enterprise Edition
#define MyAppName "SubTranscribe Studio"
; Version is read directly from the VERSION file at the project root — the
; single source of truth also read by subgen.py at runtime. CI overwrites
; that file from the git tag before compiling (see build-desktop.yml).
; Read via ISPP's FileOpen/FileRead rather than GetEnv("APP_VERSION"): the
; env-var approach silently produced a broken build in CI (the compile step
; reported success but the installer's filename/version never resolved
; correctly), while reading the file directly is simple, dependency-free,
; and has been verified against the real Inno Setup compiler.
#if FileExists("VERSION")
  #define MyAppVersion Trim(FileRead(FileOpen("VERSION")))
#else
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "SubTranscribe AI"
#define MyAppExeName "SubTranscribeStudio.exe"

[Setup]
AppId={{0809257F-F8EF-4A97-8872-7D92A6BFCACD}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=SubTranscribe_Studio_Setup_v{#MyAppVersion}
SetupIconFile=assets\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "dist\SubTranscribeStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\logo.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\logo.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// Downloaded models and history.json live in the per-user AppData folder
// (not {app}\models under Program Files) since a standard user can't write
// there — see DATA_DIR in subgen.py. A normal install/upgrade only ever
// writes under {app} (via [Files] above), so re-running this installer to
// update to a new version never touches this folder — models and history
// always survive an update untouched.

var
  CleanUninstall: Boolean;

function InitializeUninstall(): Boolean;
var
  DataDir: String;
begin
  Result := True;
  CleanUninstall := False;
  DataDir := ExpandConstant('{localappdata}\SubTranscribe Studio');

  if DirExists(DataDir) then
  begin
    // Crystal-clear single prompt:
    // Yes = Completely delete all downloaded AI models and history (Clean wipe)
    // No  = Keep models and history for future use (Default uninstall)
    CleanUninstall := (MsgBox('Do you also want to completely delete all downloaded AI models and data?' + #13#10#13#10 + '• Click YES to remove all downloaded models, cache, and history.' + #13#10 + '• Click NO to keep your downloaded models for future use.', mbConfirmation, MB_YESNO) = idYes);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\SubTranscribe Studio');
    if CleanUninstall and DirExists(DataDir) then
      DelTree(DataDir, True, True, True);
  end;
  // {app} itself (the installed program files) is removed automatically by
  // Inno Setup's own uninstall process — no need to DelTree it here.
end;
