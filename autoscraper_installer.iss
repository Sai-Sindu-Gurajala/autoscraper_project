; ------------------------------------------
; Inno Setup Script for Autoscraper
; ------------------------------------------

[Setup]
AppName=Autoscraper
AppVersion=1.0
DefaultDirName={pf}\Autoscraper
DefaultGroupName=Autoscraper
UninstallDisplayIcon={app}\Autoscraper.exe
OutputDir=dist
OutputBaseFilename=Autoscraper-Setup
Compression=lzma
SolidCompression=yes

; (Optional) Change installer icon
SetupIconFile=assets\icon.ico

[Files]
; Main compiled exe (from PyInstaller)
Source: "dist\Autoscraper.exe"; DestDir: "{app}"; Flags: ignoreversion

; Assets folder (contains chromedriver.exe, icons, etc.)
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs

[Icons]
; Start menu shortcut
Name: "{group}\Autoscraper"; Filename: "{app}\Autoscraper.exe"

; Desktop shortcut (optional)
Name: "{userdesktop}\Autoscraper"; Filename: "{app}\Autoscraper.exe"; Tasks: desktopicon

[Tasks]
; Checkbox in installer to create desktop shortcut
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
