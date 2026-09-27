import tempfile
import unittest
from pathlib import Path

from docking_universal.pocket_engines import (
    available_pocket_modes, build_p2rank_fpocket_rescore_plan,
    build_p2rank_prediction_command, discover_pocket_engines,
    merge_pocket_evidence, parse_p2rank_predictions, parse_p2rank_rescoring,
)


class PocketEngineTests(unittest.TestCase):
    def test_discovery_is_capability_driven_and_requires_java_for_p2rank(self):
        found = {"fpocket": "/tools/fpocket", "prank": "/tools/prank", "java": "/jre/java"}
        result = discover_pocket_engines(which=lambda name: found.get(name), environment={})
        self.assertEqual(result["fpocket"].status, "available")
        self.assertEqual(result["p2rank"].status, "available")
        no_java = discover_pocket_engines(which=lambda name: found.get(name) if name != "java" else None, environment={})
        self.assertEqual(no_java["p2rank"].status, "unavailable")
        self.assertEqual(no_java["p2rank"].detail, "Java runtime not found")
        modes = available_pocket_modes(no_java)
        self.assertFalse(next(item for item in modes if item["id"] == "p2rank")["available"])
        self.assertTrue(next(item for item in modes if item["id"] == "fpocket")["available"])
        self.assertEqual(modes[0]["id"], "p2rank")
        self.assertEqual(modes[0]["policy_role"], "primary")
        self.assertEqual(modes[1]["policy_role"], "fallback")

    def test_p2rank_only_command_does_not_require_fpocket(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher, receptor = root / "prank.bat", root / "receptor.pdb"
            launcher.write_text("launcher\n"); receptor.write_text("ATOM\n")
            command = build_p2rank_prediction_command(launcher, receptor, root / "output")
            self.assertEqual(command[1:3], ("predict", "-f"))
            self.assertNotIn("fpocket", " ".join(command).lower())

    def test_p2rank_csv_is_normalized_without_automatic_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "target.pdb_predictions.csv"
            path.write_text(
                "name,rank,score,probability,center_x,center_y,center_z,residue_ids\n"
                "pocket1,1,12.4,0.91,1.0,2.0,3.0,A_10 A_14\n"
            )
            record = parse_p2rank_predictions(path)[0]
            self.assertEqual(record["candidate_id"], "p2rank:pocket1")
            self.assertEqual(record["center_angstrom"], [1.0, 2.0, 3.0])
            self.assertFalse(record["automation_eligible"])
            self.assertNotIn("selected", record)

    def test_engines_remain_independent_evidence_layers(self):
        merged = merge_pocket_evidence(
            [{"engine": "fpocket", "engine_score": 2.0}],
            [{"engine": "p2rank", "engine_score": 0.8}],
        )
        self.assertEqual([item["engine"] for item in merged], ["fpocket", "p2rank"])
        self.assertEqual([item["engine_score"] for item in merged], [2.0, 0.8])

    def test_fpocket_rescore_plan_and_output_preserve_both_ranks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("prank", "receptor.pdb", "receptor_out.pdb"):
                (root / name).write_text("fixture\n")
            plan = build_p2rank_fpocket_rescore_plan(
                root / "prank", root / "receptor.pdb", root / "receptor_out.pdb", root / "rescore",
            )
            self.assertEqual(plan.command[1], "rescore")
            self.assertIn("PARAM.PREDICTION_METHOD=fpocket", plan.dataset.read_text())
            output = root / "rescore/receptor.pdb_rescored.csv"
            output.write_text("name,score,rank,old_rank,change\npocket7,8.5,1,7,6\n")
            item = parse_p2rank_rescoring(output)[0]
            self.assertEqual(item["candidate_id"], "fpocket:P7")
            self.assertEqual(item["original_fpocket_rank"], 7)
            self.assertEqual(item["p2rank_rank"], 1)
            self.assertFalse(item["automation_eligible"])
