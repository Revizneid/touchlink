[Setup]
AppName=TouchLink
AppVersion=1.0.0
DefaultDirName={userappdata}\TouchLink
DefaultGroupName=TouchLink
PrivilegesRequired=lowest
OutputBaseFilename=TouchLink-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "..\dist\TouchLink.exe"; DestDir: "{app}"
Source: "..\web\*"; DestDir: "{app}\web"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TouchLink"; Filename: "{app}\TouchLink.exe"
Name: "{group}\Uninstall TouchLink"; Filename: "{app}\unins000.exe"

[Run]
Filename: "{app}\TouchLink.exe"; Description: "Start TouchLink"; Flags: nowait postinstall unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
