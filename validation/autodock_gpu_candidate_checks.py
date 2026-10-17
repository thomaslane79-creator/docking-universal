#!/usr/bin/env python3
"""Supported-size controls and fail-closed experimental-size guard."""
import json
from pathlib import Path
import subprocess
import sys
import time
from autodock_gpu_trial import check_idle, digest, execute, save


def main():
    root=Path(__file__).resolve().parent/"runs/autodock-gpu-mac-20261016"
    path=root/"gpu-candidate-checks.json"
    if path.exists():
        raise RuntimeError("Candidate checks already exist")
    state={"status":"waiting_for_scoring_audit","harness_sha256":digest(__file__),"processes":[],"arms":[],"production_changed":False}
    save(path,state)
    try:
        while True:
            prior=json.loads((root/"remaining-limitations-series.json").read_text())
            if prior["status"]=="completed_diagnostic_not_production_acceptance": break
            if prior["status"] not in ("running","waiting_for_execution_controls"):
                raise RuntimeError("Prior audit did not complete")
            check_idle()
            time.sleep(5)
        state["status"]="running"
        guard_folder=root/"one-workitem-rejection"
        guard_folder.mkdir(exist_ok=False)
        engine=root/"source-gpu-candidate-guarded/bin/adgpu_guarded_1"
        try:
            execute([engine,"--ffile",root/"pilot/indinavir_protease/receptor.maps.fld",
                "--lfile",root/"pilot/indinavir_protease/seed_41001_r0/ligand.pdbqt"],guard_folder,"guard",state,path,30)
        except RuntimeError:
            pass
        record=state["processes"][-1]
        stderr=(guard_folder/"guard.stderr.log").read_text()
        stdout=(guard_folder/"guard.stdout.log").read_text()
        if record.get("returncode")!=64 or "No docking was launched" not in stderr or "Running Job" in stdout or "OpenCL device:" in stdout:
            raise RuntimeError("One-work-item rejection guard failed")
        state["one_workitem_guard"]={"status":"passed_expected_rejection","engine_sha256":digest(engine),"returncode":64,"gpu_launch":False,"stderr":stderr}
        for name,binary in [("repro-size32","source-candidate/bin/adgpu_candidate_32"),
                            ("repro-size64","source-candidate/bin/adgpu_candidate_64"),
                            ("repro-guarded128","source-gpu-candidate-guarded/bin/adgpu_guarded_128")]:
            cmd=[sys.executable,str(Path(__file__).with_name("autodock_gpu_repro.py")),"--pilot",str(root/"pilot"),
                 "--engine",str(root/binary),"--out",str(root/name),"--phase","ad"]
            row={"name":name,"status":"running","command":cmd}
            state["arms"].append(row)
            with (root/(name+".coordinator.log")).open("w") as log:
                child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
                row["pid"]=child.pid;save(path,state)
                row["returncode"]=child.wait()
            summary=json.loads((root/name/"summary.json").read_text())
            if row["returncode"] or summary["status"]!="completed_diagnostic_not_production_acceptance":
                raise RuntimeError(f"{name} failed: {summary.get('error',row['returncode'])}")
            row.update(status="completed",all_repeat_populations_identical=all(c["populations_identical"] for c in summary["comparisons"]))
            save(path,state)
        state["status"]="completed_checks_with_explicit_outcomes"
    except BaseException as error:
        state.update(status="failed",error=str(error));raise
    finally:
        save(path,state)


if __name__=="__main__": main()
