#!/usr/bin/env python3
"""Explicit postprocessing continuation after isolated launcher-path failure.

Never dock, prepare or overwrite the failed record. Reuse verified completed
stages; run only missing downstream products after fixing PYTHONPATH.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time

from autodock_gpu_full_screen import ROOT, NODE, make_report, run_stage
from autodock_gpu_trial import check_idle, digest, save


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--layout20", action="store_true", help="Explicit continuation using supported 20-unit 2D spacing; keep collision gates")
    a = p.parse_args()
    out = a.run.resolve(); source = out / "summary.json"
    path = out / ("layout-continuation.json" if a.layout20 else "postprocessing-continuation.json")
    if path.exists(): raise ValueError("Continuation already exists; no silent restart")
    old = json.loads(source.read_text())
    if old.get("status") != "failed" or old.get("error") != "interaction2d: exit 1; inspect retained stdout/stderr" or len(old["jobs"]) != 30:
        raise ValueError("Not the completed-docking launcher-path failure")
    failed = old["processes"][-1]
    error = (Path(failed["cwd"]) / "interaction2d.stderr.log").read_text()
    if "ModuleNotFoundError: No module named 'docking_universal'" not in error:
        raise ValueError("Failure is not the identified launcher import-path error")
    if a.layout20:
        prior_path = out / "postprocessing-continuation.json"
        prior = json.loads(prior_path.read_text())
        if prior.get("status") != "failed" or prior.get("error") != "interaction2d_continued: exit 1; inspect retained stdout/stderr":
            raise ValueError("Not the recorded 2D continuation failure")
        last = prior["processes"][-1]
        if "collision-free unambiguous layout" not in (Path(last["cwd"]) / "interaction2d_continued.stderr.log").read_text():
            raise ValueError("Not the identified layout rejection")
        old["processes"] += prior["processes"]
    for file, expected in {**old["source_hashes"], **old["map_hashes"]}.items():
        if digest(file) != expected: raise ValueError("Original input/map changed")
    for job in old["jobs"]:
        for pose in job["poses"]:
            if digest(pose["pdbqt"]) != pose["sha256"] or digest(pose["typed_sdf"]) != pose["typed_sdf_sha256"]:
                raise ValueError("Saved pose changed")
    config = json.loads((out / "source-config.json").read_text())
    check_idle()
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    os.environ["PYTHONPATH"] = str(ROOT / "libexec") + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.environ["DOCKING_UNIVERSAL_PYTHON"] = sys.executable
    state = {**old, "status": "running", "phase": "continued_analysis", "processes": [],
             "initial_failed_summary": str(source), "initial_failed_summary_sha256": digest(source),
             "continuation_harness_sha256": digest(__file__), "continued_utc": datetime.now(timezone.utc).isoformat(),
             "reused_stages": [], "recovery_reason": "Set isolated launcher's PYTHONPATH to repo libexec; do not change renderer or scientific outputs."}
    if a.layout20:
        state.update(layout_spacing=20, prior_continuation_sha256=digest(prior_path),
                     layout_reason="Explicitly use supported 20-unit layout spacing; retain all failed spacing-15 audits and unchanged collision gates.")
    state.pop("error", None)
    save(path, state)
    initial_analysis_seconds = sum(r.get("wall_seconds", 0) for r in old["processes"] if r["name"] not in ("adgpu", "autogrid"))
    start = time.monotonic()

    def stage(folder, name, script, args, products):
        expected = [str(sys.executable), str(ROOT / "libexec" / script), *map(str, args)]
        previous = [r for r in old["processes"] if r["command"] == expected and r["status"] == "completed" and r.get("returncode") == 0]
        if previous:
            if any(not Path(p).is_file() or not Path(p).stat().st_size for p in products):
                raise ValueError("Completed stage missing products: " + name)
            state["reused_stages"].append({"name": name, "folder": str(folder),
                                            "products": {str(p): digest(p) for p in products}})
            save(path, state); return
        if any(Path(p).exists() for p in products):
            raise ValueError("Unverified product exists; do not overwrite: " + name)
        run_stage(state, path, folder, name + "_continued", script, args, timeout=1200)
        if any(not Path(p).is_file() or not Path(p).stat().st_size for p in products):
            raise ValueError("Stage omitted products: " + name)

    try:
        for compound in config["compounds"]:
            folder = out / "compounds" / compound["id"]; analysis = folder / "pose_analysis"
            stage(folder, "cluster", "docking-universal-cluster-poses.py",
                  ["--comparison-root", folder / "typed_predictions", "--receptor", config["receptor_pdb"],
                   "--out", analysis, "--cluster-rmsd", str(config["cluster_rmsd"]), "--representatives", "3"],
                  [analysis / "clustering_manifest.json", analysis / "cluster_summary.csv"])
            clustering = json.loads((analysis / "clustering_manifest.json").read_text())
            if clustering["pose_count"] != 300 or not 1 <= clustering["selected_representative_count"] <= 3:
                raise ValueError("Incomplete clustering")
            # A manifest sidecar labels the engine without rewriting a reused stage.
            if not (analysis / "AD4_engine_provenance.json").exists():
                save(analysis / "AD4_engine_provenance.json", {"engine": "AutoDock-GPU AD4 experimental", "crystal_reference_available": False})
            stage(folder, "browser3d", "docking-universal-render3d.py",
                  [analysis / "representative_browser.pml", "--out", analysis / "representative_browser.png", "--session-out", analysis / "representative_browser.pse"],
                  [analysis / "representative_browser.png", analysis / "representative_browser.pse"])
            for cluster in sorted(analysis.glob("cluster_*")):
                if not cluster.is_dir(): continue
                stage(cluster, "representative3d", "docking-universal-render3d.py",
                      [cluster / "representative.pml", "--out", cluster / "representative.png", "--session-out", cluster / "representative.pse"],
                      [cluster / "representative.png", cluster / "representative.pse"])
                stage(cluster, "plip", "docking-universal-interactions.py",
                      [cluster / "complex.pdb", "--out-dir", cluster / "interactions", "--skip-native-visuals", "--typed-ligand-sdf", cluster / "representative.sdf",
                       "--ligand-resname", "UNL", "--ligand-chain", "Z", "--ligand-position", "1"],
                      [cluster / "interactions/report.xml", cluster / "interactions/run_manifest.json"])
                stage(cluster, "interaction3d", "docking-universal-render3d.py",
                      [cluster / "interactions/complex_plip_all_in_one.pml", "--out", cluster / "interactions/contacts.png", "--session-out", cluster / "interactions/contacts.pse"],
                      [cluster / "interactions/contacts.png", cluster / "interactions/contacts.pse"])
                image = cluster / "interactions" / ("diagram_spacing20.png" if a.layout20 else "diagram.png")
                extra = ["--ligand-spacing", "20"] if a.layout20 else []
                stage(cluster, "interaction2d_spacing20" if a.layout20 else "interaction2d", "docking-universal-render-poseedit.py",
                      ["--ligand", cluster / "representative.sdf", "--receptor", config["receptor_pdb"], "--plip-xml", cluster / "interactions/report.xml",
                       "--output", image, "--scale", "3", "--node", NODE, *extra],
                      [image, image.with_suffix(".manifest.json")])
                if a.layout20:
                    canonical = cluster / "interactions/diagram.png"
                    if canonical.exists(): raise ValueError("Do not overwrite an existing canonical diagram")
                    shutil.copy2(image, canonical)
                    save(cluster / "interactions/accepted_diagram.json", {"accepted_source": str(image),
                         "accepted_sha256": digest(image), "pdf_alias": str(canonical), "spacing": 20,
                         "reason": "Explicit layout-only continuation; original failed spacing-15 audits preserved.",
                         "collision_gate_unchanged": True})
        state["continued_analysis_seconds"] = time.monotonic() - start
        state["initial_analysis_including_failed_stage_seconds"] = initial_analysis_seconds
        state["analysis_and_visuals_seconds"] = initial_analysis_seconds + state["continued_analysis_seconds"]
        before = time.monotonic(); report = make_report(config, out, state)
        state.update(report=str(report), report_seconds=time.monotonic() - before)
        state["active_processing_seconds_excluding_preparation_manual_recovery_and_QA"] = old["docking_phase_seconds"] + state["analysis_and_visuals_seconds"] + state["report_seconds"]
        state["elapsed_from_initial_start_including_manual_recovery_seconds"] = (datetime.now(timezone.utc) - datetime.fromisoformat(old["started_utc"])).total_seconds()
        for file, expected in {**old["source_hashes"], **old["map_hashes"]}.items():
            if digest(file) != expected: raise ValueError("Original input/map changed during continuation")
        state.update(status="completed_benchmark_pending_pdf_visual_QA", phase="completed", original_inputs_unchanged=True,
                     poses_checked=600, searches_repeated=0, scientific_acceptance=False)
    except BaseException as error:
        state.update(status="failed", error=str(error)); raise
    finally:
        state["finished_utc"] = datetime.now(timezone.utc).isoformat(); save(path, state)


if __name__ == "__main__":
    main()
