#!/usr/bin/env python3
"""Regression tests for report reuse of retained scientific artifacts."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIGURES = load("docking_universal_report_figures", "libexec/docking-universal-report-figures.py")
REPORT = load("docking_universal_pdf_report", "libexec/docking-universal-pdf-report.py")


class RetainedReportArtifactTests(unittest.TestCase):
    def test_retained_plip_calls_use_internal_renderer_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(FIGURES, "render_sdf_plip2d", return_value=True) as internal,
                patch.object(FIGURES.subprocess, "run") as run,
            ):
                rendered = FIGURES.render_plip2d(
                    root / "interactions",
                    root / "ligand.sdf",
                    root / "diagram.png",
                    root / "plip_to_2d.py",
                    ligand_id="LIG:A:1",
                )
        self.assertTrue(rendered)
        internal.assert_called_once()
        run.assert_not_called()

    def test_existing_control_clusters_are_reused_without_reclustering(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory)
            analysis = control / "report" / "control_pose_analysis"
            analysis.mkdir(parents=True)
            (analysis / "cluster_summary.csv").write_text("energy_rank,cluster_id\n1,1\n")
            with patch.object(FIGURES.subprocess, "run") as run:
                selected = FIGURES.ensure_control_clusters(control, control / "protocol.json")
        self.assertEqual(selected, analysis)
        run.assert_not_called()

    def test_only_nonempty_cluster_results_mark_a_study_as_docked(self):
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory)
            analysis = study / "compounds" / "ligand" / "pose_analysis"
            analysis.mkdir(parents=True)
            clusters = analysis / "cluster_summary.csv"
            self.assertFalse(REPORT.has_retained_docking_results(study))
            clusters.write_text("")
            self.assertFalse(REPORT.has_retained_docking_results(study))
            clusters.write_text("energy_rank,cluster_id\n1,1\n")
            self.assertTrue(REPORT.has_retained_docking_results(study))


if __name__ == "__main__":
    unittest.main()
