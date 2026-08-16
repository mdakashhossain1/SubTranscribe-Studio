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
  RemoveModels, RemoveHistory: Boolean;

function InitializeUninstall(): Boolean;
var
  DataDir, ModelsDir, HistFile: String;
begin
  // A custom TSetupForm-based checkbox dialog was tried here first, but
  // TSetupForm is only backed by a resource embedded in the *installer*
  // executable — the separate uninstaller stub doesn't have it, so it
  // compiled fine but failed at runtime with "Resource TSetupForm not
  // found." Sequential MsgBox prompts have no such resource dependency
  // and are guaranteed available in both install and uninstall contexts.
  Result := True;      // proceed with a normal uninstall by default
  RemoveModels := False;
  RemoveHistory := False;

  DataDir := ExpandConstant('{localappdata}\SubTranscribe Studio');
  ModelsDir := DataDir + '\models';
  HistFile := DataDir + '\history.json';

  if DirExists(ModelsDir) then
    RemoveModels := (MsgBox('Also permanently delete the downloaded AI models (can be several GB)?', mbConfirmation, MB_YESNO) = idYes);

  if FileExists(HistFile) then
    RemoveHistory := (MsgBox('Also permanently delete the transcription history log?', mbConfirmation, MB_YESNO) = idYes);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, ModelsDir, HistFile: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\SubTranscribe Studio');
    ModelsDir := DataDir + '\models';
    HistFile := DataDir + '\history.json';

    if RemoveModels then
      DelTree(ModelsDir, True, True, True);

    if RemoveHistory then
      DeleteFile(HistFile);

    // Both categories removed and nothing else was ever written to this
    // folder (no separate settings file exists) — clean up the now-empty
    // shell too, so zero traces remain as promised.
    if RemoveModels and RemoveHistory and DirExists(DataDir) then
      DelTree(DataDir, True, True, True);
  end;
  // {app} itself (the installed program files) is removed automatically by
  // Inno Setup's own uninstall process — no need to DelTree it here.
end;
