#!/usr/bin/env python3
"""Report-only layout repair; never rerun docking or analysis."""
import argparse
import json
from pathlib import Path
import time
from autodock_gpu_full_screen import make_report
from autodock_gpu_trial import digest, save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",type=Path,required=True)
    a=p.parse_args();root=a.run.resolve();output=root/"report-finalization.json"
    if output.exists(): raise ValueError("Report finalization already exists")
    source=root/"layout-continuation.json";state=json.loads(source.read_text())
    if state["status"]!="completed_benchmark_pending_pdf_visual_QA":raise ValueError("Benchmark is not completed")
    preserved=root/"provenance/gpu-screen-benchmark.initial.pdf"
    if digest(preserved)!=digest(state["report"]):raise ValueError("Initial draft was not preserved")
    for file,expected in {**state["source_hashes"],**state["map_hashes"]}.items():
        if digest(file)!=expected:raise ValueError("Scientific input changed")
    start=time.monotonic(); report=make_report(json.loads((root/"source-config.json").read_text()),root,state)
    save(output,{"status":"awaiting_pdf_visual_QA","report":str(report),"sha256":digest(report),
        "report_only_regeneration_seconds":time.monotonic()-start,"source_summary_sha256":digest(source),
        "initial_pdf_sha256":digest(preserved),"harness_sha256":digest(__file__),
        "changes":"Wrap table cells, landscape panels with one cluster per page, energy-ranked panel order and page numbers. No scientific results changed.",
        "searches_repeated":0,"scientific_inputs_unchanged":True})


if __name__=="__main__":main()
