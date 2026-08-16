; Script generated for SubTranscribe Studio Enterprise Edition
#define MyAppName "SubTranscribe Studio"
; Version comes from the APP_VERSION env var, set by CI from the git tag
; (see .github/workflows/build-desktop.yml). Falls back to 0.0.0-dev for a
; local manual compile where that env var isn't set.
#define MyAppVersion GetEnv("APP_VERSION")
#if MyAppVersion == ""
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
  Form: TSetupForm;
  Lbl: TNewStaticText;
  ChkModels, ChkHistory: TNewCheckBox;
  BtnUninstall, BtnCancel: TNewButton;
  DataDir, ModelsDir, HistFile: String;
begin
  Result := True;      // proceed with a normal uninstall by default
  RemoveModels := False;
  RemoveHistory := False;

  DataDir := ExpandConstant('{localappdata}\SubTranscribe Studio');
  ModelsDir := DataDir + '\models';
  HistFile := DataDir + '\history.json';

  // Nothing extra on disk to offer removing — just do a normal uninstall.
  if not DirExists(ModelsDir) and not FileExists(HistFile) then
    Exit;

  Form := TSetupForm.Create(nil);
  try
    Form.ClientWidth := ScaleX(420);
    Form.ClientHeight := ScaleY(210);
    Form.Caption := 'Uninstall SubTranscribe Studio';
    Form.Position := poScreenCenter;

    Lbl := TNewStaticText.Create(Form);
    Lbl.Parent := Form;
    Lbl.Left := ScaleX(16);
    Lbl.Top := ScaleY(12);
    Lbl.Width := Form.ClientWidth - ScaleX(32);
    Lbl.AutoSize := False;
    Lbl.WordWrap := True;
    Lbl.Height := ScaleY(48);
    Lbl.Caption := 'The application will now be removed. Anything left unchecked below stays on your PC untouched — check only what you also want permanently deleted:';

    ChkModels := TNewCheckBox.Create(Form);
    ChkModels.Parent := Form;
    ChkModels.Left := ScaleX(24);
    ChkModels.Top := ScaleY(68);
    ChkModels.Width := Form.ClientWidth - ScaleX(48);
    ChkModels.Caption := 'Downloaded AI models (can be several GB)';
    ChkModels.Checked := False;
    ChkModels.Enabled := DirExists(ModelsDir);

    ChkHistory := TNewCheckBox.Create(Form);
    ChkHistory.Parent := Form;
    ChkHistory.Left := ScaleX(24);
    ChkHistory.Top := ScaleY(96);
    ChkHistory.Width := Form.ClientWidth - ScaleX(48);
    ChkHistory.Caption := 'Transcription history log';
    ChkHistory.Checked := False;
    ChkHistory.Enabled := FileExists(HistFile);

    BtnUninstall := TNewButton.Create(Form);
    BtnUninstall.Parent := Form;
    BtnUninstall.Width := ScaleX(100);
    BtnUninstall.Height := ScaleY(23);
    BtnUninstall.Left := Form.ClientWidth - ScaleX(216);
    BtnUninstall.Top := Form.ClientHeight - ScaleY(32);
    BtnUninstall.Caption := 'Uninstall';
    BtnUninstall.ModalResult := mrOk;
    Form.ActiveControl := BtnUninstall;

    BtnCancel := TNewButton.Create(Form);
    BtnCancel.Parent := Form;
    BtnCancel.Width := ScaleX(100);
    BtnCancel.Height := ScaleY(23);
    BtnCancel.Left := Form.ClientWidth - ScaleX(108);
    BtnCancel.Top := Form.ClientHeight - ScaleY(32);
    BtnCancel.Caption := 'Cancel';
    BtnCancel.ModalResult := mrCancel;

    if Form.ShowModal() = mrOk then
    begin
      RemoveModels := ChkModels.Checked;
      RemoveHistory := ChkHistory.Checked;
      Result := True;
    end
    else
      Result := False;  // user cancelled — abort the uninstall entirely
  finally
    Form.Free();
  end;
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
