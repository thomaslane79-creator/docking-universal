#!/usr/bin/env python3
"""Retain complete outcomes/provenance; containment is not a kernel repair."""
import json
from pathlib import Path
import subprocess
import numpy as np
from autodock_gpu_trial import digest, save


def main():
    root=Path(__file__).resolve().parent/"runs/autodock-gpu-mac-20261016"
    target=root/"remaining-limitations-analysis.json"
    if target.exists(): raise RuntimeError("Fresh output required")
    controls=json.loads((root/"execution-limits-ready/summary.json").read_text())
    series=json.loads((root/"remaining-limitations-series.json").read_text())
    candidate=json.loads((root/"gpu-candidate-checks.json").read_text())
    if controls["status"]!="completed_diagnostic_with_explicit_outcomes" or series["status"]!="completed_diagnostic_not_production_acceptance" or candidate["status"]!="completed_checks_with_explicit_outcomes":
        raise RuntimeError("Diagnostic workers not terminal")
    result={"status":"completed_diagnostic_with_quarantined_one_workitem","production_changed":False,
            "one_workitem_underlying_defect_repaired":False,"one_workitem_guard":candidate["one_workitem_guard"],
            "harness_sha256":digest(__file__),"arms":{},"provenance":{},"execution_controls":[]}
    for row in controls["runs"]:
        result["execution_controls"].append({k:v for k,v in row.items() if k not in ["events","energies"]})
    for name in ["repro-finish-control","energy-audit","repro-size32","repro-size64","repro-guarded128"]:
        path=root/name/"summary.json"
        data=json.loads(path.read_text())
        result["arms"][name]={"summary_sha256":digest(path),"engine_sha256":data["engine_sha256"],
            "status":data["status"],"invocations":len(data["runs"]),"comparisons":data["comparisons"]}
    result["search_invocations"]=len(controls["runs"])+sum(x["invocations"] for x in result["arms"].values())
    result["energy_reference_analysis_sha256"]=digest(root/"energy-reference-analysis-v2.json")
    result["one_workitem_zeroed_checkpoint_evidence"]=[]
    for folder in sorted((root/"repro-finish-control").glob("*_r*")):
        for path in folder.glob("trace-*-population.bin"):
            x=np.fromfile(path,dtype="float32").reshape(-1,20)
            zero=int(np.count_nonzero(~np.any(x,axis=1)))
            if zero or not np.isfinite(x).all():
                result["one_workitem_zeroed_checkpoint_evidence"].append({"path":str(path),"zeroed_entities":zero,"finite":bool(np.isfinite(x).all())})
    for name in ["source-execution-audit","source-finish-audit","source-energy-audit","source-gpu-candidate-guarded","source-candidate"]:
        source=root/name
        files=[p for sub in ["common","device","host","wrapcl"] for p in (source/sub).rglob("*") if p.is_file()]
        result["provenance"][name]={"git_head":subprocess.check_output(["git","-C",str(source),"rev-parse","HEAD"],text=True).strip(),
            "source_sha256":{str(p.relative_to(source)):digest(p) for p in files},
            "diff":subprocess.check_output(["git","-C",str(source),"diff","--","device","host/src","wrapcl/src"],text=True)}
    save(target,result)
    print(json.dumps({"search_invocations":result["search_invocations"],"guard":result["one_workitem_guard"]["status"],
        "repeatability":{name:{"matching":sum(c["populations_identical"] for c in a["comparisons"]),"comparisons":len(a["comparisons"])} for name,a in result["arms"].items()}},indent=2))


if __name__=="__main__": main()
