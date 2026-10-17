"""Native phase-polling acceptance with disposable state; no scientific jobs."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'libexec'))
from docking_universal.application import StudyController
from docking_universal.models import CompletionStatus, Job, JobStatus
from docking_universal.state import JsonStudyStore
from docking_universal.screening_progress import write_screening_progress
from docking_universal.stage_feedback import screening_feedback
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.gui.desktop import StudyWindow
from PyQt6.QtTest import QTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    result = {'checks': [], 'basis': 'Synthetic phase fixtures, not real docking results'}

    def check(name, passed):
        result['checks'].append({'name': name, 'passed': bool(passed)})
        if not passed:
            raise AssertionError(name)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        output = root / 'screen'
        compound = output / 'compounds/amine'
        compound.mkdir(parents=True)
        store = JsonStudyStore(root / 'state')
        StudyController(store).create_study('feedback', 'Isolated screening feedback — no docking')
        state = store.load('feedback')
        state.completion_status = CompletionStatus.RUNNING
        state.jobs = [Job('fixture', 'screening', JobStatus.RUNNING,
                          started_at=datetime.now(timezone.utc).isoformat())]
        store.save(state)
        settings = QtCore.QSettings(str(root / 'ui.ini'), QtCore.QSettings.Format.IniFormat)
        window = StudyWindow(store, 'feedback', settings=settings)
        try:
            window.resize(1100, 850)
            window.show()
            QTest.qWait(150)
            write_screening_progress(output, 'compound', 'Starting…', compound_id='amine',
                                     compound_name='Example amine', compound_index=1, compound_total=2)
            for phase, message in (
                    ('ligands', 'Preparing protonation/tautomer states at pH 6.5 and starting conformers…'),
                    ('docking', 'Docking site 2/2, repeat 1/5 (seed 101)…'),
                    ('interactions', 'Calculating PLIP contacts and drawing 2D interactions…')):
                write_screening_progress(compound, phase, message)
                feedback = screening_feedback(output, 30)
                state = store.load('feedback')
                job = state.jobs[-1]
                job.progress_phase, job.progress_message, job.progress_completed, job.progress_total = feedback
                store.save(state)
                QTest.qWait(1150)
                check(f'{phase}: automatic polling shows phase', message in window.feedback_text.text())
                check(f'{phase}: compound identified', 'Compound 1/2: Example amine' in window.screening_status.text())
                check(f'{phase}: activity remains visible', window.running_indicator.isVisibleTo(window))
                window.grab().save(str(args.output / f'{phase}.png'))
            state = store.load('feedback')
            state.jobs[-1].status = JobStatus.FAILED
            state.jobs[-1].error = 'Synthetic worker failure — validation only'
            state.completion_status = CompletionStatus.FAILED
            store.save(state)
            QTest.qWait(1150)
            check('terminal failure overrides the last milestone', 'Synthetic worker failure' in window.feedback_text.text())
            check('failure clears moving bar', not window.running_indicator.isVisibleTo(window))
            check('no scientific subprocess launched', all(job.process_id is None for job in store.load('feedback').jobs))
        except Exception as exc:
            result['error'] = str(exc)
        finally:
            state = store.load('feedback')
            state.jobs[-1].status = JobStatus.COMPLETED
            store.save(state)
            window.close()
    (args.output / 'verification.json').write_text(json.dumps(result, indent=2))
    return 1 if result.get('error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
