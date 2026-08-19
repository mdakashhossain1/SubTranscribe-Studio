; Script generated for SubTranscribe Studio Enterprise Edition
#define MyAppName "SubTranscribe Studio"
; Version is read directly from the VERSION file at the project root — the
; single source of truth also read by main.py at runtime. CI overwrites
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
SetupIconFile=subtranscribe\assets\logo.ico
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
// there — see DATA_DIR in main.py. A normal install/upgrade only ever
// writes under {app} (via [Files] above), so re-running this installer to
// update to a new version never touches this folder — models and history
// always survive an update untouched.

var
  CleanUninstall: Boolean;

function InitializeUninstall(): Boolean;
var
  DataDir: String;
  UninstallForm: TSetupForm;
  InfoLabel: TNewStaticText;
  CleanCheckBox: TNewCheckBox;
  ButtonsDivider: TBevel;
  BtnUninstall, BtnCancel: TNewButton;
  HasDataDir: Boolean;
  FormHeight: Integer;
begin
  Result := False;
  CleanUninstall := False;
  DataDir := ExpandConstant('{localappdata}\SubTranscribe Studio');
  HasDataDir := DirExists(DataDir);

  // Single wizard-styled confirmation dialog (built from the same native
  // controls the install wizard uses) instead of two chained native
  // MsgBox() popups — one checkbox covers the cleanup choice.
  UninstallForm := CreateCustomForm();
  try
    FormHeight := 170;
    if HasDataDir then
      FormHeight := FormHeight + 34;

    UninstallForm.ClientWidth := ScaleX(420);
    UninstallForm.ClientHeight := ScaleY(FormHeight);
    UninstallForm.Caption := 'Uninstall SubTranscribe Studio';
    UninstallForm.Position := poScreenCenter;
    UninstallForm.BorderStyle := bsDialog;

    InfoLabel := TNewStaticText.Create(UninstallForm);
    InfoLabel.Parent := UninstallForm;
    InfoLabel.Left := ScaleX(20);
    InfoLabel.Top := ScaleY(20);
    InfoLabel.Width := UninstallForm.ClientWidth - ScaleX(40);
    InfoLabel.AutoSize := False;
    InfoLabel.Height := ScaleY(48);
    InfoLabel.WordWrap := True;
    InfoLabel.Caption := 'Are you sure you want to completely remove SubTranscribe Studio and all of its components from this computer?';

    if HasDataDir then
    begin
      CleanCheckBox := TNewCheckBox.Create(UninstallForm);
      CleanCheckBox.Parent := UninstallForm;
      CleanCheckBox.Left := ScaleX(20);
      CleanCheckBox.Top := InfoLabel.Top + InfoLabel.Height + ScaleY(8);
      CleanCheckBox.Width := UninstallForm.ClientWidth - ScaleX(40);
      CleanCheckBox.Height := ScaleY(34);
      CleanCheckBox.Caption := 'Also delete downloaded AI models, cache, and history' + #13#10 + '(complete cleanup — leaves zero traces on this PC)';
      CleanCheckBox.Checked := False;
    end
    else
      CleanCheckBox := nil;

    ButtonsDivider := TBevel.Create(UninstallForm);
    ButtonsDivider.Parent := UninstallForm;
    ButtonsDivider.Left := 0;
    ButtonsDivider.Top := UninstallForm.ClientHeight - ScaleY(52);
    ButtonsDivider.Width := UninstallForm.ClientWidth;
    ButtonsDivider.Height := 1;
    ButtonsDivider.Shape := bsTopLine;

    BtnCancel := TNewButton.Create(UninstallForm);
    BtnCancel.Parent := UninstallForm;
    BtnCancel.Width := ScaleX(90);
    BtnCancel.Height := ScaleY(28);
    BtnCancel.Left := UninstallForm.ClientWidth - ScaleX(20) - BtnCancel.Width;
    BtnCancel.Top := UninstallForm.ClientHeight - ScaleY(38);
    BtnCancel.Caption := 'Cancel';
    BtnCancel.Cancel := True;
    BtnCancel.ModalResult := mrCancel;

    BtnUninstall := TNewButton.Create(UninstallForm);
    BtnUninstall.Parent := UninstallForm;
    BtnUninstall.Width := ScaleX(100);
    BtnUninstall.Height := ScaleY(28);
    BtnUninstall.Left := BtnCancel.Left - ScaleX(10) - BtnUninstall.Width;
    BtnUninstall.Top := BtnCancel.Top;
    BtnUninstall.Caption := 'Uninstall';
    BtnUninstall.Default := True;
    BtnUninstall.ModalResult := mrOk;

    if UninstallForm.ShowModal() = mrOk then
    begin
      Result := True;
      if HasDataDir then
        CleanUninstall := CleanCheckBox.Checked;
    end;
  finally
    UninstallForm.Free;
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
