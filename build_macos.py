"""Build an Apple-silicon .app and .dmg on macOS; no Windows cross-compilation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import tempfile


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='1.0.0')
    args = parser.parse_args()
    if len(args.version.split('.')) != 3 or not all(p.isdigit() for p in args.version.split('.')):
        parser.error('Version must have three numeric parts, such as 1.0.0.')
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        parser.error('Run this builder on an Apple-silicon Mac with native arm64 Python. Intel is not supported by this dependency set.')
    root = Path(__file__).resolve().parent
    dist = root / 'dist-macos'
    work = root / 'build-macos'
    logs = root / 'build-evidence'
    for directory in (dist, work, logs):
        directory.mkdir(exist_ok=True)
    # A source launch validates model integrity, inference and Tk before packaging.
    run(sys.executable, root / 'desktop.py', '--self-test', logs / 'source-diagnostics.json', cwd=root)
    env = os.environ.copy()
    env['MACOSX_DEPLOYMENT_TARGET'] = '15.0'
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
               '--name', 'Twin Finder', '--target-arch', 'arm64', '--osx-bundle-identifier', 'org.twinfinder.desktop',
               '--distpath', str(dist), '--workpath', str(work), '--specpath', str(work),
               '--add-data', str(root / 'models') + ':models', '--collect-all', 'tokenizers']
    for module in ('sentence_transformers', 'transformers', 'sklearn', 'scipy', 'pandas', 'matplotlib', 'pytest',
                   'torchvision', 'torchaudio', 'IPython', 'notebook', 'streamlit'):
        command += ['--exclude-module', module]
    command.append(str(root / 'desktop.py'))
    run(*command, cwd=root, env=env)
    app = dist / 'Twin Finder.app'
    executable = app / 'Contents' / 'MacOS' / 'Twin Finder'
    with (app / 'Contents' / 'Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    if info.get('CFBundleIdentifier') != 'org.twinfinder.desktop':
        raise RuntimeError('Incorrect application bundle identifier.')
    info.update(CFBundleShortVersionString=args.version, CFBundleVersion=args.version,
                LSMinimumSystemVersion='15.0', NSHighResolutionCapable=True)
    with (app / 'Contents' / 'Info.plist').open('wb') as stream:
        plistlib.dump(info, stream)
    # Updating Info.plist invalidates the outer ad-hoc signature; nested binaries
    # already have PyInstaller's signatures and are not modified here.
    run('codesign', '--force', '--sign', '-', app)
    run('codesign', '--verify', '--deep', '--strict', app)
    # Use a fresh working directory; bundle resolution must not rely on the source tree.
    with tempfile.TemporaryDirectory(prefix='twinfinder-launch-') as launch_dir:
        run(executable, '--self-test', logs / 'packaged-diagnostics.json', cwd=launch_dir)
    for name in ('source-diagnostics.json', 'packaged-diagnostics.json'):
        result = json.loads((logs / name).read_text())
        if result.get('status') != 'passed' or not result.get('tk_ui_constructed'):
            raise RuntimeError(f'Application diagnostic failed: {name}')
    dmg = dist / f'TwinFinder-{args.version}-macOS-AppleSilicon.dmg'
    with tempfile.TemporaryDirectory(prefix='twinfinder-dmg-') as staging:
        stage = Path(staging)
        run('ditto', app, stage / app.name)
        (stage / 'Applications').symlink_to('/Applications', target_is_directory=True)
        (stage / 'READ ME.txt').write_text(
            'Twin Finder for Apple-silicon Macs\n\n'
            'Drag Twin Finder into Applications, then open it from Applications.\n'
            'The AI models and runtime are included; Python is not required.\n'
            'Keep datasets in a writable folder outside the application.\n\n'
            'This is a test build: it has an ad-hoc signature, not a Developer ID signature,\n'
            'and is not notarized by Apple. Gatekeeper may prevent it from opening.\n'
            'Do not disable Gatekeeper or remove quarantine to bypass this.\n'
            'A Developer ID signed and notarized release is needed for normal distribution.\n'
            'Built and automatically checked on macOS 15; other versions and an interactive\n'
            'download/install on an independent Mac are not yet verified.\n', encoding='utf-8')
        run('hdiutil', 'create', '-volname', 'Twin Finder', '-srcfolder', stage, '-ov', '-format', 'UDZO', dmg)
    run('hdiutil', 'verify', dmg)
    # Also check the copy actually shipped inside the disk image.
    with tempfile.TemporaryDirectory(prefix='twinfinder-mount-') as mount_dir:
        run('hdiutil', 'attach', dmg, '-readonly', '-nobrowse', '-mountpoint', mount_dir)
        try:
            mounted = Path(mount_dir) / app.name
            run('codesign', '--verify', '--deep', '--strict', mounted)
            run(mounted / 'Contents/MacOS/Twin Finder', '--self-test', logs / 'dmg-diagnostics.json', cwd=mount_dir)
        finally:
            run('hdiutil', 'detach', mount_dir)
    mounted_result = json.loads((logs / 'dmg-diagnostics.json').read_text())
    if mounted_result.get('status') != 'passed' or not mounted_result.get('tk_ui_constructed'):
        raise RuntimeError('The application inside the disk image failed diagnostics.')
    digest = hashlib.file_digest(dmg.open('rb'), 'sha256').hexdigest()
    (dist / 'SHA256SUMS.txt').write_text(f'{digest}  {dmg.name}\n', encoding='utf-8')
    manifest = {'version': args.version, 'platform': platform.platform(), 'architecture': platform.machine(),
                'python': sys.version, 'dmg': dmg.name, 'sha256': digest, 'signature': 'ad-hoc; not Developer ID',
                'notarized': False, 'interactive_install_tested': False, 'status': 'automated checks passed'}
    (logs / 'macos-build.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(dmg)


if __name__ == '__main__':
    main()
