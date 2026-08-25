#!/usr/bin/env python3
"""Cross-platform graphical file/folder chooser with a headless fallback signal."""

import argparse
import os
import platform
import shutil
import subprocess
from pathlib import Path


def executable(env_name, command):
    override = os.environ.get(env_name)
    if override:
        return override if Path(override).is_file() else shutil.which(override)
    return shutil.which(command)


def backend():
    system = platform.system()
    if system == "Darwin" and executable("DOCKING_UNIVERSAL_OSASCRIPT", "osascript"):
        return "Finder"
    if system == "Linux" and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        if executable("DOCKING_UNIVERSAL_ZENITY", "zenity"):
            return "Zenity"
        try:
            import tkinter as tk
        except ImportError:
            return None
        try:
            probe = tk.Tk(); probe.withdraw(); probe.destroy()
            return "Tk"
        except tk.TclError:
            return None
    return None


def choose(prompt, folder=False, sdf=False):
    selected_backend = backend()
    if selected_backend == "Finder":
        command = executable("DOCKING_UNIVERSAL_OSASCRIPT", "osascript")
        chooser = "choose folder" if folder else "choose file"
        script = f'POSIX path of ({chooser} with prompt "{prompt}")'
        result = subprocess.run([command, "-e", script], text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise SystemExit("Graphical file selection cancelled")
        selected_text = result.stdout.strip()
    elif selected_backend == "Zenity":
        command = [executable("DOCKING_UNIVERSAL_ZENITY", "zenity"), "--file-selection", f"--title={prompt}"]
        if folder:
            command.append("--directory")
        if sdf:
            command.extend(["--file-filter=SDF files | *.sdf", "--file-filter=All files | *"])
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise SystemExit("Graphical file selection cancelled")
        selected_text = result.stdout.strip()
    elif selected_backend == "Tk":
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw()
        try:
            root.attributes("-topmost", True)
            if folder:
                selected_text = filedialog.askdirectory(title=prompt, mustexist=True)
            else:
                filetypes = [("SDF files", "*.sdf"), ("All files", "*")] if sdf else [("All files", "*")]
                selected_text = filedialog.askopenfilename(title=prompt, filetypes=filetypes)
        finally:
            root.destroy()
        if not selected_text:
            raise SystemExit("Graphical file selection cancelled")
    else:
        raise SystemExit("Graphical file selection is unavailable")

    selected = Path(selected_text).expanduser().resolve()
    if folder and not selected.is_dir():
        raise SystemExit(f"Selection is not a readable folder: {selected}")
    if not folder and not selected.is_file():
        raise SystemExit(f"Selection is not a readable file: {selected}")
    if sdf and selected.suffix.lower() != ".sdf":
        raise SystemExit(f"Selected ligand file must end in .sdf: {selected}")
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--available", action="store_true")
    parser.add_argument("--label", action="store_true")
    parser.add_argument("--prompt", default="Choose a file")
    parser.add_argument("--folder", action="store_true")
    parser.add_argument("--sdf", action="store_true")
    args = parser.parse_args()
    selected_backend = backend()
    if args.available:
        raise SystemExit(0 if selected_backend else 1)
    if args.label:
        print(selected_backend or "terminal path entry")
        return
    print(choose(args.prompt, folder=args.folder, sdf=args.sdf))


if __name__ == "__main__":
    main()
