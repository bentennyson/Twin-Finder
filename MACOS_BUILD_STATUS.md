# Mac build verification

Build: https://github.com/bentennyson/Twin-Finder/actions/runs/41231512900
Built source: c9222916b654e9541917754dd0ff1fcf02fa4e9a

- Target: Apple-silicon Macs, macOS 15 or later.
- Mac regression suite: 28 passed in 13.44 seconds; two TorchScript deprecation warnings.
- Windows portability regression: 28 passed in 22.80 seconds; the same two warnings.
- Source, packaged application and mounted-DMG diagnostics passed, including neural inference and construction of the Tk interface.
- DMG integrity and ad-hoc application signatures verified.
- Download ZIP SHA-256: 245109fbf68a207f6df2076527372d7949ddf7b373a5339b8604f862f9da46b6

Download: https://github.com/bentennyson/Twin-Finder/actions/runs/41231512900/artifacts/13053718550
The GitHub artifact is retained for seven days from October 31, 2026. Save a local copy before expiry.

Developer ID signing, Apple notarization and an independent downloaded installation test remain incomplete. This is a test build, not a notarized public release. Intel Macs are not supported by this pinned dependency set.

The first Mac test attempt stalled while update() drained continuous animation events. The UI tests now run the same mainloop used by the app, with a scheduled bounded quit; no tests or assertions were skipped. Core AI, matching, storage, feedback and export algorithms remain unchanged. The Windows report evidence remains tied to its recorded Windows source snapshot.
