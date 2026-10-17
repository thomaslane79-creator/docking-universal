#!/usr/bin/env python3
"""Report-only portrait/identity revision of the completed isolated benchmark."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time

from autodock_gpu_full_screen import make_report, report_compound_identity
from autodock_gpu_trial import digest, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    root = args.run.resolve()
    revision = root / "report-portrait-revision.json"
    if revision.exists():
        raise ValueError("Revision already exists; do not overwrite its provenance")
    completion_path = root / "completion.json"
    completion = json.loads(completion_path.read_text())
    if completion["status"] != "completed_scoped_performance_benchmark":
        raise ValueError("Expected completed benchmark")
    report = Path(completion["report"])
    if digest(report) != completion["report_sha256"]:
        raise ValueError("Prior report differs from its completed verification")
    preserved = root / "provenance/gpu-screen-benchmark.landscape.pdf"
    if preserved.exists():
        raise ValueError("Prior report already preserved; inspect before retrying")
    state = json.loads((root / "layout-continuation.json").read_text())
    config = json.loads((root / "source-config.json").read_text())
    inputs = {**state["source_hashes"], **state["map_hashes"]}
    for path, expected in inputs.items():
        if digest(path) != expected:
            raise ValueError("Scientific input changed: " + path)
    scientific_files = sorted(p for folder in (root / "compounds", root / "maps")
                              for p in folder.rglob("*") if p.is_file())
    hashes = {str(p): digest(p) for p in scientific_files}
    shutil.copy2(report, preserved)
    started = time.monotonic()
    make_report(config, root, state)
    seconds = time.monotonic() - started
    for path, expected in {**inputs, **hashes}.items():
        if digest(path) != expected:
            raise ValueError("Scientific artifact changed: " + path)
    identities = [{"internal_id": compound["id"], "input": compound["input"],
                   "input_sha256": digest(compound["input"]),
                   "report_label": report_compound_identity(compound, i)[0],
                   "label_source": report_compound_identity(compound, i)[1]}
                  for i, compound in enumerate(config["compounds"], 1)]
    save(revision, {"status": "awaiting_pdf_visual_QA", "created_utc": datetime.now(timezone.utc).isoformat(),
        "report": str(report), "report_sha256": digest(report), "orientation": "portrait",
        "preserved_landscape_report": str(preserved), "prior_report_sha256": digest(preserved),
        "prior_benchmark_completion": str(completion_path), "prior_completion_sha256": digest(completion_path),
        "report_only_generation_seconds_not_benchmark_timing": seconds,
        "identity_mapping": identities, "scientific_artifact_hashes": hashes,
        "scientific_inputs_outputs_unchanged": True, "searches_repeated": 0,
        "production_changed": False, "scientific_acceptance": False,
        "harness_sha256": digest(__file__), "report_authoring_sha256": digest(Path(__file__).with_name("autodock_gpu_full_screen.py")),
        "changes": "Portrait Letter; stacked labeled 2D/3D panels; headings use actual retained Nextval_ID, not file-derived titles. All prior scientific results, timing and completion records preserved."})
    print(json.dumps({"report": str(report), "revision": str(revision), "scientific_artifacts_verified": len(hashes)}))


if __name__ == "__main__":
    main()
