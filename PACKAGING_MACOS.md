# Build Twin Finder for macOS without owning a Mac

Status: the Mac test build passed automated checks on October 31, 2026. See MACOS_BUILD_STATUS.md for the download and verification limits.

This package targets Apple M-series Macs running macOS 15 or later. It uses the same matching, AI, review, learning, storage and export modules and the same model files as the Windows release. The only runtime edits select a Mac font and the macOS Application Support location for the recent-jobs list. Windows behavior is preserved.

Intel Macs are not included: the pinned PyTorch 2.10.0 dependency has macOS arm64 wheels, but not matching Intel wheels. Do not label this an installer for every Mac. Windows-only research screenshot tooling remains available for reproducing the original Windows report evidence; it is not part of the Mac application.

## Repository layout

Put the CONTENTS of this project directory at your GitHub repository root. The `.github` directory must be at the repository root, alongside `desktop.py`, `requirements.txt` and `models`.

Keep `models/encoder.pt` with the project. It is about 90 MB, so GitHub's browser uploader will not accept it. Use Git or GitHub Desktop to push the source directory. Do not upload your `.venv`, generated installers, personal datasets or saved jobs. The provided source archive includes reproducibility datasets and results intentionally, but no personal job databases or original report documents.

## Run the cloud build

1. Open https://github.com/bentennyson/Twin-Finder/actions and select **Build Mac application**.
2. A push to macos-build starts the build automatically. Manual dispatch becomes available once the workflow exists on the default branch.
3. After a successful run, download **TwinFinder-macOS-AppleSilicon-test-build** from its Artifacts section.
4. Extract the downloaded ZIP to obtain the `.dmg` and its checksum.

The workflow runs for pushes to macos-build and supports manual dispatch once present on the default branch. It uses a standard `macos-15` Apple-silicon runner, a 35-minute timeout, and seven-day artifact retention. Private repositories use your account's included Actions allowance and may incur charges if billing permits overages. Public repositories make the source visible; do not change visibility solely to avoid build charges without considering that consequence.

The job installs the official Python 3.13.3 macOS package after checking its signature, installs pinned dependencies, runs the existing regression suite, builds the application, checks its bundled neural model and UI, creates a DMG, and repeats the packaged diagnostic from the mounted DMG. Failed checks prevent the download artifact from being published. Build evidence is saved separately even on failure. A green result is automated evidence, not an independent user-installation test.

## Installation experience and signing

The disk image contains `Twin Finder.app` and an Applications shortcut. A recipient drags the app into Applications. Python and separate model downloads are not needed once the app is built successfully.

The initial build has an ad-hoc signature, not an Apple Developer ID signature, and is not notarized. Gatekeeper may block a downloaded copy. For ordinary public distribution, obtain an Apple Developer ID signing identity and configure signing plus Apple's notarization before release. No certificate, account password, or private signing key should be pasted into chat or committed to Git. The current workflow neither requests nor uses them, and does not bypass Gatekeeper.

Until that signing work and an interactive download/install test are completed, describe the output as a Mac test build, not a production installer with verified first-launch behavior. Do not claim support for macOS releases earlier than 15 or for Intel Macs.

## Local Mac build, if a Mac becomes available

With native arm64 Python 3.13.3 from python.org installed:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt PyInstaller==6.21.0 pytest==8.4.2
.venv/bin/python -m pytest tests -q
.venv/bin/python build_macos.py --version 1.0.0
```

The output is `dist-macos/TwinFinder-1.0.0-macOS-AppleSilicon.dmg`. Source, packaged, and DMG diagnostics are in `build-evidence`. Saved datasets stay outside the app; recent-job metadata on macOS is in `~/Library/Application Support/TwinFinder/recent.json`.

## References

- GitHub-hosted runner architectures and private-repository usage: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- PyInstaller platform-specific packaging: https://pyinstaller.org/en/stable/usage.html
- Python installer: https://www.python.org/downloads/release/python-3133/
- PyTorch release files: https://pypi.org/project/torch/2.10.0/#files
- Apple notarization: https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution
