"""Run the established GUI interaction contracts with real Qt, without PyMOL/GPU.

Used by make test-gui and the native-host CI matrix. Native rendering and window
acceptance remain separate: these tests use offscreen Qt and adapter fixtures.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'libexec'), str(ROOT)]


def main():
    # Fail before collection rather than silently skipping an absent GUI runtime.
    from docking_universal.gui.qt import QtWidgets
    import gemmi, rdkit, PIL, reportlab  # Required fixture/rendering dependencies.
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    modules = (
        'test_pocket_sites', 'test_active_study_session', 'test_desktop_workspace',
        'test_pocket_plot', 'test_pocket_evidence', 'test_study_viewer',
        'test_linked_pose_review', 'test_cluster_contacts',
        'test_embedded_pymol_adapter', 'test_protocol_finalization',
    )
    suite = unittest.defaultTestLoader.loadTestsFromNames(['tests.' + name for name in modules])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    app.processEvents()
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
