#!/usr/bin/env python3
"""Isolated full 2R8N workload on patched AD4 GPU; never a Vina protocol reuse.

Exact prepared chemistry, all 2 x 3 x 5 inputs, 20 LGA winners per search.
Native outputs stay AD4. Shared geometry/PLIP/render stages take typed molecules;
no fake VINA remarks or production engine installation.
"""
import argparse
import csv
from datetime import datetime, timezone
import fcntl
import html
import importlib.util
import json
import os
from pathlib import Path
import shutil
import statistics
import sys
import time

from rdkit import Chem
from rdkit.Chem import rdMolAlign

from autodock_gpu_control_panel import ARMS, RUN_ROOT, command, gpu_log_valid, validate_types, xml_ranking
from autodock_gpu_trial import ROOT, check_idle, digest, execute, grid_description, mapped_molecule, pdbqt_atoms, pose_from_template, save

SOURCE = ROOT / "validation/runs/vina-execution-20261015_095135"
ENGINE = RUN_ROOT / "source-gpu-candidate-guarded/bin/adgpu_guarded_128"
NODE = "/Users/crown2/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"


def inventory(config):
    if len(config["compounds"]) != 2 or len(config["parameters"]["seeds"]) != 5:
        raise ValueError("Expected exact original two-compound/five-seed workload")
    rows = []
    for c in config["compounds"]:
        if len(c["prepared"]) != 3:
            raise ValueError("Expected all three retained conformers")
        identities = set()
        for path in c["prepared"]:
            if digest(path) != c["prepared_sha256"][path]:
                raise ValueError("Prepared input changed: " + path)
            mol = mapped_molecule(Path(path).read_text())
            identities.add(Chem.MolToSmiles(mol, isomericSmiles=True))
            validate_types({a[3] for a in pdbqt_atoms(Path(path).read_text())})
            for seed in config["parameters"]["seeds"]:
                rows.append({"compound": c["id"], "ligand": path, "conformer": Path(path).stem, "seed": seed})
        if len(identities) != 1:
            raise ValueError("Retained conformers differ in chemical state")
    return rows


def typed_adapter(target, output, poses):
    """Neutral typed-score contract for existing geometry-only clustering route.

    The historical command calls this a comparison table, but these inputs are
    AD4 predictions, not experimental pose comparisons. No RMSD is invented.
    """
    output.mkdir(parents=True, exist_ok=False)
    with (output / "pose_comparison.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["model", "affinity_kcal_per_mol"])
        writer.writeheader()
        for rank, row in enumerate(poses, 1):
            mol = row.pop("molecule")
            mol.SetProp("DockingUniversal_Engine", "autodock-gpu-ad4-experimental")
            mol.SetProp("DockingUniversal_Source", row["pdbqt"])
            mol.SetDoubleProp("DockingUniversal_AD4BindingEnergy", row["binding_energy_kcal_mol"])
            sdf = output / f"pose_{rank:03d}.sdf"
            with Chem.SDWriter(str(sdf)) as w:
                w.write(mol)
            row["typed_sdf"] = str(sdf)
            row["typed_sdf_sha256"] = digest(sdf)
            writer.writerow({"model": rank, "affinity_kcal_per_mol": row["binding_energy_kcal_mol"]})
    save(output / "score_provenance.json", {"engine": "AutoDock-GPU AD4", "experimental_crystal": False,
         "source": str(target), "ranking": "Upstream XML order, preserved on printed ties", "poses": poses})


def run_stage(state, summary, folder, stage, filename, args, timeout=1200):
    return execute([sys.executable, ROOT / "libexec" / filename, *args], folder, stage, state, summary, timeout)


def postprocess(config, out, state, summary):
    started = time.monotonic()
    state["phase"] = "analysis_and_visuals"
    save(summary, state)
    for compound in config["compounds"]:
        folder = out / "compounds" / compound["id"]
        analysis = folder / "pose_analysis"
        process = run_stage(state, summary, folder, "cluster", "docking-universal-cluster-poses.py",
            ["--comparison-root", folder / "typed_predictions", "--receptor", config["receptor_pdb"],
             "--out", analysis, "--cluster-rmsd", str(config["cluster_rmsd"]), "--representatives", "3"])
        manifest = json.loads((analysis / "clustering_manifest.json").read_text())
        if manifest["pose_count"] != 300 or not 1 <= manifest["selected_representative_count"] <= 3:
            raise ValueError("Expected 300 poses and up to three distinct selected clusters")
        manifest.update(engine="AutoDock-GPU AD4 experimental", crystal_reference_available=False,
                        energy_meaning="Upstream estimated AD4 binding energy, not Vina binding energy")
        save(analysis / "clustering_manifest.json", manifest)
        run_stage(state, summary, folder, "browser3d", "docking-universal-render3d.py",
                  [analysis / "representative_browser.pml", "--out", analysis / "representative_browser.png",
                   "--session-out", analysis / "representative_browser.pse"])
        for cluster in sorted(analysis.glob("cluster_*")):
            if not cluster.is_dir():
                continue
            run_stage(state, summary, cluster, "representative3d", "docking-universal-render3d.py",
                      [cluster / "representative.pml", "--out", cluster / "representative.png",
                       "--session-out", cluster / "representative.pse"])
            run_stage(state, summary, cluster, "plip", "docking-universal-interactions.py",
                [cluster / "complex.pdb", "--out-dir", cluster / "interactions", "--skip-native-visuals",
                 "--typed-ligand-sdf", cluster / "representative.sdf", "--ligand-resname", "UNL",
                 "--ligand-chain", "Z", "--ligand-position", "1"])
            run_stage(state, summary, cluster, "interaction3d", "docking-universal-render3d.py",
                [cluster / "interactions/complex_plip_all_in_one.pml", "--out", cluster / "interactions/contacts.png",
                 "--session-out", cluster / "interactions/contacts.pse"])
            run_stage(state, summary, cluster, "interaction2d", "docking-universal-render-poseedit.py",
                ["--ligand", cluster / "representative.sdf", "--receptor", config["receptor_pdb"],
                 "--plip-xml", cluster / "interactions/report.xml", "--output", cluster / "interactions/diagram.png",
                 "--scale", "3", "--node", NODE, "--ligand-spacing", "20"])
    state["analysis_and_visuals_seconds"] = time.monotonic() - started


def report_compound_identity(compound, ordinal):
    """Use the retained library identifier, never an input filename as a name."""
    mol = next(iter(Chem.SDMolSupplier(str(compound["input"]))), None)
    if mol is not None and mol.HasProp("Nextval_ID"):
        identifier = mol.GetProp("Nextval_ID").strip()
        if identifier:
            return f"Compound {identifier}", "Retained library identifier: Nextval_ID"
    return f"Compound {ordinal}", "Sequential report label; no verified library identifier available"


def make_report(config, out, state, contact_figure_root=None):
    """Benchmark PDF deliberately does not claim production AD4 integration."""
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
    report = out / "output/pdf/gpu-screen-benchmark.pdf"
    report.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 12
    story = [Paragraph("AutoDock-GPU: full retained workload", styles["Title"]), Spacer(1, 12),
        Paragraph("Isolated Apple-Silicon benchmark | AutoDock4 scoring | Not a validated screening protocol", styles["Heading2"]),
        Paragraph("Two compounds, three retained conformers each and five seeds: 30 searches, each retaining 20 genetic-search run winners. No chemical preparation was repeated. The original Vina protocol and study are unchanged.", styles["BodyText"]), Spacer(1, 10)]
    for text in ["AD4 and Vina use different scoring/search methods. Their energies are not interchangeable, nor are their search budgets equivalent.",
                 "Neither compound has a crystal reference here. Pose differences from previous Vina predictions are NOT experimental RMSD or evidence that either engine is correct.",
                 "An earlier separate matched-formula audit failed a strict numerical gate on one non-winning tipranavir state (0.000932 kcal/mol). It remains unresolved; this timing run does not waive that gate or authorize engine integration.",
                 f"Historical clustering override retained for comparison: {config['cluster_rmsd']:g} A; three lowest-energy distinct cluster representatives. Current new-study defaults are not changed.",
                 "This PDF is an engine-labeled benchmark report, not the unmodified Vina-specific production report. Shared clustering, PLIP, 2D and ray-rendered PyMOL stages are timed separately; PDF-generation costs are not identical."]:
        story.extend([Paragraph(html.escape(text), styles["BodyText"]), Spacer(1, 7)])
    rows = [["Stage", "Seconds"], ["AD4 map generation", f"{state['map_wall_seconds']:.2f}"],
            ["All 30 search processes", f"{state['search_process_wall_seconds']:.2f}"],
            ["Docking phase incl. validation/export", f"{state['docking_phase_seconds']:.2f}"],
            ["Shared analysis and visuals", f"{state['analysis_and_visuals_seconds']:.2f}"],
            ["Historical 8-thread Vina docking + analysis", "581.60 (prepared inputs reused)"]]
    rows = [[Paragraph(html.escape(str(cell)), styles["BodyText"]) for cell in row] for row in rows]
    t = Table(rows, colWidths=[332, 184]); t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e4edf6")),
        ("GRID", (0, 0), (-1, -1), .4, colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story.extend([Spacer(1, 8), t, Spacer(1, 8), Paragraph(
        "Molecule headings use retained library identifiers, not source filenames. File mappings are retained separately in the report revision provenance.", styles["BodyText"])])
    for ordinal, compound in enumerate(config["compounds"], 1):
        display_name, identity_note = report_compound_identity(compound, ordinal)
        root = out / "compounds" / compound["id"] / "pose_analysis"
        jobs = [j for j in state["jobs"] if j["compound"] == compound["id"]]
        clusters = sorted(root.glob("cluster_*/cluster.json"), key=lambda p: (json.loads(p.read_text())["best_energy"], int(json.loads(p.read_text())["cluster_id"])))
        for rank, cluster in enumerate(clusters, 1):
            if not cluster.parent.is_dir(): continue
            story.extend([PageBreak(), Paragraph(html.escape(display_name), styles["Heading2"]),
                Paragraph(html.escape(identity_note), styles["BodyText"]),
                Paragraph(f"15 searches; 300 retained winners. Search-process wall sum: {sum(j['wall_seconds'] for j in jobs):.2f} s. AD4 energy rank {rank} among selected clusters.", styles["BodyText"])])
            data = json.loads(cluster.read_text())
            story.extend([Spacer(1, 8), Paragraph(f"Cluster {data['cluster_id']} | AD4 {data['best_energy']:.2f} kcal/mol | {data['pose_count']} poses | {data['seed_support']} seeds", styles["Heading3"])])
            contact_image = (Path(contact_figure_root) / compound["id"] / cluster.parent.name / "contacts.png"
                             if contact_figure_root is not None else cluster.parent / "interactions/contacts.png")
            for label, img in [("2D interactions", cluster.parent / "interactions/diagram.png"),
                               ("3D PLIP contacts" + (" - contacting residues labeled" if contact_figure_root is not None else ""), contact_image)]:
                w, h = ImageReader(str(img)).getSize()
                scale = min(516 / w, 260 / h)
                story.extend([Paragraph(label, styles["BodyText"]),
                              Image(str(img), width=w * scale, height=h * scale), Spacer(1, 5)])
    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(48, 20, "Isolated AD4 GPU benchmark - not an approved screening protocol")
        canvas.drawRightString(564, 20, str(doc.page))
    SimpleDocTemplate(str(report), pagesize=(612, 792), leftMargin=48, rightMargin=48, topMargin=32, bottomMargin=32,
                      title="AutoDock-GPU full retained-workload benchmark", author="Docking Universal").build(story, onFirstPage=footer, onLaterPages=footer)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--preflight-only", action="store_true")
    a = p.parse_args()
    out = a.out.resolve()
    if out.exists(): raise ValueError("Output exists; no duplicate/restart")
    check_idle()
    config = json.loads((SOURCE / "config.json").read_text())
    work = inventory(config)
    if digest(config["protocol_bundle"]) != config["protocol_sha256"]:
        raise ValueError("Retained Vina bundle changed")
    if digest(ENGINE) != "062b5816f8342fa4c2150d65852e83f52940fe2f2cb603710e27527b33a9d02a":
        raise ValueError("Patched engine identity changed")
    if a.preflight_only:
        print(json.dumps({"searches": len(work), "prepared_inputs": 6, "retained_pose_target": 600,
                          "seeds": config["parameters"]["seeds"], "cluster_rmsd": config["cluster_rmsd"]})); return
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    os.environ["PYTHONPATH"] = str(ROOT / "libexec") + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.environ["DOCKING_UNIVERSAL_PYTHON"] = sys.executable
    with (RUN_ROOT / "full-screen.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        out.mkdir(parents=True, exist_ok=False)
        save(out / "source-config.json", config)
        summary = out / "summary.json"
        files = [SOURCE / "config.json", Path(config["receptor"]), Path(config["receptor_pdb"]),
                 Path(config["box"]), Path(config["protocol_bundle"]), ENGINE]
        files += [Path(x) for c in config["compounds"] for x in c["prepared"]]
        state = {"status": "running", "phase": "maps", "pid": os.getpid(), "processes": [], "jobs": [],
                 "started_utc": datetime.now(timezone.utc).isoformat(), "production_changed": False,
                 "source_hashes": {str(f): digest(f) for f in files}, "harness_sha256": digest(__file__),
                 "scientific_settings": {"engine": "AutoDock-GPU v1.6 patched AD4 OpenCL 128", "nrun": 20,
                   "search_profile": "heuristics/autostop enabled, 12M heuristic cap, population 150, ADADELTA 300 iterations",
                   "chemistry_preparation": "exact retained original, not repeated", "search_count": 30,
                   "seeds": config["parameters"]["seeds"], "clustering_angstrom": config["cluster_rmsd"]},
                 "unresolved_numerical_gate": str(RUN_ROOT / "control-panel-atomtype-audit/summary.json"),
                 "limitations": ["Not equivalent-work GPU Vina or a new approved protocol; AD4 scoring/search differs.",
                    "No experimental structures for these compounds; Vina agreement is not experimental pose recovery.",
                    "600 AD4 run winners versus 450 retained Vina poses; clustering/visual costs and pose distributions differ.",
                    "Prepared chemistry reused; no new preparation timing. Dedicated labeled benchmark PDF, not Vina production PDF.",
                    "Earlier strict numerical-audit failure remains unresolved; this timing test does not relax acceptance."]}
        save(summary, state)
        started = time.monotonic()
        try:
            maps = out / "maps"; maps.mkdir(); shutil.copy2(config["receptor"], maps / "receptor.pdbqt")
            types = sorted({atom[3] for c in config["compounds"] for f in c["prepared"] for atom in pdbqt_atoms(Path(f).read_text())})
            receptor_types = sorted({x[3] for x in pdbqt_atoms(Path(config["receptor"]).read_text())})
            text, state["grid"] = grid_description(config["geometry"], receptor_types, types)
            (maps / "receptor.gpf").write_text(text)
            proc = execute(["/usr/local/bin/autogrid4", "-p", "receptor.gpf", "-l", "receptor.glg"], maps, "autogrid", state, summary, 300)
            if "Successful Completion" not in (maps / "receptor.glg").read_text(): raise ValueError("AutoGrid failed")
            state["map_wall_seconds"] = proc["wall_seconds"]
            state["map_hashes"] = {str(p): digest(p) for p in maps.glob("receptor.*.map")}
            state["phase"] = "docking"
            vina = json.loads((SOURCE / "shared_grid_cpu8/execution.json").read_text())
            for task in work:
                check_idle()
                folder = out / "compounds" / task["compound"] / f"seed_{task['seed']}" / task["conformer"]
                folder.mkdir(parents=True); shutil.copy2(task["ligand"], folder / "ligand.pdbqt")
                proc = execute(command(ENGINE, maps / "receptor.maps.fld", ARMS[0], task["seed"]), folder, "adgpu", state, summary, 1200)
                if not gpu_log_valid((folder / "adgpu.stdout.log").read_text()): raise ValueError("GPU completion not confirmed")
                rows = xml_ranking(folder / "result.xml", 20)
                for row in rows:
                    path = folder / f"ligand_docked_run{row['run']}_entity1.pdbqt"
                    mol = pose_from_template(Path(task["ligand"]).read_text(), path.read_text())
                    row.update(molecule=mol, pdbqt=str(path), sha256=digest(path))
                previous = next(j for j in vina["jobs"] if j["compound"] == task["compound"] and j["seed"] == task["seed"] and j["ligand"] == Path(task["ligand"]).name)
                old_mol = mapped_molecule(Path(previous["output"]).read_text())
                delta = rdMolAlign.CalcRMS(rows[0]["molecule"], old_mol, refId=0)
                adapter = out / "compounds" / task["compound"] / "typed_predictions" / f"seed_{task['seed']}" / (task["conformer"] + "_comparison")
                typed_adapter(folder, adapter, rows)
                state["jobs"].append({**task, "directory": str(folder), "wall_seconds": proc["wall_seconds"],
                     "pose_count": 20, "chemistry_checks_passed": True, "poses": rows,
                     "lowest_AD4_energy_kcal_mol": rows[0]["binding_energy_kcal_mol"],
                     "top_pose_to_historical_Vina_top_pose_rmsd_NOT_experimental": delta,
                     "historical_cpu8_search_seconds": previous["dock_seconds"], "historical_vina_output_sha256": digest(previous["output"])})
                save(summary, state)
            state["docking_phase_seconds"] = time.monotonic() - started
            state["search_process_wall_seconds"] = sum(j["wall_seconds"] for j in state["jobs"])
            save(summary, state)
            postprocess(config, out, state, summary)
            state["phase"] = "benchmark_report"
            before = time.monotonic(); report = make_report(config, out, state)
            state.update(report_seconds=time.monotonic() - before, report=str(report),
                         pipeline_seconds_excluding_preparation_and_pdf_QA=time.monotonic() - started)
            for file, value in {**state["source_hashes"], **state["map_hashes"]}.items():
                if digest(file) != value: raise ValueError("Source/map changed: " + file)
            if len(state["jobs"]) != 30: raise ValueError("Incomplete workload")
            state.update(status="completed_benchmark_pending_pdf_visual_QA", phase="completed", poses_checked=600,
                         original_inputs_unchanged=True, scientific_acceptance=False)
        except BaseException as error:
            state.update(status="failed", error=str(error)); raise
        finally:
            state["finished_utc"] = datetime.now(timezone.utc).isoformat(); save(summary, state)


if __name__ == "__main__":
    main()
