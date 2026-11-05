"""Render GUI teaching surfaces with private fixtures; never start scientific work.

Optionally load earlier GUI modules to measure visible text with the same data.
This complements native viewer acceptance; synthetic tables are layout evidence,
not docking results. The supplied mmCIF, if any, is read-only and hash checked.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-gui', type=Path)
    parser.add_argument('--structure', type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'libexec'))
    import docking_universal.gui
    if args.baseline_gui:
        docking_universal.gui.__path__ = [str(args.baseline_gui)]
    from docking_universal.gui.qt import QtCore, QtGui, QtWidgets
    from docking_universal.gui.workflow_panels import (
        StudySetupPanel, PreparationProgressPanel, ProtocolFinalizationPanel,
        ScreeningSetupPanel, ProtocolImportDialog,
    )
    from docking_universal.gui.results_review import ResultsReviewPanel
    from docking_universal.gui.pocket_evidence import PocketEvidencePanel
    from docking_universal.gui.receptor_model_review import ReceptorModelReviewDialog
    from docking_universal.gui.study_launcher import StudyLauncherDialog
    from docking_universal.gui.decision_dialog import DecisionDialog
    from docking_universal.decisions import DecisionRequired, DecisionOption
    from docking_universal.state import JsonStudyStore
    from docking_universal.services.coordinate_evidence import read_coordinate_evidence
    from PyQt6.QtTest import QTest

    args.output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    result = {'baseline': bool(args.baseline_gui), 'surfaces': [], 'checks': []}
    rendered_windows = []  # Keep owners alive while checking their passive values.
    before = hashlib.sha256(args.structure.read_bytes()).hexdigest() if args.structure else None

    def check(name, passed):
        result['checks'].append({'name': name, 'passed': bool(passed)})
        if not passed:
            raise AssertionError(name)

    def words(panel):
        document = QtGui.QTextDocument()
        text = []
        for widget in panel.findChildren(QtWidgets.QWidget):
            if (widget.window() == panel.window() and widget.isVisibleTo(panel)
                    and isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton))):
                document.setHtml(widget.text())
                text.append(document.toPlainText())
        return len(' '.join(text).split())

    def capture(name, panel, *, dialog=False):
        if dialog:
            window, scroll = panel, None
        else:
            window = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(window)
            layout.addWidget(QtWidgets.QLabel(name.replace('-', ' ').title()))
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(panel)
            layout.addWidget(scroll)
        window.setWindowTitle('GUI text review — private display fixture')
        rendered_windows.append(window)
        try:
            for width in (960, 1280):
                window.resize(width, 800)
                window.show()
                QTest.qWait(80)
                if scroll:
                    check(f'{name}/{width}: no horizontal scroll', scroll.horizontalScrollBar().maximum() == 0)
                # Detailed evidence viewports intentionally scroll. Teaching
                # labels should fit completely without manual scrolling.
                for note in panel.findChildren(QtWidgets.QLabel):
                    if note.isVisibleTo(panel) and note.wordWrap() and note.minimumHeight() != note.maximumHeight():
                        needed = note.heightForWidth(note.width())
                        check(f'{name}/{width}: {note.objectName() or "label"} fits', needed <= note.height() + 4)
                result['surfaces'].append({'name': name, 'width': width,
                    'visible_label_button_words': words(panel),
                    'panel_size_hint_height': panel.sizeHint().height(),
                    'vertical_scroll': scroll.verticalScrollBar().maximum() if scroll else None})
                window.grab().save(str(args.output / f'{name}-{width}.png'))
        finally:
            window.close()

    try:
        with TemporaryDirectory(prefix='du-gui-text-') as directory:
            root = Path(directory)
            setup = StudySetupPanel()
            setup.output_directory.setText('/example/study')
            if args.structure:
                setup.input_pdb.setText(str(args.structure))
                setup.set_coordinate_evidence(read_coordinate_evidence(args.structure))
            capture('study-setup', setup)
            preparation = PreparationProgressPanel()
            capture('preparation', preparation)
            final = ProtocolFinalizationPanel()
            final.output_directory.setText('/example/protocol')
            capture('protocol-settings', final)
            screen = ScreeningSetupPanel()
            screen.ligands.setText('/example/compounds.sdf')
            screen.output.setText('/example/screen')
            capture('screening', screen)
            evidence = PocketEvidencePanel()
            evidence.set_viewer_presentation(embedded=True)
            evidence.set_candidate({'id': 'P1', 'evidence': {
                'experimental_ligand_evidence': {'observation_count': 2, 'pdb_entry_count': 1},
                'conformational_site_evidence': {'status': 'conformationally_incompatible',
                    'occluding_residues': [{'name': 'ASP', 'chain': 'A', 'number': '30'}]},
            }})
            evidence.set_lookup_status({'mode': 'off', 'status': 'not_requested'})
            capture('site-evidence', evidence)
            capture('results', ResultsReviewPanel({'status': 'available', 'missing': []}))
            capture('protocol-import', ProtocolImportDialog({
                'target': 'Display fixture', 'protocol_type': 'site-guided-exploratory',
                'region_count': 2, 'engine': 'vina', 'parameters': {},
                'exploratory_authorization_required': True, 'verified_files': 8,
            }), dialog=True)
            review = ReceptorModelReviewDialog({'residue_inventory': [{
                'resname': 'ASN', 'chain': 'A', 'number': '10', 'insertion_code': '',
                'label': 'ASN A:10', 'missing_backbone_atom_names': [],
                'alternate_locations': [{'altloc': 'A', 'occupancy_min': .6, 'occupancy_max': .6},
                                        {'altloc': 'B', 'occupancy_min': .4, 'occupancy_max': .4}],
            }]}, lambda _: (_ for _ in ()).throw(AssertionError('No preparation allowed')))
            capture('receptor-review', review, dialog=True)
            check('model approval remains disabled', not review.prepare_button.isEnabled())
            decision = DecisionRequired(id='display-fixture', kind='select_pockets',
                prompt='Choose docking regions', detected='Two candidates retained',
                why_stopped='The selected regions define the searched space.',
                consequences=('Approved geometry is recorded.',),
                options=(DecisionOption('P1', 'Pocket 1', 'Search the first region'),
                         DecisionOption('P2', 'Pocket 2', 'Search the second region')),
                presentation={'guided': '<p>Compare the retained evidence before choosing.</p>'})
            settings = QtCore.QSettings(str(root / 'settings.ini'), QtCore.QSettings.Format.IniFormat)
            decision_window = DecisionDialog(decision, settings=settings, allow_approval=True)
            capture('decision-review', decision_window, dialog=True)
            check('decision reading selects nothing', not decision_window.selected_values())
            capture('study-launcher', StudyLauncherDialog(JsonStudyStore(root / 'studies'), None, mode='create'), dialog=True)
            check('no exploratory approvals', not final.approval.isChecked() and not screen.approval.isChecked())
            if args.structure:
                check('source coordinates unchanged', before == hashlib.sha256(args.structure.read_bytes()).hexdigest())
    except Exception as exc:
        result['error'] = str(exc)
    (args.output / 'verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({'surfaces': len(result['surfaces']), 'checks': len(result['checks']),
                      'error': result.get('error')}))
    return 1 if result.get('error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
