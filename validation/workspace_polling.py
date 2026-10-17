"""Native automatic polling checks; synthetic transitions never launch real jobs."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'libexec'))
from docking_universal.application import StudyController
from docking_universal.models import ArtifactRecord, CompletionStatus, Job, JobStatus
from docking_universal.state import JsonStudyStore
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.gui.desktop import StudyWindow
from PyQt6.QtTest import QTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--read-only-study-root', type=Path)
    parser.add_argument('--read-only-study-id')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    results = {'checks': []}
    windows = []
    def check(name, condition):
        results['checks'].append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = JsonStudyStore(root / 'state')
        StudyController(store).create_study('polling', 'Isolated polling fixture — no calculation')
        state = store.load('polling')
        state.selected_pocket_ids = ['P1']
        state.jobs = [Job('fixture-report', 'final_report', JobStatus.RUNNING,
            started_at=(datetime.now(timezone.utc) - timedelta(seconds=6)).isoformat(),
            progress_message='Rendering report figures…')]
        state.completion_status = CompletionStatus.RUNNING
        store.save(state)
        settings = QtCore.QSettings(str(root / 'window.ini'), QtCore.QSettings.Format.IniFormat)
        window = StudyWindow(store, 'polling', settings=settings)
        windows.append(window)
        try:
            window.show()
            QTest.qWait(150)
            check('show starts automatic 1-second polling', window.refresh_timer.isActive()
                  and window.refresh_timer.interval() == 1000)
            check('running fixture shows activity and actual phase', window.running_indicator.isVisibleTo(window)
                  and 'Rendering report figures' in window.feedback_text.text())
            initial_elapsed = window.running_elapsed.text()
            original = store.path_for('polling').read_bytes()
            QTest.qWait(1100)
            check('elapsed advances without an authoritative state change', window.running_elapsed.text() != initial_elapsed)
            check('polling does not write authoritative state', store.path_for('polling').read_bytes() == original)
            state = store.load('polling')
            state.jobs[-1].progress_message = 'Writing the final PDF report…'
            store.save(state)
            QTest.qWait(1100)
            check('phase update is observed without manual refresh', 'Writing the final PDF' in window.feedback_text.text())
            window.grab().save(str(args.output / 'running-phase.png'))
            bundle, report = root / 'fixture.duprotocol', root / 'fixture.pdf'
            bundle.write_text('Synthetic bundle availability fixture; not a real protocol')
            report.write_text('Synthetic report availability fixture; not a real report')
            state = store.load('polling')
            state.jobs[-1].status = JobStatus.COMPLETED
            state.completion_status = CompletionStatus.COMPLETED
            state.artifacts = [ArtifactRecord('bundle', 'protocol_bundle', str(bundle)),
                               ArtifactRecord('report', 'final_report', str(report))]
            store.save(state)
            original = store.path_for('polling').read_bytes()
            QTest.qWait(1100)
            check('completion is observed automatically and clears the moving bar',
                  window.state.revision == state.revision and not window.running_indicator.isVisibleTo(window)
                  and 'Status: completed' in window.summary.text())
            check('saved output actions become enabled', window.open_final_report_button.isEnabled()
                  and window.open_bundle_location_button.isEnabled())
            check('completion observation never regenerates or mutates the study', store.path_for('polling').read_bytes() == original)
            window.grab().save(str(args.output / 'completed.png'))
            window.hide()
            QTest.qWait(1100)
            check('hidden workspace stops polling', not window.refresh_timer.isActive())
            window.show()
            QTest.qWait(100)
            check('reshown workspace restarts polling', window.refresh_timer.isActive())
            state = store.load('polling')
            state.jobs[-1].status = JobStatus.FAILED
            state.jobs[-1].error = 'Synthetic renderer failure — fixture only'
            state.completion_status = CompletionStatus.FAILED
            state.artifacts = []
            store.save(state)
            QTest.qWait(1100)
            check('failure is observed automatically instead of showing endless activity',
                  not window.running_indicator.isVisibleTo(window) and 'Synthetic renderer failure' in window.feedback_text.text())
            window.close()
            if args.read_only_study_root:
                class ReadOnlyStore(JsonStudyStore):
                    def save(self, *a, **kw):
                        raise AssertionError('Read-only validation cannot save the real study')
                    def update(self, *a, **kw):
                        raise AssertionError('Read-only validation cannot update the real study')
                real_store = ReadOnlyStore(args.read_only_study_root)
                path = real_store.path_for(args.read_only_study_id)
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                real_window = StudyWindow(real_store, args.read_only_study_id, settings=settings)
                windows.append(real_window)
                real_window.show()
                QTest.qWait(1100)
                latest = real_store.load(args.read_only_study_id)
                check('real retained completed study opens at its authoritative revision',
                      real_window.state.revision == latest.revision
                      and latest.completion_status == CompletionStatus.COMPLETED
                      and not real_window.running_indicator.isVisibleTo(real_window))
                real_window.grab().save(str(args.output / 'real-study-read-only.png'))
                real_window.close()
                check('real study bytes are unchanged', hashlib.sha256(path.read_bytes()).hexdigest() == before)
        except Exception as exc:
            results['error'] = str(exc)
        finally:
            # Make only the disposable fixture terminal before closing it.
            state = store.load('polling')
            if state.active_job:
                state.active_job.status = JobStatus.COMPLETED
                store.save(state)
            for widget in windows:
                widget.close()
    (args.output / 'verification.json').write_text(json.dumps(results, indent=2))
    return 1 if results.get('error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
