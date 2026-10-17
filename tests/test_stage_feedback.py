import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from docking_universal.stage_feedback import (
    control_feedback, finalization_feedback, preparation_feedback, screening_feedback,
)
from docking_universal.screening_progress import write_screening_progress, read_screening_progress


class StageFeedbackTests(unittest.TestCase):
    def test_preparation_and_finalization_milestones_follow_real_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdb = root / "receptor" / "target.pdb"
            pdbqt = root / "receptor" / "target.pdbqt"
            self.assertEqual(preparation_feedback(root, pdb, pdbqt)[0], "input")
            pdb.parent.mkdir()
            pdb.write_text("ATOM\n")
            self.assertEqual(preparation_feedback(root, pdb, pdbqt)[0], "coordinates")
            pdbqt.write_text("ATOM\n")
            self.assertEqual(preparation_feedback(root, pdb, pdbqt)[0], "receptor")
            cavity = root / "cavity"
            cavity.mkdir()
            (cavity / "target_pocket1.conf").write_text("center_x = 1\n")
            self.assertEqual(preparation_feedback(root, pdb, pdbqt)[0], "pockets")

            protocol = root / "protocol.json"
            report = root / "report.pdf"
            bundle = root / "protocol.duprotocol"
            self.assertEqual(finalization_feedback(protocol, report, bundle)[0], "setup")
            protocol.write_text("{}")
            self.assertEqual(finalization_feedback(protocol, report, bundle)[0], "protocol")
            report.write_text("%PDF")
            self.assertEqual(finalization_feedback(protocol, report, bundle)[0], "report")
            bundle.write_text("bundle")
            self.assertEqual(finalization_feedback(protocol, report, bundle)[0], "bundle")

    def test_screening_distinguishes_docking_from_analysis_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(screening_feedback(root, 2)[0], "ligands")
            docking = root / "compounds" / "ligand" / "seed_1" / "docking"
            docking.mkdir(parents=True)
            (docking / "independent_ensemble_1_vina.pdbqt").write_text("MODEL\n")
            self.assertEqual(screening_feedback(root, 2)[2:], (1, 2))
            (docking / "independent_ensemble_2_vina.pdbqt").write_text("MODEL\n")
            self.assertEqual(screening_feedback(root, 2)[0], "analysis")
            (root / "report").mkdir()
            (root / "report" / "screen.pdf").write_text("%PDF")
            self.assertEqual(screening_feedback(root, 2)[0], "report")

    def test_control_bundle_presence_is_only_a_verification_milestone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(control_feedback(root)[0], "preparation")
            (root / "study_manifest.json").write_text("{}")
            self.assertEqual(control_feedback(root)[0], "assessment")
            (root / "unverified.duprotocol").write_bytes(b"not a bundle")
            self.assertIn("verifying", control_feedback(root)[1])

    def test_screening_worker_phases_include_compound_and_do_not_claim_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compound = root / 'compounds/ligand'
            compound.mkdir(parents=True)
            write_screening_progress(root, 'compound', 'Starting…', compound_id='ligand',
                                     compound_name='Indinavir', compound_index=2, compound_total=4,
                                     failed_compounds=1)
            for phase, message in [('ligands', 'Preparing protonation states at pH 6.5…'),
                                   ('ligand_atoms', 'Preparing docking atoms…'),
                                   ('docking', 'Docking site 2/2, repeat 1/5…'),
                                   ('clustering', 'Grouping poses…'),
                                   ('interactions', 'Calculating PLIP contacts…'),
                                   ('finished', 'Compound processing finished…')]:
                write_screening_progress(compound, phase, message)
                feedback = screening_feedback(root, 30)
                self.assertEqual(feedback[0], phase)
                self.assertIn('Compound 2/4: Indinavir', feedback[1])
                self.assertIn(message, feedback[1])
                self.assertIn('1 earlier compound(s) failed', feedback[1])
                self.assertEqual(feedback[2:], (0, 30) if phase == 'docking' else (None, None))
            write_screening_progress(root, 'report', 'Generating library report…', failed_compounds=1)
            self.assertIn('Generating library report', screening_feedback(root, 30)[1])
            self.assertNotIn('Indinavir', screening_feedback(root, 30)[1])

    def test_multiple_sites_are_counted_and_initial_plan_cannot_prove_all_jobs_finished(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compound = root / 'compounds/ligand'
            for site in (1, 2):
                docking = compound / f'site_{site}/seed_1/docking'
                docking.mkdir(parents=True)
                (docking / 'state_vina.pdbqt').write_text('MODEL\n')
            write_screening_progress(root, 'compound', 'Starting…', compound_id='ligand',
                                     compound_index=1, compound_total=1)
            write_screening_progress(compound, 'docking', 'Docking another chemical state…')
            feedback = screening_feedback(root, 1)
            self.assertEqual(feedback[0], 'docking')
            self.assertIn('files written: 2 (initial plan: 1)', feedback[1])
            self.assertEqual(feedback[2:], (None, None))

    def test_progress_is_atomic_advisory_and_does_not_follow_external_compound_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(write_screening_progress(root / 'absent', 'input', 'Starting…'))
            self.assertFalse((root / 'absent').exists())
            self.assertTrue(write_screening_progress(root, 'input', 'Starting…'))
            before = (root / 'screening_progress.json').read_bytes()
            with patch('docking_universal.screening_progress.os.replace', side_effect=OSError('denied')):
                self.assertFalse(write_screening_progress(root, 'docking', 'New phase…'))
            self.assertEqual((root / 'screening_progress.json').read_bytes(), before)
            self.assertFalse(list(root.glob('.screening-progress-*')))
            self.assertEqual(read_screening_progress(root)['phase'], 'input')
            write_screening_progress(root, 'compound', 'Waiting…', compound_id='../external')
            self.assertEqual(screening_feedback(root, 10)[0], 'compound')
            (root / 'screening_progress.json').write_text('{partial')
            self.assertEqual(read_screening_progress(root), {})
            self.assertEqual(screening_feedback(root, 10)[0], 'ligands')
