"""Build a Windows one-folder application without changing shell execution policy."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dist',type=Path,default=Path('dist'));p.add_argument('--work',type=Path,default=Path('build'))
    p.add_argument('--debug-console',action='store_true');p.add_argument('--clean',action='store_true')
    a=p.parse_args();root=Path(__file__).resolve().parent
    if os.name!='nt':raise SystemExit('Build the Windows application on Windows.')
    for name in ('encoder.pt','tokenizer.json','base_classifier.json','encoder_manifest.json'):
        if not (root/'models'/name).is_file():raise SystemExit('Missing model file: '+name)
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--console' if a.debug_console else '--windowed',
             '--name','TwinFinder','--distpath',str(a.dist.resolve()),'--workpath',str(a.work.resolve()),'--specpath',str(a.work.resolve()),
             '--add-data',str(root/'models')+';models','--collect-all','tokenizers',
             '--manifest',str(root/'windows.manifest')]
    if a.clean:command.append('--clean')
    for name in ('sentence_transformers','transformers','sklearn','scipy','pandas','matplotlib','pytest','torchvision','torchaudio','IPython','notebook'):
        command+=['--exclude-module',name]
    command.append(str(root/'desktop.py'))
    subprocess.run(command,cwd=root,check=True)
    print(f'Built {a.dist.resolve()/"TwinFinder"/"TwinFinder.exe"}. Distribute the whole TwinFinder folder.')

if __name__=='__main__':main()
