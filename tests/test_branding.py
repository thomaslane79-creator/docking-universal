from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from docking_universal.gui.branding import application_icon_path


def test_application_icon_is_packaged_simplified_asset():
    icon = application_icon_path()

    assert icon.name == "docking-universal-app-icon.png"
    assert icon.is_file()
    assert icon.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert icon.stat().st_size > 10_000
