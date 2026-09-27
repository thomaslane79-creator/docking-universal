"""Approved, package-local Docking Universal branding assets."""

from __future__ import annotations

from pathlib import Path


_BRANDING_ROOT = Path(__file__).resolve().parent / "assets" / "branding"


def application_icon_path() -> Path:
    """Return the flat simplified full-color application icon."""

    return _BRANDING_ROOT / "docking-universal-app-icon.png"
