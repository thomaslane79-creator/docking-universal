"""Site-first control inputs; an approved site is not a passed recovery control."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..protocol_finalization import approved_regions_from_study, sha256
from docking_universal_pocket_evidence import ligand_box_relationship, read_box_geometry


class NoControlSiteSelected(ValueError):
    """The chosen regions are valid but none can test this experimental pose."""


def reviewed_control_inputs(state) -> dict:
    setup = state.workflow_data.get("study_setup") or {}
    if setup.get("pathway") != "control" or not setup.get("site_review_first"):
        raise ValueError("This study has no site-first control preparation")
    regions, approval = approved_regions_from_study(state)
    assets = {}
    for name, kind in (("source_structure", "source_receptor_structure"),
                       ("source_pdb", "normalized_receptor_input"),
                       ("receptor_pdb", "prepared_receptor_structure"),
                       ("receptor_pdbqt", "prepared_receptor")):
        artifact = next((row for row in state.artifacts if row.kind == kind), None)
        if not artifact or not Path(artifact.path).is_file() or sha256(Path(artifact.path)) != artifact.sha256:
            raise ValueError(f"Reviewed control input changed or is missing: {kind}")
        assets[name] = {"path": artifact.path, "sha256": artifact.sha256}
    ligand = (str(setup["ligand_resname"]), str(setup["ligand_chain_id"]),
              str(setup["ligand_residue_number"]))
    coordinates = []
    for line in Path(assets["source_pdb"]["path"]).read_text().splitlines():
        if line.startswith(("ATOM  ", "HETATM")) and (
            line[17:20].strip(), line[21:22].strip() or "_", line[22:26].strip()
        ) == ligand and not line[26:27].strip():
            element = line[76:78].strip().upper()
            if element not in {"H", "D"}:
                coordinates.append([float(line[start:start + 8]) for start in (30, 38, 46)])
    if not coordinates:
        raise ValueError("Selected experimental control ligand is missing from the retained input")
    containing = [region for region in regions if ligand_box_relationship(
        np.asarray(coordinates), *read_box_geometry(region["box"]),
    )["all_heavy_atoms_inside"]]
    if not containing:
        raise NoControlSiteSelected("None of the selected regions contains the complete experimental control ligand. Select its site to run the control, or finalize the selected sites as explicitly exploratory.")
    # Selection order is retained in the decision and the first containing box
    # is disclosed before launch. Other selected regions are not auto-tested.
    tested = containing[0]
    sensitivity = state.workflow_data.get("receptor_state_sensitivity") or {}
    untested_states = []
    if tested["box_label"] in (sensitivity.get("affected_boxes") or []):
        primary = sensitivity.get("primary_review_state", "primary")
        untested_states = [name for name in (sensitivity.get("variants") or {}) if name != primary]
    assets["box"] = {"path": tested["box"], "sha256": tested["box_sha256"]}
    return {"schema_name": "docking-universal-reviewed-control-inputs", "schema_version": 1,
            "study_id": state.study_id, "approval_id": approval.id,
            "ligand_id": ":".join(ligand), "engine": setup["engine"],
            "assets": assets, "tested_box_label": tested["box_label"],
            "selected_regions": regions,
            "untested_box_labels": [region["box_label"] for region in regions if region is not tested],
            "untested_receptor_states": untested_states,
            "preparation_root": state.workflow_data["preparation_root"],
            "pdb_pocket_evidence": state.workflow_data.get("pdb_pocket_evidence", {"mode": "off"}),
            "authority": "site selection approved; pose-recovery control not yet performed"}


def read_reviewed_control_inputs(path, *, complex_path=None, ligand_id=None, engine=None, expected_sha256=None):
    """Recheck sealed files at the native control boundary, before any search."""
    if expected_sha256 and sha256(Path(path)) != expected_sha256:
        raise ValueError("Reviewed control input record changed after launch approval")
    record = json.loads(Path(path).read_text())
    if record.get("schema_name") != "docking-universal-reviewed-control-inputs" or record.get("schema_version") != 1:
        raise ValueError("Unsupported reviewed-control input record")
    for key in ("source_structure", "source_pdb", "receptor_pdb", "receptor_pdbqt", "box"):
        asset = record["assets"][key]
        if not Path(asset["path"]).is_file() or sha256(Path(asset["path"])) != asset["sha256"]:
            raise ValueError(f"Reviewed control input changed or is missing: {key}")
    if complex_path is not None and sha256(Path(complex_path)) != record["assets"]["source_pdb"]["sha256"]:
        raise ValueError("Control complex differs from the reviewed input")
    if ligand_id is not None and ligand_id != record["ligand_id"]:
        raise ValueError("Control ligand differs from the reviewed ligand")
    if engine is not None and engine != record["engine"]:
        raise ValueError("Control engine differs from the reviewed engine")
    if not record.get("approval_id") or not record.get("selected_regions"):
        raise ValueError("Reviewed control record lacks a persisted site approval")
    chosen = next((region for region in record["selected_regions"]
                   if region["box_label"] == record["tested_box_label"]), None)
    if not chosen or chosen["box_sha256"] != record["assets"]["box"]["sha256"]:
        raise ValueError("Control box is not the reviewed selected region")
    for region in record["selected_regions"]:
        if sha256(Path(region["box"])) != region["box_sha256"]:
            raise ValueError("A selected region changed after site approval")
    return record
