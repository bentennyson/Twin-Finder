; Build from the project root after running: python build_windows.py --clean
; ISCC TwinFinder.iss
; AppSource and InstallerOutput may be overridden with /Dname=value.
#ifndef AppSource
  #define AppSource SourcePath + "\dist\TwinFinder"
#endif
#ifndef InstallerOutput
  #define InstallerOutput SourcePath + "\installer-output"
#endif
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#if !FileExists(AppSource + "\TwinFinder.exe")
  #error "Build TwinFinder.exe first, or supply /DAppSource=the complete application folder."
#endif

[Setup]
AppId={{19CF73E5-9703-4BF3-8E92-4A94C59FC699}
AppName=Twin Finder
AppVersion={#AppVersion}
AppVerName=Twin Finder {#AppVersion}
VersionInfoVersion={#AppVersion}.0
AppComments=Local AI-assisted bibliographic duplicate review
DefaultDirName={localappdata}\Programs\TwinFinder
DefaultGroupName=Twin Finder
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible and not arm64
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
AllowNoIcons=yes
WizardStyle=modern
WizardSizePercent=110
OutputDir={#InstallerOutput}
OutputBaseFilename=TwinFinderSetup-{#AppVersion}-Windows-x64
Compression=lzma2/normal
SolidCompression=yes
UninstallDisplayName=Twin Finder
UninstallDisplayIcon={app}\TwinFinder.exe
CloseApplications=yes
CloseApplicationsFilter=TwinFinder.exe
RestartApplications=no
SetupLogging=yes
ChangesAssociations=no
UsePreviousAppDir=yes
UsePreviousTasks=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Twin Finder"; Filename: "{app}\TwinFinder.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Twin Finder"; Filename: "{app}\TwinFinder.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\TwinFinder.exe"; Description: "Open Twin Finder"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

; Deliberately no wildcard uninstall deletion. User-created jobs and datasets
; are not installer-owned files and must survive uninstall and upgrades.
