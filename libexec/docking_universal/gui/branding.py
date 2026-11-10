"""Approved, package-local Docking Universal branding assets."""

from __future__ import annotations

from pathlib import Path
import sys


_BRANDING_ROOT = Path(__file__).resolve().parent / "assets" / "branding"


def application_icon_path() -> Path:
    """Return the flat simplified full-color application icon."""

    return _BRANDING_ROOT / "docking-universal-app-icon.png"


def set_windows_application_identity() -> None:
    """Give Windows a distinct taskbar group before Qt creates any windows."""
    if sys.platform == 'win32':
        import ctypes
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        shell.SetCurrentProcessExplicitAppUserModelID('DockingUniversal.Desktop.1')
