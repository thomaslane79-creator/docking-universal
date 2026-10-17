"""Verify that real Reduce2's cell-less translation is rejected, not accepted."""
import json
import os
from pathlib import Path
import subprocess

from autodock_gpu_trial import ROOT, digest


def main():
    run = ROOT / "validation/runs/reduce2-frame-fix-installed-20261017"
    out = run / "missing-cell-guard"
    out.mkdir(exist_ok=False)
    runtime = Path("/opt/anaconda3/envs/docking-universal/libexec/docking-universal")
    original = run / "pdb/2R8N_receptor_prep/receptor/2R8N_filtered.pdb"
    original_sha = digest(original)
    source = out / "2R8N_no_cell.pdb"
    source.write_text("\n".join(line for line in original.read_text().splitlines()
                                if not line.startswith(("CRYST1", "SCALE", "ORIGX"))) + "\n")
    output, audit, log = out / "accepted.pdb", out / "audit.json", out / "reduce2.log"
    env = dict(os.environ, DOCKING_UNIVERSAL_GEOSTD=str(runtime / "docking_universal/data/geostd"))
    process = subprocess.run(["/opt/anaconda3/envs/docking-universal/bin/python",
                              str(runtime / "docking-universal-reduce2-receptor.py"),
                              str(source), str(output), str(audit), str(log)],
                             env=env, capture_output=True, text=True)
    record = json.loads(audit.read_text())
    assert process.returncode == 2 and record["status"] == "incompatible"
    assert record["coordinate_frame"]["status"] == "changed"
    assert record["input_heavy_atom_count"] == record["output_heavy_atom_count"] == 754
    assert not output.exists() and digest(original) == original_sha
    summary = {"status": "passed", "process_returncode": process.returncode,
               "meaning": "Real cell-less Reduce2 output moved the backbone and was refused; no shifted receptor was published",
               "audit": str(audit), "coordinate_frame": record["coordinate_frame"], "scientific_docking_searches": 0}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
