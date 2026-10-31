# Package Twin Finder as a Windows application

You receive the full source and model files. Packaging creates a separate executable folder; it does not replace your source project.

The builder embeds `windows.manifest` to declare per-monitor DPI awareness. Keep that file with the source when rebuilding. Source execution initializes DPI awareness before creating the first Tk window; the packaged executable uses the manifest. Neither changes Windows display settings. Display scaling and a new interface require a fresh app launch, rather than reusing an already-open window.

1. Install 64-bit Python 3.13 with Tcl/Tk on Windows. Follow the virtual-environment and CPU dependency commands in `README.md`.
2. Install the packager in that environment:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.21.0
```

3. From the project directory, build:

```powershell
.\.venv\Scripts\python.exe build_windows.py --clean
```

4. The application is `dist\TwinFinder\TwinFinder.exe`. Keep the entire `TwinFinder` folder, including `_internal`; copying only the executable breaks its dependencies and model files. One-folder packaging avoids extracting the large neural runtime on every launch.
5. Run a launch check that loads the neural model, scores a pair and constructs the actual Tk interface:

```powershell
.\dist\TwinFinder\TwinFinder.exe --self-test C:\TwinFinderJobs\launch_check.json
```

Create the output parent folder first. Confirm the JSON reports `status: passed`, then open the application normally and follow the sample workflow in `USER_MANUAL.md`. If a build or launch fails, use `python build_windows.py --debug-console --clean` to retain a console with diagnostics. Do not disable operating-system security settings to run an unverified executable.

You can also open the application and choose **Help → Run diagnostics**. This loads the bundled neural model and reports the saved diagnostic JSON path. Consult the current delivery verification for the exact source and packaged checks performed; a successful build alone is not proof that every screen works.

The supplied `build_windows.ps1` is an equivalent convenience wrapper for environments that allow PowerShell scripts; the Python builder does not require changing that policy. Build on Windows for Windows. This is an unsigned application folder, not a signed installer, an auto-update service or a cross-platform distribution.

The final delivery verification records exactly which build and launch checks completed in the preparation environment. A fresh dependency installation and a second-machine installation are separate checks; do not describe them as tested unless you perform them.
