# Mac build status

The complete Windows source is preserved on main at commit d2449e69aff0843130383317e4d534604a103b19. The macos-build branch adds the Mac packager and platform-specific font/settings paths. It uses the same AI models, matching, storage, feedback and export services.

Local Windows regression checks: 28 passed. GitHub Actions provides the Mac execution evidence; do not treat preparation as a successful build.

Target: Apple-silicon Macs, macOS 15 or later. Developer ID signing, Apple notarization and an independent downloaded installation test are not yet completed.

The report results and screenshots remain Windows evidence tied to the main snapshot. Run research/verify_evidence.py on that snapshot; the Mac interface source differs. No Mac timing or usability claims are made by the Windows report.
