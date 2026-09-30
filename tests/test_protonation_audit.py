import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "libexec" / "docking-universal-protonate-receptor.py"


def _pdb(path: Path, residue: str = "ALA", atom_name: str = "CA") -> None:
    path.write_text(
        f"ATOM      1  N   {residue} A   1       0.000   0.000   0.000  1.00 20.00           N\n"
        f"ATOM      2  {atom_name:<4}{residue:>3} A   1       1.500   0.000   0.000  1.00 20.00           C\n"
        "END\n"
    )


def _run(source: Path, output: Path) -> tuple[int, dict]:
    audit = output.with_suffix(".json")
    pqr = output.with_suffix(".pqr")
    log = output.with_suffix(".log")
    result = subprocess.run(
        [sys.executable, str(HELPER), str(source), str(output), str(pqr), str(audit), str(log), "--command", "/usr/bin/true"],
        check=False, capture_output=True, text=True,
    )
    return result.returncode, json.loads(audit.read_text())


def test_audit_rejects_dropped_heavy_atoms():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "in.pdb"; output = root / "out.pdb"
        _pdb(source)
        output.write_text("ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N\nEND\n")
        code, record = _run(source, output)
        assert code == 2
        assert record["status"] == "incompatible"
        assert record["missing_input_heavy_atoms"]


def test_real_audit_marks_component_identity_change_incompatible():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "in.pdb"; output = root / "out.pdb"
        _pdb(source, residue="CSO")
        _pdb(output, residue="CYS")
        code, record = _run(source, output)
        assert code == 2
        assert record["status"] == "incompatible"
        assert record["missing_input_heavy_atoms"]


def test_reduce2_wrapper_accepts_hydrogen_optimized_model():
    helper = ROOT / "libexec" / "docking-universal-reduce2-receptor.py"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "in.pdb"; output = root / "out.pdb"
        source.write_text(
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N\n"
            "ATOM      2  CA  ALA A   1       1.500   0.000   0.000  1.00 20.00           C\nEND\n"
        )
        fake = root / "reduce2.py"
        fake.write_text(
            "import pathlib, sys\n"
            "p=pathlib.Path(sys.argv[1]); out=p.with_name(p.stem + 'H.pdb')\n"
            "out.write_text(p.read_text() + 'ATOM      3  H   ALA A   1       0.000   0.000   1.000  1.00 20.00           H\\n')\n"
        )
        audit = root / "audit.json"; log = root / "reduce2.log"
        env = dict(__import__("os").environ, REDUCE2_SCRIPT=str(fake), DOCKING_UNIVERSAL_GEOSTD=str(root))
        result = subprocess.run(
            [sys.executable, str(helper), str(source), str(output), str(audit), str(log)],
            env=env, check=False, capture_output=True, text=True,
        )
        record = json.loads(audit.read_text())
        assert result.returncode == 0
        assert record["status"] == "compatible"
        assert record["added_hydrogen_count"] == 1
        assert output.is_file()


def test_reduce2_wrapper_rejects_overprotonated_internal_peptide_nitrogen():
    helper = ROOT / "libexec" / "docking-universal-reduce2-receptor.py"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "in.pdb"; output = root / "out.pdb"
        source.write_text(
            "ATOM      1  C   ALA A   1       0.000   0.000   0.000  1.00 20.00           C\n"
            "ATOM      2  N   CSO A   2       1.330   0.000   0.000  1.00 20.00           N\n"
            "ATOM      3  CA  CSO A   2       2.700   0.000   0.000  1.00 20.00           C\n"
            "END\n"
        )
        fake = root / "reduce2.py"
        fake.write_text(
            "import pathlib, sys\n"
            "p=pathlib.Path(sys.argv[1]); out=p.with_name(p.stem + 'H.pdb')\n"
            "out.write_text(p.read_text() + "
            "'ATOM      4  H   CSO A   2       1.330   1.000   0.000  1.00 20.00           H\\n' + "
            "'ATOM      5 HN2  CSO A   2       1.330  -1.000   0.000  1.00 20.00           H\\n')\n"
        )
        audit = root / "audit.json"; log = root / "reduce2.log"
        env = dict(__import__("os").environ, REDUCE2_SCRIPT=str(fake), DOCKING_UNIVERSAL_GEOSTD=str(root))
        result = subprocess.run(
            [sys.executable, str(helper), str(source), str(output), str(audit), str(log)],
            env=env, check=False, capture_output=True, text=True,
        )
        record = json.loads(audit.read_text())
        assert result.returncode == 2
        assert record["status"] == "incompatible"
        assert record["backbone_nitrogen_hydrogen_conflicts"] == [{
            "residue": "A:2",
            "component": "CSO",
            "backbone_nitrogen_hydrogen_count": 2,
            "hydrogen_atoms": ["H", "HN2"],
            "reason": "internal peptide backbone nitrogen has more than one bonded hydrogen",
        }]
        assert not output.exists()


class ProtonationAuditTests(unittest.TestCase):
    test_dropped_heavy_atoms = staticmethod(test_audit_rejects_dropped_heavy_atoms)
    test_component_identity_change = staticmethod(test_real_audit_marks_component_identity_change_incompatible)
    test_reduce2_hydrogen_optimized_model = staticmethod(test_reduce2_wrapper_accepts_hydrogen_optimized_model)
    test_reduce2_overprotonated_internal_peptide = staticmethod(
        test_reduce2_wrapper_rejects_overprotonated_internal_peptide_nitrogen
    )
