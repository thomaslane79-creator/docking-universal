#!/usr/bin/env python3
"""Declared sequential diagnostic matrix; never retries or installs binaries."""
import json
from pathlib import Path
import subprocess
import sys
from autodock_gpu_trial import check_idle, digest, save


def main():
    root = Path(__file__).resolve().parent / "runs/autodock-gpu-mac-20261016"
    manifest = root / "repro-series.json"
    if manifest.exists():
        raise RuntimeError("Series manifest exists: no duplicate/restart allowed")
    plan = [
        ("repro-strict", "source-strict/bin/adgpu_strict_128", "ad"),
        ("repro-one-workitem", "source-diagnostic/bin/adgpu_diagnostic_1", "ad"),
        ("repro-candidate-short", "source-candidate/bin/adgpu_candidate_128", "focused"),
        ("repro-official-full", "tools/adgpu-v1.6_macos_aarch64_ocl_128wi", "full"),
        ("repro-candidate-full", "source-candidate/bin/adgpu_candidate_128", "full"),
        ("repro-candidate-default", "source-candidate/bin/adgpu_candidate_128", "default"),
    ]
    state = {"status": "running", "harness_sha256": digest(__file__), "production_changed": False, "arms": []}
    save(manifest, state)
    try:
        for name, binary, phase in plan:
            check_idle()
            cmd = [sys.executable, str(Path(__file__).with_name("autodock_gpu_repro.py")),
                   "--pilot", str(root / "pilot"), "--engine", str(root / binary),
                   "--out", str(root / name), "--phase", phase]
            row = {"name": name, "command": cmd, "status": "running"}
            state["arms"].append(row)
            with (root / (name + ".coordinator.log")).open("w") as log:
                child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
                row["pid"] = child.pid
                save(manifest, state)
                row["returncode"] = child.wait()
            result = json.loads((root / name / "summary.json").read_text())
            if row["returncode"] or result["status"] != "completed_diagnostic_not_production_acceptance":
                raise RuntimeError(f"{name} failed: {result.get('error', row['returncode'])}")
            row["status"] = "completed"
            save(manifest, state)
        state["status"] = "completed_diagnostic_not_production_acceptance"
    except BaseException as error:
        state.update(status="failed", error=str(error))
        raise
    finally:
        save(manifest, state)


if __name__ == "__main__":
    main()
