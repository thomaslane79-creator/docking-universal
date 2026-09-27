"""Structured receptor-preparation stops shared by the engine, host, and GUI."""

from __future__ import annotations

import json
import math
import html
from pathlib import Path
from typing import Iterable

from ..decisions import DecisionOption, DecisionRequired


SCHEMA_NAME = "docking-universal-preparation-intervention"
SCHEMA_VERSION = 1


def _diagnosis_fields(path: Path) -> dict[str, str]:
    prefixes = {
        "Receptor preparation failure category": "category",
        "Why this matters": "scientific_concern",
        "Recommended next step": "recommended_action",
        "Detected detail": "detected_detail",
    }
    fields: dict[str, str] = {}
    if not path.is_file():
        return fields
    for raw in path.read_text(errors="replace").splitlines():
        if ":" not in raw:
            continue
        label, value = raw.split(":", 1)
        if label in prefixes:
            fields[prefixes[label]] = value.strip()
    return fields


def _histidines_without_ring_protons(path: Path) -> list[str]:
    residues: dict[tuple[str, str, str], set[str]] = {}
    if not path.is_file():
        return []
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or line[17:20].strip() != "HIS":
            continue
        key = (line[21:22].strip(), line[22:26].strip(), line[26:27].strip())
        residues.setdefault(key, set()).add(line[12:16].strip())
    return [
        f"{chain}:{number}{icode}"
        for (chain, number, icode), atoms in sorted(residues.items())
        if not ({"HD1", "HE2"} & atoms)
    ]


def write_intervention_record(
    diagnosis: Path,
    filtered_receptor: Path,
    output: Path,
    *,
    ambiguous_histidine: str = "",
    diagnostic_logs: Iterable[Path] = (),
    source_mmcif: Path | None = None,
) -> dict:
    """Write the versioned engine-to-application intervention contract."""

    fields = _diagnosis_fields(diagnosis)
    category = fields.get("category", "Unclassified receptor-template failure")
    histidine = ambiguous_histidine.strip()
    kind = "histidine_template" if category == "Ambiguous histidine protonation" and histidine else "review_required"
    record = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "category": category,
        "scientific_concern": fields.get("scientific_concern", ""),
        "recommended_action": fields.get("recommended_action", ""),
        "detected_detail": fields.get("detected_detail", ""),
        "diagnosis_path": str(diagnosis.resolve()),
        "filtered_receptor_path": str(filtered_receptor.resolve()),
        "diagnostic_logs": [str(Path(item).resolve()) for item in diagnostic_logs if Path(item).is_file()],
    }
    if histidine:
        record["residue"] = histidine
        candidates = _histidines_without_ring_protons(filtered_receptor)
        record["eligible_histidines"] = candidates or [histidine]
        if source_mmcif and source_mmcif.is_file():
            record["deposited_mmcif_evidence"] = _mmcif_histidine_context(
                source_mmcif, histidine,
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return "" if text in {".", "?"} else text


def _float(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _mmcif_histidine_context(source: Path, residue_key: str) -> dict:
    """Extract deposited context without inferring a protonation assignment."""

    try:
        import gemmi
    except ImportError:
        return {"status": "unavailable", "reason": "gemmi is unavailable"}
    try:
        block = gemmi.cif.read_file(str(source)).sole_block()
    except Exception as exc:
        return {"status": "unavailable", "reason": f"mmCIF could not be read: {exc}"}
    chain, _, residue_number = residue_key.partition(":")
    if not chain or not residue_number:
        return {"status": "unavailable", "reason": "residue identity is incomplete"}
    atoms = block.get_mmcif_category("_atom_site.")
    count = len(atoms.get("id", atoms.get("group_PDB", [])))

    def atom_value(name: str, index: int) -> str:
        values = atoms.get(name, [])
        return _clean(values[index]) if index < len(values) else ""

    target_rows: list[dict] = []
    all_rows: list[dict] = []
    for index in range(count):
        row = {
            "chain": atom_value("auth_asym_id", index) or atom_value("label_asym_id", index),
            "number": atom_value("auth_seq_id", index) or atom_value("label_seq_id", index),
            "insertion_code": atom_value("pdbx_PDB_ins_code", index),
            "residue_name": atom_value("auth_comp_id", index) or atom_value("label_comp_id", index),
            "atom_name": atom_value("auth_atom_id", index) or atom_value("label_atom_id", index),
            "element": atom_value("type_symbol", index),
            "formal_charge": atom_value("pdbx_formal_charge", index),
            "altloc": atom_value("label_alt_id", index),
            "occupancy": _float(atom_value("occupancy", index)),
            "b_iso": _float(atom_value("B_iso_or_equiv", index)),
            "x": _float(atom_value("Cartn_x", index)),
            "y": _float(atom_value("Cartn_y", index)),
            "z": _float(atom_value("Cartn_z", index)),
        }
        all_rows.append(row)
        deposited_key = row["number"] + row["insertion_code"]
        if row["chain"] == chain and deposited_key == residue_number and row["residue_name"] == "HIS":
            target_rows.append(row)
    if not target_rows:
        return {
            "status": "unavailable",
            "reason": "the author residue identity was not found in the deposited atom_site table",
        }
    ring = [row for row in target_rows if row["atom_name"] in {"ND1", "NE2"}]
    explicit = [
        row for row in target_rows
        if row["element"].upper() in {"H", "D"}
        or row["atom_name"].upper() in {"HD1", "HE2", "DD1", "DE2"}
    ]
    nearby = []
    for other in all_rows:
        if other in target_rows or None in (other["x"], other["y"], other["z"]):
            continue
        distances = [
            math.dist(
                (site["x"], site["y"], site["z"]),
                (other["x"], other["y"], other["z"]),
            )
            for site in ring if None not in (site["x"], site["y"], site["z"])
        ]
        if distances and min(distances) <= 4.0:
            nearby.append({
                key: other[key] for key in (
                    "chain", "number", "insertion_code", "residue_name",
                    "atom_name", "element", "altloc", "occupancy", "b_iso",
                    "formal_charge",
                )
            } | {"distance_to_histidine_ring": round(min(distances), 3)})
    nearby.sort(key=lambda item: item["distance_to_histidine_ring"])

    def values(tag: str) -> list[str]:
        return [item for item in map(_clean, block.find_values(tag)) if item]

    site_rows = []
    site = block.get_mmcif_category("_struct_site_gen.")
    site_count = len(site.get("site_id", []))
    for index in range(site_count):
        def site_value(name: str) -> str:
            column = site.get(name, [])
            return _clean(column[index]) if index < len(column) else ""
        site_chain = site_value("auth_asym_id") or site_value("label_asym_id")
        site_number = site_value("auth_seq_id") or site_value("label_seq_id")
        site_icode = site_value("pdbx_auth_ins_code")
        if site_chain == chain and site_number + site_icode == residue_number:
            site_rows.append({
                "site_id": site_value("site_id"),
                "details": site_value("details"),
            })
    return {
        "status": "available",
        "source": str(source.resolve()),
        "explicit_ring_hydrogens_or_deuteriums": explicit,
        "histidine_atoms": target_rows,
        "nearby_atoms_within_4A": nearby[:40],
        "deposited_site_annotations": site_rows,
        "crystallization_ph": values("_exptl_crystal_grow.pH"),
        "crystallization_ph_range": values("_exptl_crystal_grow.pdbx_pH_range"),
        "crystallization_details": values("_exptl_crystal_grow.pdbx_details"),
        "experimental_method": values("_exptl.method"),
        "xray_resolution_angstrom": values("_refine.ls_d_res_high"),
        "em_resolution_angstrom": values("_em_3d_reconstruction.resolution"),
        "interpretation": (
            "Deposited coordinates and conditions support review but do not by themselves "
            "establish the biologically correct histidine protonation state."
        ),
    }


def read_intervention_record(path: Path) -> dict:
    record = json.loads(path.read_text())
    if record.get("schema_name") != SCHEMA_NAME or record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported receptor-preparation intervention record")
    if record.get("kind") not in {"histidine_template", "review_required"}:
        raise ValueError("Unsupported receptor-preparation intervention kind")
    return record


def decision_from_intervention(path: Path, decision_id: str) -> DecisionRequired | None:
    """Create the bounded decision that the current GUI can safely resolve."""

    record = read_intervention_record(path)
    if record["kind"] != "histidine_template":
        return None
    residue = str(record.get("residue") or "").strip()
    if not residue:
        raise ValueError("Histidine intervention is missing its residue identity")
    deposited = record.get("deposited_mmcif_evidence") or {}
    evidence_notes = []
    explicit_atoms = deposited.get("explicit_ring_hydrogens_or_deuteriums") or []
    if explicit_atoms:
        evidence_notes.append(
            "The deposited atom table includes "
            + ", ".join(str(item.get("atom_name")) for item in explicit_atoms)
            + " for this residue."
        )
    formal_charges = sorted({
        str(item.get("formal_charge"))
        for item in deposited.get("histidine_atoms") or []
        if item.get("formal_charge") not in {None, ""}
    })
    if formal_charges:
        evidence_notes.append(
            "Deposited atom-site formal charge value(s): "
            + ", ".join(formal_charges) + "."
        )
    nearby = deposited.get("nearby_atoms_within_4A") or []
    if nearby:
        evidence_notes.append(
            f"The retained mmCIF review found {len(nearby)} nearby atom record(s) within 4 Å "
            "of ND1 or NE2."
        )
    evidence_summary = " ".join(evidence_notes) or (
        "No explicit ring hydrogen, formal charge, or nearby-atom summary was available from "
        "the deposited mmCIF record."
    )
    evidence_summary_html = html.escape(evidence_summary)
    options = []
    descriptions = {
        "HIE": "Neutral histidine with the proton on NE2.",
        "HID": "Neutral histidine with the proton on ND1.",
        "HIP": "Positively charged histidine with protons on both ring nitrogens.",
    }
    labels = {
        "HIE": "Neutral — hydrogen on NE2 (HIE)",
        "HID": "Neutral — hydrogen on ND1 (HID)",
        "HIP": "Positive — hydrogens on both nitrogens (HIP)",
    }
    for template in ("HIE", "HID", "HIP"):
        options.append(DecisionOption(
            f"{template}_CURRENT", f"{labels[template]} — only {residue}",
            descriptions[template] + " Only the detected residue is assigned.",
            automation_eligible=False,
        ))
    options.append(DecisionOption(
        "TEST_NEUTRAL_CURRENT",
        f"Test both neutral states — only {residue}",
        (
            "Prepare retained HIE and HID receptor variants. After docking-box selection, "
            "boxes that can be influenced by this residue require matched comparison docks."
        ),
        recommended=True,
        automation_eligible=False,
    ))
    if len(record.get("eligible_histidines") or []) > 1:
        for template in ("HIE", "HID", "HIP"):
            options.append(DecisionOption(
                f"{template}_ALL", f"{labels[template]} — all unresolved histidines",
                descriptions[template] + " The same state is applied to every unresolved histidine listed in the retained record.",
                automation_eligible=False,
            ))
    options.append(DecisionOption(
        "STOP", "Stop and review the receptor",
        "Preparation remains stopped. Supply a corrected structure or begin a new study after structural review.",
        automation_eligible=False,
    ))
    return DecisionRequired(
        id=decision_id,
        kind="select_histidine_template",
        prompt=f"How should histidine {residue} be represented?",
        detected=(
            f"Preparation found two or more equally compatible ways to place the ring hydrogen "
            f"on histidine {residue}. Histidine is a standard amino acid; only its hydrogen "
            "placement and charge are unresolved. No state has been assigned yet. "
            + ("Deposited mmCIF context is attached for review."
               if record.get("deposited_mmcif_evidence", {}).get("status") == "available"
               else "No decisive deposited mmCIF assignment is available.")
        ),
        why_stopped=(record.get("scientific_concern") or
                     "The protonation state changes the receptor hydrogen-bonding model."),
        consequences=(
            "The selected template assignment changes the prepared receptor model.",
            "The choice and affected residue identities will be retained in the study audit trail.",
            "Choose Stop when the local structural or catalytic environment has not been reviewed.",
        ),
        options=tuple(options),
        artifact_ids=("preparation-intervention",),
        maximum_selections=1,
        changes_molecular_model=True,
        automation_eligible=False,
        payload=record,
        presentation={
            "guided": (
                "<ol>"
                "<li><b>Check metal coordination first.</b> A nitrogen directly coordinating "
                "a metal normally needs its lone pair and is therefore the unprotonated nitrogen. "
                "Treat this as strong evidence, not an exception-free rule.</li>"
                "<li><b>Inspect hydrogen-bond partners.</b> A nearby donor supports that histidine "
                "nitrogen acting as an acceptor; a nearby acceptor supports that histidine nitrogen "
                "carrying the donated proton. Confirm that the geometry is plausible.</li>"
                "<li><b>Reject steric clashes.</b> Avoid a state that places a ring hydrogen against "
                "another heavy atom. Absence of a clash does not by itself select a state.</li>"
                "<li><b>Stop when the evidence conflicts.</b> Catalytic networks, unusual metal "
                "chemistry, or unresolved alternate conformations require expert review rather "
                "than a forced assignment.</li>"
                "</ol>"
                "<p><b>Name reminder:</b> HIE has H on NE2 and leaves ND1 accepting; HID has H on "
                "ND1 and leaves NE2 accepting; HIP has H on both and is positively charged.</p>"
                f"<p><b>Deposited evidence currently available:</b> {evidence_summary_html}</p>"
            ),
            "background": (
                "HID and HIE are neutral tautomers with different ring nitrogens protonated; "
                "HIP is positively charged. Coordinates alone may not establish the correct state. "
                + evidence_summary_html
            ),
            "technical": (
                "The resumed attempt passes an explicit Meeko --set_template assignment. "
                "The failed attempt is archived before the engine is rerun."
            ),
        },
        continuation={
            "action": "continue_stage",
            "checkpoint": "rerun_preparation_with_histidine_template",
            "terminal_options": ["STOP"],
        },
    )


def template_assignments(record: dict, selection: str) -> str:
    """Translate one validated GUI choice into explicit Meeko assignments."""

    if selection == "STOP":
        return ""
    try:
        template, scope = selection.split("_", 1)
    except ValueError as exc:
        raise ValueError("Invalid histidine intervention selection") from exc
    if template not in {"HIE", "HID", "HIP"} or scope not in {"CURRENT", "ALL"}:
        raise ValueError("Invalid histidine intervention selection")
    residues = (
        [str(item) for item in record.get("eligible_histidines") or []]
        if scope == "ALL" else [str(record.get("residue") or "")]
    )
    if not residues or any(not item for item in residues):
        raise ValueError("Histidine intervention lacks explicit residue identities")
    return ",".join(f"{residue}={template}" for residue in residues)


def neutral_sensitivity_assignments(record: dict, selection: str) -> dict[str, str]:
    """Return the two explicit Meeko assignments for a bounded sensitivity request."""

    if selection != "TEST_NEUTRAL_CURRENT":
        raise ValueError("Invalid histidine sensitivity selection")
    residue = str(record.get("residue") or "").strip()
    if not residue:
        raise ValueError("Histidine intervention lacks an explicit residue identity")
    return {
        "HIE": f"{residue}=HIE",
        "HID": f"{residue}=HID",
    }


def classify_histidine_affected_boxes(
    receptor_pdb: Path,
    residue: str,
    selected_box_ids: Iterable[str],
    artifacts: Iterable[object],
    *,
    margin_angstrom: float = 4.0,
) -> dict:
    """Classify selected axis-aligned boxes conservatively from retained coordinates."""

    if margin_angstrom < 0 or not math.isfinite(margin_angstrom):
        raise ValueError("The receptor-state influence margin must be finite and non-negative")
    chain, separator, number = residue.partition(":")
    if not separator or not chain or not number:
        raise ValueError("Histidine residue identity must use chain:number form")
    coordinates = []
    if receptor_pdb.is_file():
        for line in receptor_pdb.read_text(errors="replace").splitlines():
            if not line.startswith(("ATOM  ", "HETATM")):
                continue
            deposited_number = line[22:26].strip() + line[26:27].strip()
            if line[21:22].strip() != chain or deposited_number != number:
                continue
            try:
                coordinates.append(tuple(float(line[start:end]) for start, end in (
                    (30, 38), (38, 46), (46, 54),
                )))
            except ValueError:
                continue

    selected = list(dict.fromkeys(map(str, selected_box_ids)))
    geometry_by_label = {}
    for artifact in artifacts:
        metadata = getattr(artifact, "metadata", {}) or {}
        label = str(metadata.get("label") or "")
        if getattr(artifact, "kind", None) == "docking_box" and label in selected:
            geometry_by_label[label] = metadata.get("geometry") or {}

    affected = []
    unaffected = []
    details = []
    conservative_reason = None
    if not coordinates:
        affected = selected
        conservative_reason = "The prepared receptor does not expose coordinates for the ambiguous residue."
    else:
        for label in selected:
            geometry = geometry_by_label.get(label)
            try:
                center = tuple(float(geometry[f"center_{axis}"]) for axis in "xyz")
                half_size = tuple(float(geometry[f"size_{axis}"]) / 2.0 for axis in "xyz")
            except (KeyError, TypeError, ValueError):
                affected.append(label)
                details.append({"box": label, "affected": True, "reason": "box geometry unavailable"})
                continue
            inside = any(all(
                abs(point[index] - center[index]) <= half_size[index] + margin_angstrom
                for index in range(3)
            ) for point in coordinates)
            (affected if inside else unaffected).append(label)
            details.append({
                "box": label,
                "affected": inside,
                "reason": (
                    f"residue atom lies within the box or {margin_angstrom:g} Å influence margin"
                    if inside else
                    f"all residue atoms lie outside the {margin_angstrom:g} Å influence margin"
                ),
            })
    return {
        "status": "conservative_all_affected" if conservative_reason else "classified",
        "residue": residue,
        "margin_angstrom": margin_angstrom,
        "affected_boxes": affected,
        "unaffected_boxes": unaffected,
        "details": details,
        "conservative_reason": conservative_reason,
    }
