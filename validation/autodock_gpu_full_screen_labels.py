#!/usr/bin/env python3
"""Label retained benchmark contact figures; no docking, PLIP or 2D reruns."""
import argparse
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time

from autodock_gpu_trial import digest, save


def render(source, output):
    """One label per actual PLIP-contacting protein residue in the retained PSE."""
    import pymol
    import numpy as np
    from pymol import cmd
    pymol.finish_launching(["pymol", "-cq"])
    cmd.load(str(source))
    before = cmd.get_coords("all").copy()
    selections = [name for name in cmd.get_names("selections")
                  if name.startswith("plip_contact_residues_chain_")]
    if not selections:
        raise ValueError("Retained scene has no PLIP contact selections")
    selected = "(" + " or ".join(selections) + ") and polymer.protein"
    atoms = []
    cmd.iterate(selected, "atoms.append({'model':model, 'index':index, 'resn':resn, 'resi':resi, 'chain':chain, 'segi':segi, 'name':name})", space={"atoms": atoms})
    residues = {}
    for atom in atoms:
        key = (atom["model"], atom["segi"], atom["chain"], atom["resi"])
        if key not in residues or (atom["name"] == "CA" and residues[key]["name"] != "CA"):
            residues[key] = atom
    if not residues:
        raise ValueError("PLIP contact selections are empty")
    cmd.hide("labels", "all")
    cmd.set("label_color", "black")
    cmd.set("label_outline_color", "white")
    cmd.set("label_font_id", 5)
    cmd.set("label_size", 40)
    cmd.set("float_labels", 1)
    cmd.set("label_shadow_mode", 0)
    cmd.set("label_connector", 1)
    cmd.set("label_connector_color", "gray50")
    cmd.set("label_connector_width", 1.5)
    cmd.set("label_position", [0, 0, 0])
    cmd.set("label_bg_color", "white")
    cmd.set("label_bg_transparency", 0.0)
    # Screen-relative front-plane labels also work in ray tracing, unlike
    # float_labels, which only affects the interactive OpenGL display.
    view = cmd.get_view()
    rotation = np.asarray(view[:9]).reshape(3, 3)
    origin = np.asarray(view[12:15])
    projected = []
    for key, atom in residues.items():
        selection = f"model {atom['model']} and index {atom['index']}"
        camera = rotation @ (np.asarray(cmd.get_atom_coords(selection)) - origin)
        projected.append((float(camera[0]), float(camera[1]), key))
    projected.sort()
    placements = {}
    split = (len(projected) + 1) // 2
    for side, group in ((-1, projected[:split]), (1, projected[split:])):
        for i, (_, _, key) in enumerate(sorted(group, key=lambda row: row[1])):
            y = -0.65 + i * 1.3 / (len(group) - 1) if len(group) > 1 else 0.0
            placements[key] = [side * 0.82, y, 1.0]
    labels = []
    for key, atom in sorted(residues.items()):
        selection = f"model {atom['model']} and index {atom['index']}"
        text = f"{atom['resn'].capitalize()}{atom['resi']}{atom['chain']}"
        cmd.label(selection, repr(text))
        cmd.set("label_relative_mode", 1, selection)
        cmd.set("label_screen_point", placements[key], selection)
        labels.append({"label": text, "model": atom['model'], "chain": atom['chain'],
                       "residue_number": atom['resi'], "residue_name": atom['resn'],
                       "anchor_atom": atom['name'], "atom_index": atom['index'],
                       "label_screen_point": placements[key]})
    cmd.deselect()
    cmd.bg_color("white")
    cmd.set("antialias", 2)
    cmd.set("ray_shadows", 0)
    cmd.set("ray_opaque_background", 1)
    cmd.viewport(1800, 1400)
    output.mkdir(parents=True, exist_ok=False)
    cmd.png(str(output / "contacts.png"), width=1800, height=1400, dpi=200, ray=1)
    cmd.save(str(output / "contacts.pse"))
    after = cmd.get_coords("all")
    if not np.array_equal(after, before):
        raise ValueError("Molecular coordinates changed while labeling")
    save(output / "labels.json", {"source_session": str(source), "source_sha256": digest(source),
         "contacts_sha256": digest(output / "contacts.png"), "labels": labels,
         "coordinates_unchanged": True, "label_scope": "PLIP-contacting protein residues only",
         "style": "Spaced foreground callouts with thin gray leaders, one per contacting residue; chain retained"})
    cmd.quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--render-session", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--revision-tag", default="")
    parser.add_argument("--prior-record", type=Path)
    args = parser.parse_args()
    if args.render_session:
        if not args.output:
            parser.error("--render-session requires --output")
        render(args.render_session.resolve(), args.output.resolve())
        return
    if not args.run:
        parser.error("--run is required")
    from autodock_gpu_full_screen import make_report
    root = args.run.resolve()
    if args.revision_tag and not re.fullmatch(r"[a-z0-9-]+", args.revision_tag):
        parser.error("Invalid revision tag")
    tag = "-" + args.revision_tag if args.revision_tag else ""
    revision = root / f"report-residue-label{tag}-revision.json"
    figure_root = root / f"residue-labeled-figures{tag}"
    if revision.exists() or figure_root.exists():
        raise ValueError("Label revision exists; inspect rather than silently rerun")
    prior_record = (args.prior_record.resolve() if args.prior_record else root / "report-portrait-qa.json")
    prior = json.loads(prior_record.read_text())
    report = root / "output/pdf/gpu-screen-benchmark.pdf"
    if digest(report) != prior["report_sha256"]:
        raise ValueError("Current PDF differs from its verified portrait revision")
    state = json.loads((root / "layout-continuation.json").read_text())
    config = json.loads((root / "source-config.json").read_text())
    previous = json.loads((root / "report-portrait-revision.json").read_text())
    hashes = {**state["source_hashes"], **state["map_hashes"], **previous["scientific_artifact_hashes"]}
    for path, expected in hashes.items():
        if digest(path) != expected:
            raise ValueError("Scientific artifact changed: " + path)
    preserved = root / f"provenance/gpu-screen-benchmark.before-residue-label{tag}.pdf"
    if preserved.exists():
        if digest(preserved) != prior["report_sha256"]:
            raise ValueError("Preserved portrait PDF differs from verified prior version")
    else:
        shutil.copy2(report, preserved)
    figure_root.mkdir()
    started = time.monotonic()
    records = []
    for compound in config["compounds"]:
        analysis = root / "compounds" / compound["id"] / "pose_analysis"
        for cluster in sorted(analysis.glob("cluster_*/cluster.json")):
            source = cluster.parent / "interactions/contacts.pse"
            output = figure_root / compound["id"] / cluster.parent.name
            output.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                "--render-session", str(source), "--output", str(output)], capture_output=True, text=True)
            save(output.with_suffix(".render-log.json"), {"returncode": result.returncode,
                 "stdout": result.stdout, "stderr": result.stderr})
            if result.returncode or not (output / "labels.json").is_file():
                raise RuntimeError("Label render failed: " + str(output.with_suffix(".render-log.json")))
            records.append({"compound": compound["id"], "cluster": cluster.parent.name,
                            "labels_record": str(output / "labels.json"),
                            "labels_record_sha256": digest(output / "labels.json")})
    make_report(config, root, state, contact_figure_root=figure_root)
    for path, expected in hashes.items():
        if digest(path) != expected:
            raise ValueError("Scientific artifact changed: " + path)
    save(revision, {"status": "awaiting_pdf_visual_QA", "created_utc": datetime.now(timezone.utc).isoformat(),
         "report": str(report), "report_sha256": digest(report), "figures": records,
         "prior_pdf": str(preserved), "prior_pdf_sha256": digest(preserved),
         "prior_revision_sha256": digest(root / "report-portrait-revision.json"),
         "prior_report_record": str(prior_record), "prior_report_record_sha256": digest(prior_record),
         "harness_sha256": digest(__file__),
         "render_and_report_seconds_excluded_from_benchmark": time.monotonic() - started,
         "original_scientific_artifacts_checked": len(hashes), "original_artifacts_unchanged": True,
         "docking_PLIP_and_2D_repeated": False, "production_changed": False,
         "scientific_acceptance": False})
    print(json.dumps({"report": str(report), "labeled_figures": len(records)}))


if __name__ == "__main__":
    main()
