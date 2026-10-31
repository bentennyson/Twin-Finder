# Twin Finder downloads

Installers are attached to this repository's GitHub Releases. They are downloaded as individual files, without cloning or downloading the source project.

## Windows

[Download TwinFinderSetup-1.0.1-Windows-x64.exe](https://github.com/bentennyson/Twin-Finder/releases/download/windows-v1.0.1/TwinFinderSetup-1.0.1-Windows-x64.exe)

Run the installer and open Twin Finder from the Start menu. Windows 10/11 on Intel/AMD 64-bit is required. Python and the AI models are included. This installer is unsigned. The Windows release includes a SHA-256 checksum.

## Mac test build

[Download TwinFinder-1.0.0-macOS-AppleSilicon.dmg](https://github.com/bentennyson/Twin-Finder/releases/download/macos-v1.0.0-test/TwinFinder-1.0.0-macOS-AppleSilicon.dmg)

Open the DMG and drag Twin Finder to Applications. Apple-silicon Macs running macOS 15 or later are supported by this test build. It is not Apple-notarized, and Gatekeeper may block a downloaded copy. Automated app/DMG checks passed; an independent downloaded installation has not been verified. Intel Macs are not supported.

[All releases and checksums](https://github.com/bentennyson/Twin-Finder/releases)

## Build from source

Windows: install the runtime/build requirements, then run `python build_windows.py --clean` followed by `python build_installer.py --version 1.0.1`. Inno Setup is required. The resulting installer is in `installer-output`.

Mac: use the `macos-build` branch and its `PACKAGING_MACOS.md` instructions. Source, tests and build evidence are separate from the installers.
