"""Compile Twin Finder's installer after building dist/TwinFinder on Windows."""
import argparse
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', help='Full path to the Inno Setup ISCC.exe compiler')
    parser.add_argument('--version', default='1.0.0', help='Three-part release version, e.g. 1.0.1')
    args = parser.parse_args()
    if len(args.version.split('.')) != 3 or not all(p.isdigit() and int(p) <= 65535 for p in args.version.split('.')):
        parser.error('Version must contain three integers between 0 and 65535.')
    root = Path(__file__).resolve().parent
    compiler = args.iscc or shutil.which('ISCC.exe')
    if not compiler:
        for folder in ('C:/Program Files (x86)/Inno Setup 6', 'C:/Program Files/Inno Setup 7', 'C:/Program Files (x86)/Inno Setup 7'):
            candidate = Path(folder) / 'ISCC.exe'
            if candidate.is_file():
                compiler = str(candidate)
                break
    if not compiler:
        parser.error('Install Inno Setup from https://jrsoftware.org/isdl.php or pass --iscc PATH.')
    bundle = root / 'dist' / 'TwinFinder'
    required = ('TwinFinder.exe', '_internal/models/encoder.pt', '_internal/models/tokenizer.json', '_internal/models/base_classifier.json')
    for name in required:
        if not (bundle / name).is_file():
            parser.error(f'Missing {bundle / name}. First run: python build_windows.py --clean')
    subprocess.run([compiler, f'/DAppVersion={args.version}', str(root / 'TwinFinder.iss')], cwd=root, check=True)
    print(root / 'installer-output' / f'TwinFinderSetup-{args.version}-Windows-x64.exe')


if __name__ == '__main__':
    main()
