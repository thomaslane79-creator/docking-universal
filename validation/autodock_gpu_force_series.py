#!/usr/bin/env python3
"""Run final force probes only after the main diagnostic series exits normally."""
import json
from pathlib import Path
import subprocess
import sys
import time
from autodock_gpu_trial import check_idle, digest, save


def main():
    root = Path(__file__).resolve().parent / "runs/autodock-gpu-mac-20261016"
    manifest = root / "repro-force-series.json"
    if manifest.exists():
        raise RuntimeError("Probe series exists; no duplicate or automatic retry")
    state = {"status": "waiting_for_main_series", "harness_sha256": digest(__file__), "arms": []}
    save(manifest, state)
    try:
        while True:
            main = json.loads((root / "repro-series.json").read_text())
            if main["status"] == "completed_diagnostic_not_production_acceptance":
                break
            if main["status"] != "running":
                raise RuntimeError("Main series failed; probes not launched")
            check_idle()
            time.sleep(5)
        state["status"] = "running"
        for name, binary, phase in [
            ("repro-force-probe", "source-force-probe/bin/adgpu_force_probe_128", "force"),
            ("repro-force-probe-barrier", "source-force-probe-barrier/bin/adgpu_force_probe_barrier_128", "force"),
            ("repro-one-workitem-barrier", "source-candidate/bin/adgpu_candidate_1", "medium"),
        ]:
            check_idle()
            cmd = [sys.executable, str(Path(__file__).with_name("autodock_gpu_repro.py")), "--pilot", str(root / "pilot"),
                   "--engine", str(root / binary), "--out", str(root / name), "--phase", phase]
            row = {"name": name, "status": "running", "command": cmd}
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
