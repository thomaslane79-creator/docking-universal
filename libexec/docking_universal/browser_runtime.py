"""Discover an already installed local Chromium-family browser without downloads."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil


def find_chromium(explicit=None, *, environment=None, which=shutil.which, system=None):
    values = os.environ if environment is None else environment
    selected = explicit or values.get('DOCKING_UNIVERSAL_CHROME')
    candidates = [selected] if selected else [which(name) for name in (
        'google-chrome', 'chromium', 'chromium-browser', 'chrome', 'msedge', 'microsoft-edge')]
    system = platform.system() if system is None else system
    if not selected and system == 'Darwin':
        candidates += ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                       '/Applications/Chromium.app/Contents/MacOS/Chromium',
                       '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge']
    elif not selected and system == 'Windows':
        for name in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
            # Windows environment variables are case-insensitive in os.environ;
            # ordinary mappings in tests may preserve their familiar spelling.
            folder = next((v for k, v in values.items() if k.upper() == name), None)
            if folder:
                candidates += [str(Path(folder) / 'Google/Chrome/Application/chrome.exe'),
                               str(Path(folder) / 'Microsoft/Edge/Application/msedge.exe')]
    return next((Path(item).expanduser().resolve() for item in candidates
                 if item and Path(item).expanduser().is_file()), None)
