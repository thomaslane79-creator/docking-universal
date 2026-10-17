#!/usr/bin/env python3
"""Dependent isolated synchronization and matched-coordinate scoring audits."""
import json
from pathlib import Path
import subprocess
import sys
import time
from autodock_gpu_trial import check_idle, digest, save


def main():
    root = Path(__file__).resolve().parent / "runs/autodock-gpu-mac-20261016"
    path = root / "remaining-limitations-series.json"
    if path.exists():
        raise RuntimeError("Series exists; no automatic duplicate/restart")
    state = {"status": "waiting_for_execution_controls", "harness_sha256": digest(__file__), "arms": [], "production_changed": False}
    save(path, state)
    try:
        while True:
            control = json.loads((root / "execution-limits-ready/summary.json").read_text())
            if control["status"] == "completed_diagnostic_with_explicit_outcomes":
                break
            if control["status"] != "running":
                raise RuntimeError("Execution controls stopped without completion")
            check_idle()
            time.sleep(5)
        state["status"] = "running"
        for name, binary, phase in [
            ("repro-finish-control", "source-finish-audit/bin/adgpu_finish_audit_1", "ad"),
            ("energy-audit", "source-energy-audit/bin/adgpu_energy_audit_128", "energy"),
        ]:
            check_idle()
            cmd=[sys.executable,str(Path(__file__).with_name("autodock_gpu_repro.py")),"--pilot",str(root/"pilot"),
                 "--engine",str(root/binary),"--out",str(root/name),"--phase",phase]
            row={"name":name,"command":cmd,"status":"running"}
            state["arms"].append(row)
            with (root/(name+".coordinator.log")).open("w") as log:
                child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
                row["pid"]=child.pid
                save(path,state)
                row["returncode"]=child.wait()
            result=json.loads((root/name/"summary.json").read_text())
            if row["returncode"] or result["status"]!="completed_diagnostic_not_production_acceptance":
                raise RuntimeError(f"{name} failed: {result.get('error',row['returncode'])}")
            row["status"]="completed"
            save(path,state)
        state["status"]="completed_diagnostic_not_production_acceptance"
    except BaseException as error:
        state.update(status="failed",error=str(error))
        raise
    finally:
        save(path,state)


if __name__=="__main__":
    main()
