"""Small presentation and settings-path differences between desktop platforms."""
import os
from pathlib import Path
import sys

UI_FONT = 'Helvetica Neue' if sys.platform == 'darwin' else 'Segoe UI'


def recent_jobs_path():
    if sys.platform == 'darwin':
        root = Path.home() / 'Library' / 'Application Support'
    elif sys.platform == 'win32':
        root = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))
    else:
        root = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local' / 'state')))
    return root / 'TwinFinder' / 'recent.json'
