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
#define MyAppExeName "SubGen.exe"

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
Source: "dist\SubGen\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\logo.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\logo.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if MsgBox('Do you want to completely remove all downloaded AI models, cached weights, history logs, and application data entirely from your PC?' + #13#10#13#10 + 'Click YES to erase all model files and leave zero traces, or NO to keep downloaded models.', mbConfirmation, MB_YESNO) = idYes then
    begin
      // Downloaded models and history.json live in the per-user AppData
      // folder (not {app}\models under Program Files) since a standard user
      // can't write there — see DATA_DIR in subgen.py.
      DelTree(ExpandConstant('{localappdata}\SubTranscribe Studio'), True, True, True);
      DelTree(ExpandConstant('{app}'), True, True, True);
    end;
  end;
end;
