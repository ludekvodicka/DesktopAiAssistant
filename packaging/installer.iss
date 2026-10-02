; Per-user Setup for first installs: python packaging/package_release.py runs
; iscc /DAppVersion=X.Y.Z packaging/installer.iss on the folder build in dist/DesktopAiAssistant.
; Later releases install themselves from the release zip (src/desktop_ai_assistant/updates.py).
; ASCII only.

#ifndef AppVersion
  #error Pass /DAppVersion=X.Y.Z
#endif

[Setup]
; Equal to InstallRegistration.app_id; a test compares them. Never change it.
AppId={{9EA4AB2D-541B-497C-A34F-10C2FBE9D378}
AppName=Desktop AI Assistant
AppVersion={#AppVersion}
AppVerName=Desktop AI Assistant {#AppVersion}
AppPublisher=ludekvodicka
AppPublisherURL=https://github.com/ludekvodicka/DesktopAiAssistant
AppSupportURL=https://github.com/ludekvodicka/DesktopAiAssistant/issues
UninstallDisplayName=Desktop AI Assistant
UninstallDisplayIcon={app}\DesktopAiAssistant.exe
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\DesktopAiAssistant
DisableDirPage=yes
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=force
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
OutputDir=..\dist\release
OutputBaseFilename=DesktopAiAssistant-Setup-{#AppVersion}-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[InstallDelete]
; PyInstaller replaces its runtime folder as a whole; files of an older build must not stay.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\DesktopAiAssistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Desktop AI Assistant"; Filename: "{app}\DesktopAiAssistant.exe"; WorkingDir: "{app}"

[Registry]
; The app writes these at every start (browser_setup.register_browser); Setup only removes them.
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\com.desktopai.assistant"; Flags: uninsdeletekey dontcreatekey
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\com.desktopai.assistant"; Flags: uninsdeletekey dontcreatekey

[Run]
Filename: "{app}\DesktopAiAssistant.exe"; Description: "Start Desktop AI Assistant"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The self-update stages beside the program folder and keeps its cache in the data folder.
; Settings, history and other user data in the data folder stay.
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{app}.staged"
Type: filesandordirs; Name: "{app}.staged.part"
Type: filesandordirs; Name: "{app}.old"
Type: filesandordirs; Name: "{localappdata}\DesktopAiAssistant\updates"
Type: files; Name: "{localappdata}\DesktopAiAssistant\update-notified.txt"

[Code]
procedure StopRunningCopies();
var
  Folder: String;
  ResultCode: Integer;
begin
  { The app and browser-started DesktopAiHost.exe processes hold files in the program folder. }
  Folder := ExpandConstant('{app}');
  StringChangeEx(Folder, '''', '''''', True);
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "Get-Process DesktopAiAssistant,DesktopAiHost -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -like ''' + Folder + '\*'' } | Stop-Process -Force -PassThru | ' +
    'Wait-Process -Timeout 10 -ErrorAction SilentlyContinue"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function InitializeUninstall(): Boolean;
begin
  StopRunningCopies();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command: String;
begin
  { "Start with Windows" writes this value; remove it only when it starts this copy. }
  if (CurUninstallStep = usPostUninstall) and
     RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DesktopAiAssistant', Command) and
     (Pos(Lowercase(ExpandConstant('{app}')), Lowercase(Command)) > 0) then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DesktopAiAssistant');
end;
