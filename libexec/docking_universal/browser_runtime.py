"""Discover an already installed local Chromium-family browser without downloads."""
from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess


def private_chromium(prefix):
    """Use only a registered browser inside this application's owned cache."""
    prefix = Path(prefix).resolve()
    try:
        record = json.loads((prefix / 'share/docking-universal/renderer-browser.json').read_text())
        path = Path(record['executable']).resolve()
        path.relative_to(prefix / 'share/playwright-browsers')
        if (record.get('schema') != 'docking-universal-renderer-browser-v1'
                or hashlib.sha256(path.read_bytes()).hexdigest() != record['executable_sha256']):
            return None
        return path
    except (OSError, ValueError, KeyError, TypeError):
        return None


def register_private_chromium(prefix, executable, playwright_version):
    prefix, executable = Path(prefix).resolve(), Path(executable).resolve()
    executable.relative_to(prefix / 'share/playwright-browsers')
    version = subprocess.check_output([str(executable), '--version'], text=True, timeout=15).strip()
    record = {'schema': 'docking-universal-renderer-browser-v1', 'executable': str(executable),
              'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
              'browser_version': version, 'playwright_version': str(playwright_version),
              'source': 'Chromium revision selected by the installed pinned Playwright package',
              'network_used_for_dependency_download': True, 'structures_uploaded': False}
    target = prefix / 'share/docking-universal/renderer-browser.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.partial')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(target)
    return record


def find_chromium(explicit=None, *, environment=None, which=shutil.which, system=None):
    values = os.environ if environment is None else environment
    selected = explicit or values.get('DOCKING_UNIVERSAL_CHROME')
    candidates = [selected] if selected else [which(name) for name in (
        'google-chrome', 'chromium', 'chromium-browser', 'chrome', 'msedge', 'microsoft-edge')]
    if not selected:
        prefixes = []
        scientific_python = values.get('DOCKING_UNIVERSAL_PYTHON')
        if scientific_python:
            executable = Path(scientific_python).resolve()
            prefixes.append(executable.parent.parent if executable.parent.name in {'bin', 'Scripts'} else executable.parent)
        prefixes += [p for p in Path(__file__).resolve().parents if (p / 'conda-meta').is_dir()]
        if values.get('CONDA_PREFIX'):
            prefixes.append(Path(values['CONDA_PREFIX']))
        for prefix in dict.fromkeys(prefixes):
            browser = private_chromium(prefix)
            if browser is not None:
                candidates.insert(0, str(browser))
                break
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


def install_private_chromium(prefix, renderer):
    """Installer-only dependency acquisition, using the exact installed package."""
    prefix, renderer = Path(prefix).resolve(), Path(renderer).resolve()
    if not (prefix / 'conda-meta').is_dir():
        raise ValueError('An explicit Conda installation prefix is required')
    existing = find_chromium()
    if existing is not None:
        return {'source': 'existing_local', 'executable': str(existing)}
    node = prefix / ('node.exe' if os.name == 'nt' else 'bin/node')
    package = renderer / 'node_modules/playwright'
    version = json.loads((package / 'package.json').read_text())['version']
    wanted = json.loads((renderer / 'package.json').read_text())['dependencies']['playwright']
    if version != wanted:
        raise ValueError('Installed Playwright differs from the pinned renderer package')
    environment = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(prefix / 'share/playwright-browsers'))
    subprocess.run([str(node), str(package / 'cli.js'), 'install', 'chromium', '--no-shell', '--no-remove'],
                   env=environment, check=True)
    path = subprocess.check_output([str(node), '-e',
        'process.stdout.write(require(process.argv[1]).chromium.executablePath())', str(package)],
        env=environment, text=True).strip()
    return register_private_chromium(prefix, path, version)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Install the pinned local diagram browser when no local browser is available.')
    parser.add_argument('--install-private', type=Path, required=True)
    parser.add_argument('--renderer-root', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install_private_chromium(args.install_private, args.renderer_root), indent=2))
