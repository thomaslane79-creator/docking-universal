#!/usr/bin/env python3
"""Final read-only integrity checks after explicit visual review of seven pages."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from autodock_gpu_trial import digest, save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",type=Path,required=True)
    p.add_argument("--pdf-pages-reviewed",type=int,required=True)
    a=p.parse_args();root=a.run.resolve();output=root/"completion.json"
    if output.exists():raise ValueError("Final verification already exists")
    if a.pdf_pages_reviewed!=7:raise ValueError("Expected all seven final PDF pages reviewed")
    s=json.loads((root/"layout-continuation.json").read_text())
    pdf=json.loads((root/"report-finalization.json").read_text())
    if s["status"]!="completed_benchmark_pending_pdf_visual_QA" or pdf["status"]!="awaiting_pdf_visual_QA":raise ValueError("Work not complete")
    if digest(pdf["report"])!=pdf["sha256"]:raise ValueError("PDF changed after rendering")
    for file,expected in {**s["source_hashes"],**s["map_hashes"]}.items():
        if digest(file)!=expected:raise ValueError("Input or map changed")
    for j in s["jobs"]:
        for pose in j["poses"]:
            if digest(pose["pdbqt"])!=pose["sha256"] or digest(pose["typed_sdf"])!=pose["typed_sdf_sha256"]:
                raise ValueError("Pose changed")
    diagrams=[]
    for manifest in sorted(root.glob("compounds/*/pose_analysis/cluster_*/interactions/diagram_spacing20.manifest.json")):
        pic=manifest.with_suffix("").with_suffix(".png")
        collision=json.loads(Path(str(pic)+".collision-audit.json").read_text())
        info=json.loads(manifest.read_text())
        if collision["overlapCount"]!=0 or info["collision_count"]!=0 or info["layout_failure_count"]!=0:
            raise ValueError("Diagram collision/layout gate failed")
        diagrams.append({"manifest":str(manifest),"sha256":digest(manifest),"diagram":str(pic),"diagram_sha256":digest(pic)})
    if len(s["jobs"])!=30 or len(diagrams)!=6:raise ValueError("Missing search or diagram")
    result={"status":"completed_scoped_performance_benchmark","scientific_acceptance":False,"production_changed":False,
        "verified_utc":datetime.now(timezone.utc).isoformat(),"harness_sha256":digest(__file__),
        "searches":30,"poses_chemistry_checked":600,"selected_clusters":6,"searches_repeated":0,
        "source_inputs_maps_outputs_unchanged":True,"pdf_pages_visually_reviewed":7,"report":pdf["report"],"report_sha256":pdf["sha256"],
        "docking_phase_seconds":s["docking_phase_seconds"],"search_process_wall_seconds":s["search_process_wall_seconds"],
        "analysis_and_visuals_seconds":s["analysis_and_visuals_seconds"],
        "active_processing_seconds_excluding_preparation_manual_recovery_and_QA":s["active_processing_seconds_excluding_preparation_manual_recovery_and_QA"],
        "elapsed_to_initial_report_including_manual_recovery_seconds":s["elapsed_from_initial_start_including_manual_recovery_seconds"],
        "report_only_regeneration_seconds_not_in_benchmark":pdf["report_only_regeneration_seconds"],
        "timing_caveat":"Stage-summed active processing is not an uninterrupted whole-run timing. Manual recovery/visual QA and final report-layout revision are excluded; original failure logs preserved. Different AD4/Vina search and pose budgets, custom benchmark versus production PDF.",
        "historical_cpu8":{"docking_worker_seconds":499.311545708,"docking_plus_analysis_seconds":581.595224083},
        "continuation_records":{n:digest(root/n) for n in ["summary.json","postprocessing-continuation.json","layout-continuation.json","report-finalization.json"]},
        "diagrams":diagrams,"unresolved_numerical_gate":s["unresolved_numerical_gate"]}
    save(output,result)
    print(json.dumps({k:result[k] for k in ["status","searches","poses_chemistry_checked","docking_phase_seconds","active_processing_seconds_excluding_preparation_manual_recovery_and_QA"]},indent=2))


if __name__=="__main__":main()
