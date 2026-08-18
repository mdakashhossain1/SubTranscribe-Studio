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
//
// Uninstall uses a single custom form with checkboxes (all unchecked by
// default) so the user explicitly opts-in to deleting optional data.
// The software is always removed; only the data choices differ.

var
  RemoveModels, RemoveHistory: Boolean;

// ── Custom uninstall dialog ───────────────────────────────────────────────
procedure ShowUninstallOptionsForm;
var
  Form       : TSetupForm;
  HeadLbl    : TLabel;
  SubLbl     : TLabel;
  Sep        : TBevel;
  ModChk     : TCheckBox;
  HistChk    : TCheckBox;
  NoteLbl    : TLabel;
  BtnPanel   : TPanel;
  UninstBtn  : TButton;
  CancelBtn  : TButton;
  DataDir    : String;
  ModelsDir  : String;
  HistFile   : String;
begin
  DataDir   := ExpandConstant('{localappdata}\SubTranscribe Studio');
  ModelsDir := DataDir + '\models';
  HistFile  := DataDir + '\history.json';

  Form := CreateCustomForm();
  Form.Caption  := 'Uninstall SubTranscribe Studio';
  Form.Width    := 480;
  Form.Height   := 300;
  Form.Position := poScreenCenter;
  Form.Color    := $160D09;  // dark background

  // Heading
  HeadLbl         := TLabel.Create(Form);
  HeadLbl.Parent  := Form;
  HeadLbl.Caption := 'Remove SubTranscribe Studio?';
  HeadLbl.Font.Style := [fsBold];
  HeadLbl.Font.Size  := 11;
  HeadLbl.Font.Color := $F8FAFC;
  HeadLbl.Left    := 24;
  HeadLbl.Top     := 20;
  HeadLbl.Width   := 420;

  // Sub-text
  SubLbl         := TLabel.Create(Form);
  SubLbl.Parent  := Form;
  SubLbl.Caption := 'The application will be removed. Optionally delete stored data:';
  SubLbl.Font.Size  := 9;
  SubLbl.Font.Color := $B8A394;
  SubLbl.Left    := 24;
  SubLbl.Top     := 46;
  SubLbl.Width   := 420;

  // Separator
  Sep          := TBevel.Create(Form);
  Sep.Parent   := Form;
  Sep.Left     := 24;
  Sep.Top      := 70;
  Sep.Width    := 420;
  Sep.Height   := 2;
  Sep.Shape    := bsTopLine;

  // Models checkbox (only shown if models directory exists)
  ModChk         := TCheckBox.Create(Form);
  ModChk.Parent  := Form;
  ModChk.Caption := 'Delete downloaded AI models  (can be several GB)';
  ModChk.Font.Size  := 9;
  ModChk.Font.Color := $F8FAFC;
  ModChk.Left    := 24;
  ModChk.Top     := 88;
  ModChk.Width   := 420;
  ModChk.Checked := False;
  ModChk.Enabled := DirExists(ModelsDir);

  // History checkbox (only shown if history file exists)
  HistChk         := TCheckBox.Create(Form);
  HistChk.Parent  := Form;
  HistChk.Caption := 'Delete transcription history log';
  HistChk.Font.Size  := 9;
  HistChk.Font.Color := $F8FAFC;
  HistChk.Left    := 24;
  HistChk.Top     := 116;
  HistChk.Width   := 420;
  HistChk.Checked := False;
  HistChk.Enabled := FileExists(HistFile);

  // Note
  NoteLbl         := TLabel.Create(Form);
  NoteLbl.Parent  := Form;
  NoteLbl.Caption := 'Leave boxes unchecked to keep your models and history.';
  NoteLbl.Font.Size  := 8;
  NoteLbl.Font.Color := $7A8A94;
  NoteLbl.Left    := 24;
  NoteLbl.Top     := 148;
  NoteLbl.Width   := 420;

  // Button panel
  BtnPanel           := TPanel.Create(Form);
  BtnPanel.Parent    := Form;
  BtnPanel.BevelOuter := bvNone;
  BtnPanel.Color     := $160D09;
  BtnPanel.Left      := 0;
  BtnPanel.Top       := Form.Height - 68;
  BtnPanel.Width     := Form.Width;
  BtnPanel.Height    := 56;

  // Cancel button
  CancelBtn          := TButton.Create(Form);
  CancelBtn.Parent   := BtnPanel;
  CancelBtn.Caption  := 'Cancel';
  CancelBtn.Width    := 90;
  CancelBtn.Height   := 32;
  CancelBtn.Left     := BtnPanel.Width - 110;
  CancelBtn.Top      := 12;
  CancelBtn.ModalResult := mrCancel;

  // Uninstall button
  UninstBtn          := TButton.Create(Form);
  UninstBtn.Parent   := BtnPanel;
  UninstBtn.Caption  := 'Uninstall';
  UninstBtn.Width    := 100;
  UninstBtn.Height   := 32;
  UninstBtn.Left     := BtnPanel.Width - 218;
  UninstBtn.Top      := 12;
  UninstBtn.ModalResult := mrOk;
  UninstBtn.Default  := True;

  if Form.ShowModal = mrOk then
  begin
    RemoveModels  := ModChk.Checked  and ModChk.Enabled;
    RemoveHistory := HistChk.Checked and HistChk.Enabled;
  end
  else
    Abort();  // User clicked Cancel — halt uninstall

  Form.Free();
end;

function InitializeUninstall(): Boolean;
begin
  Result        := True;
  RemoveModels  := False;
  RemoveHistory := False;
  ShowUninstallOptionsForm();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, ModelsDir, HistFile: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    DataDir   := ExpandConstant('{localappdata}\SubTranscribe Studio');
    ModelsDir := DataDir + '\models';
    HistFile  := DataDir + '\history.json';

    if RemoveModels then
      DelTree(ModelsDir, True, True, True);

    if RemoveHistory then
      DeleteFile(HistFile);

    // If both were removed and nothing else remains, clean the shell folder too
    if RemoveModels and RemoveHistory and DirExists(DataDir) then
      DelTree(DataDir, True, True, True);
  end;
  // {app} itself (the installed program files) is removed automatically by
  // Inno Setup's own uninstall process — no need to DelTree it here.
end;
