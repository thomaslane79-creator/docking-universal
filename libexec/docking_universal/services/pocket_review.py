"""Build a durable pocket-selection decision from retained real artifacts."""

from __future__ import annotations

import csv
import copy
import hashlib
import json
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docking_universal_box_candidates import config_geometry, grouped_fpocket_boxes
from docking_universal_region import write_box_files

from ..application import StudyController
from ..automation import AutomationPolicy
from ..decisions import DecisionRequired
from ..models import ArtifactRecord, PocketCandidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ordered_pocket_boxes(cavity: Path | str) -> list[Path]:
    cavity = Path(cavity)
    retained_file = cavity / "selected_pocket_records.txt"
    retained_numbers = set()
    if retained_file.is_file():
        for line in retained_file.read_text(errors="replace").splitlines():
            fields = line.split("|", 2)
            if len(fields) < 2:
                continue
            match = re.search(r"pocket(\d+)_atm\.pdb$", fields[1])
            if match:
                retained_numbers.add(int(match.group(1)))
    numbered = []
    for path in cavity.glob("*.conf"):
        match = re.search(r"_pocket(\d+)\.conf$", path.name)
        if match and (not retained_numbers or int(match.group(1)) in retained_numbers):
            numbered.append((int(match.group(1)), path))
    return [path for _, path in sorted(numbered, key=lambda item: (item[0], item[1].name))]


def _safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "site"


def _shared_group_ligands_in_representative_box(state, candidate):
    """Recover verified legacy grouping evidence without changing the saved study."""
    from ..pocket_sites import ligand_coordinates, ligand_fits
    from .molecule_inspection import is_supporting_component_observation
    evidence = candidate.get('evidence') or {}
    group = evidence.get('site_group') or evidence.get('site_group_presentation') or {}
    hashes = {digest for relation in group.get('relationships', [])
              for digest in relation.get('ligand_sha256s', [])}
    grouping = (state.workflow_data.get('pocket_site_grouping')
                or state.workflow_data.get('pocket_site_presentation') or {})
    originals = grouping.get('original_candidates') or []
    if not hashes or not originals:
        return []
    artifacts = {str(Path(a.path).resolve()): a for a in state.artifacts if a.kind == 'aligned_ligand'}
    box = next((a for a in state.artifacts if a.id == candidate.get('box_artifact_id')), None)
    if box is None:
        return []
    try:
        if not box.sha256 or _sha256(Path(box.path)) != box.sha256:
            return []
        geometry = config_geometry(Path(box.path))
    except (OSError, ValueError, KeyError):
        return []
    found = {}
    for source in originals:
        observations = ((source.get('evidence') or {}).get('experimental_ligand_evidence') or {}).get('observations') or []
        for observation in observations:
            if is_supporting_component_observation(observation):
                continue
            try:
                path = Path(observation['aligned_ligand_pdb']).resolve()
                artifact = artifacts[str(path)]
                if artifact.sha256 not in hashes or _sha256(path) != artifact.sha256:
                    continue
                inside = ligand_fits(ligand_coordinates(path), geometry)
            except (OSError, KeyError, ValueError, TypeError):
                continue
            identity = (str(observation.get('source_ligand_id') or path), artifact.sha256)
            relationships = [f"{relation.get('left')}/{relation.get('right')}"
                             for relation in group.get('relationships', [])
                             if artifact.sha256 in relation.get('ligand_sha256s', [])]
            found.setdefault(identity, {**observation,
                'evidence_role': 'shared_grouping_ligand_in_box' if inside else 'shared_grouping_ligand_outside_box',
                'original_evidence_site': source.get('id'), 'supporting_relationships': relationships})
    return list(found.values())


_INPUT_LIGAND_CACHE = {}


def _related_ligands_in_box(state, candidate):
    """Project verified related-structure ligands by their coordinates, not pocket assignment."""
    from .molecule_inspection import is_supporting_component_observation
    from ..pocket_sites import ligand_coordinates, ligand_fits
    grouping = state.workflow_data.get('pocket_site_grouping') or state.workflow_data.get('pocket_site_presentation') or {}
    originals = grouping.get('original_candidates') or state.workflow_data.get('pocket_candidates') or []
    artifacts = getattr(state, 'artifacts', ())
    box = next((a for a in artifacts if a.id == candidate.get('box_artifact_id')), None)
    if box is None or not originals:
        return []
    try:
        if not box.sha256 or _sha256(Path(box.path)) != box.sha256:
            return []
        geometry = config_geometry(Path(box.path))
    except (OSError, ValueError, KeyError):
        return []
    index = getattr(state, '_related_ligand_box_index', None)
    if index is None:
        assets = {str(Path(a.path).resolve()): a for a in artifacts if a.kind == 'aligned_ligand'}
        index, seen = [], set()
        for source in originals:
            observations = ((source.get('evidence') or {}).get('experimental_ligand_evidence') or {}).get('observations') or []
            for observation in observations:
                if is_supporting_component_observation(observation):
                    continue
                try:
                    path = Path(observation['aligned_ligand_pdb']).resolve()
                    asset = assets[str(path)]
                    key = (str(observation.get('source_ligand_id') or path), asset.sha256)
                    if key in seen or not asset.sha256 or _sha256(path) != asset.sha256:
                        continue
                    points = ligand_coordinates(path)
                    bounds = tuple((min(p[i] for p in points), max(p[i] for p in points)) for i in range(3))
                    index.append((bounds, path, asset.sha256, path.stat().st_mtime_ns,
                                  {**observation, 'evidence_role': 'related_ligand_in_box',
                                   'original_evidence_site': source.get('id')}))
                    seen.add(key)
                except (OSError, KeyError, ValueError, TypeError):
                    continue
        state._related_ligand_box_index = index
    result = []
    for bounds, path, digest, mtime, observation in index:
        if not all(low >= geometry['center_' + axis] - geometry['size_' + axis] / 2 and
                   high <= geometry['center_' + axis] + geometry['size_' + axis] / 2
                   for (low, high), axis in zip(bounds, 'xyz')):
            continue
        try:
            if path.stat().st_mtime_ns == mtime and _sha256(path) == digest:
                result.append(observation)
        except OSError:
            continue
    return result


def _other_input_ligands(state, selected):
    """Extract eligible deposited instances for presentation, preserving provenance.

    These are observations inside a search box, not proof of a predicted
    cavity or a replacement for the selected pose-recovery reference.
    """
    artifacts = getattr(state, 'artifacts', ())
    source = next((a for a in artifacts if a.kind == 'source_receptor_structure'), None)
    normalized = next((a for a in artifacts if a.kind == 'normalized_receptor_input'), None)
    if not source or not normalized or not source.sha256 or not normalized.sha256:
        return []
    try:
        stats = tuple((Path(a.path).stat().st_mtime_ns, Path(a.path).stat().st_size)
                      for a in (source, normalized, selected))
    except OSError:
        return []
    key = (source.path, source.sha256, normalized.path, normalized.sha256, selected.sha256, stats)
    cached = getattr(state, '_input_ligand_observations', None)
    if cached and cached[0] == key:
        return cached[1]
    if key in _INPUT_LIGAND_CACHE:
        return _INPUT_LIGAND_CACHE[key]
    from .molecule_inspection import input_molecules
    try:
        if _sha256(Path(source.path)) != source.sha256 or _sha256(Path(normalized.path)) != normalized.sha256:
            return []
        entries = [item for item in input_molecules(source.path)
                   if item.get('kind') == 'component' and not item.get('supporting_component')]
        selected_lines = Path(selected.path).read_text().splitlines()
        selected_ids = {(line[17:20].strip(), line[21:22].strip() or '_',
                         line[22:26].strip(), line[26:27].strip()) for line in selected_lines
                        if line.startswith(('ATOM  ', 'HETATM'))}
        by_id = {}
        for line in Path(normalized.path).read_text().splitlines():
            if line.startswith('ENDMDL'):
                break
            if line.startswith(('ATOM  ', 'HETATM')):
                identity = (line[17:20].strip(), line[21:22].strip() or '_',
                            line[22:26].strip(), line[26:27].strip())
                by_id.setdefault(identity, []).append(line)
        directory = Path(tempfile.mkdtemp(prefix='docking-input-ligands-'))
        observations = []
        for entry in entries:
            identity = (entry['resname'], entry['chain'] or '_', entry['residue_number'], entry['insertion_code'])
            all_lines = by_id.get(identity, [])
            if identity in selected_ids or not all_lines:
                continue
            altlocs = sorted({line[16:17].strip() for line in all_lines if line[16:17].strip()}) or ['']
            for altloc in altlocs:
                lines = [line for line in all_lines if not line[16:17].strip() or line[16:17].strip() == altloc]
                atoms = [tuple(float(line[i:i + 8]) for i in (30, 38, 46)) for line in lines
                         if line[76:78].strip().upper() not in {'H', 'D'}]
                if not atoms or not all(math.isfinite(v) for xyz in atoms for v in xyz):
                    continue
                path = directory / (hashlib.sha256(repr((identity, altloc)).encode()).hexdigest() + '.pdb')
                path.write_text('\n'.join(lines) + '\nEND\n')
                observations.append((atoms, {'evidence_class': 'input_structure', 'entry': 'Input',
                'ligand': f'{identity[0]} {identity[1]}:{identity[2]}{identity[3]}' + (f' (alt {altloc})' if altloc else ''),
                'aligned_ligand_pdb': str(path), 'ligand_sha256': _sha256(path),
                'source_ligand_id': 'input/' + '/'.join((identity[0], identity[1], identity[2] + identity[3])),
                'altloc': altloc,
                'source': 'input_structure', 'evidence_role': 'input ligand inside docking box; not proof of a predicted pocket',
                'deposited_source': normalized.path, 'deposited_source_sha256': normalized.sha256,
                'component_source': source.path, 'component_source_sha256': source.sha256}))
        state._input_ligand_observations = (key, observations)
        if len(_INPUT_LIGAND_CACHE) >= 8:
            _INPUT_LIGAND_CACHE.pop(next(iter(_INPUT_LIGAND_CACHE)))
        _INPUT_LIGAND_CACHE[key] = observations
        return observations
    except (OSError, ValueError, KeyError):
        return []


def candidate_with_input_ligand_evidence(state, candidate, *, boundary_tolerance=.25, include_box_related=True):
    """Project retained local ligand evidence without rewriting saved science.

    Also works for older studies. Verify both retained assets and require the
    entire selected ligand to fit (0.25 Å boundary tolerance). Local observations
    remain separate from related-PDB evidence and never grant control authority.
    """
    if candidate is None:
        return None
    group = (candidate.get('evidence') or {}).get('site_group') or (candidate.get('evidence') or {}).get('site_group_presentation')
    if group and not (candidate.get('evidence') or {}).get('conformational_site_evidence'):
        from ..pocket_sites import merged_site_conformation
        conformation = merged_site_conformation(group)
        if conformation:
            candidate = {**candidate, 'evidence': dict(candidate.get('evidence') or {})}
            candidate['evidence']['conformational_site_evidence'] = conformation
    shared = _shared_group_ligands_in_representative_box(state, candidate) if group else []
    if shared:
        candidate = {**candidate, 'evidence': dict(candidate.get('evidence') or {})}
        candidate['evidence']['grouping_ligand_evidence'] = {
            'observations': [item for item in shared if item['evidence_role'] == 'shared_grouping_ligand_outside_box'],
            'decision_role': 'grouping evidence outside selected box; not evidence inside this box',
        }
        original = candidate['evidence'].get('experimental_ligand_evidence') or {}
        related = list(original.get('observations') or [])
        seen = {(str(item.get('source_ligand_id') or ''), str(item.get('aligned_ligand_pdb') or '')) for item in related}
        for item in shared:
            if item['evidence_role'] != 'shared_grouping_ligand_in_box':
                continue
            key = (str(item.get('source_ligand_id') or ''), str(item.get('aligned_ligand_pdb') or ''))
            if key not in seen:
                related.append(item)
                seen.add(key)
        classes = {}
        for item in related:
            kind = item.get('evidence_class') or 'unclassified'
            classes[kind] = classes.get(kind, 0) + 1
        candidate['evidence']['experimental_ligand_evidence'] = {
            **original, 'observations': related, 'observation_count': len(related),
            'pdb_entry_count': len({item.get('entry') for item in related if item.get('entry')}),
            'evidence_class_counts': classes,
        }
    inside_related = _related_ligands_in_box(state, candidate) if include_box_related else []
    if inside_related:
        candidate = {**candidate, 'evidence': dict(candidate.get('evidence') or {})}
        existing = candidate['evidence'].get('experimental_ligand_evidence') or {}
        related = list(existing.get('observations') or [])
        seen = {(str(item.get('source_ligand_id') or ''), str(item.get('aligned_ligand_pdb') or '')) for item in related}
        for item in inside_related:
            key = (str(item.get('source_ligand_id') or ''), str(item.get('aligned_ligand_pdb') or ''))
            if key not in seen:
                related.append(item)
                seen.add(key)
        classes = {}
        for item in related:
            kind = item.get('evidence_class') or 'unclassified'
            classes[kind] = classes.get(kind, 0) + 1
        candidate['evidence']['experimental_ligand_evidence'] = {
            **existing, 'observations': related, 'observation_count': len(related),
            'pdb_entry_count': len({item.get('entry') for item in related if item.get('entry')}),
            'evidence_class_counts': classes}
    artifacts = getattr(state, 'artifacts', ())
    ligand = next((a for a in artifacts if a.kind == 'bound_ligand'), None)
    if ligand is None:
        return candidate
    # Only add a presentation field. Large retained evidence is read-only and
    # may be shared; copying all residue comparisons stalls the GUI.
    result = {**candidate, 'evidence': dict(candidate.get('evidence') or {})}
    evidence = result['evidence']
    local = {'observation_count': 0, 'observations': [], 'source': 'input_structure',
             'decision_role': 'site evidence only; not independent control validation'}
    evidence['input_ligand_evidence'] = local
    try:
        box = next(a for a in artifacts if a.id == candidate.get('box_artifact_id'))
        for asset in (ligand, box):
            if not asset.sha256 or _sha256(Path(asset.path)) != asset.sha256:
                raise ValueError('Retained input ligand or docking box changed')
        geometry = config_geometry(Path(box.path))
        if any(not math.isfinite(value) for value in geometry.values()) or any(
                geometry['size_' + axis] <= 0 for axis in 'xyz'):
            raise ValueError('Invalid retained box geometry')
        atoms, identities = [], set()
        for line in Path(ligand.path).read_text().splitlines():
            if not line.startswith(('ATOM  ', 'HETATM')) or line[76:78].strip().upper() in {'H', 'D'}:
                continue
            identities.add((line[17:20].strip(), line[21:22].strip() or '_',
                            line[22:26].strip(), line[26:27].strip()))
            xyz = tuple(float(line[start:start + 8]) for start in (30, 38, 46))
            if not all(math.isfinite(value) for value in xyz):
                raise ValueError('Nonfinite retained ligand coordinates')
            atoms.append(xyz)
        if not atoms or len(identities) != 1:
            raise ValueError('Retained input ligand lacks one exact heavy-atom identity')
        identity = next(iter(identities))
        inside = sum(all(abs(value - geometry['center_' + axis]) <= geometry['size_' + axis] / 2 + boundary_tolerance
                         for axis, value in zip('xyz', xyz)) for xyz in atoms)
        clearance = min(geometry['size_' + axis] / 2 - abs(value - geometry['center_' + axis])
                        for xyz in atoms for axis, value in zip('xyz', xyz))
        local.update(status='verified', heavy_atom_count=len(atoms), heavy_atoms_inside=inside,
                     all_heavy_atoms_inside=inside == len(atoms), boundary_tolerance_angstrom=boundary_tolerance,
                     minimum_face_clearance_angstrom=clearance,
                     ligand_sha256=ligand.sha256, box_sha256=box.sha256)
        if inside == len(atoms):
            local['observations'] = [{'evidence_class': 'input_structure', 'entry': 'Input',
                'ligand': f'{identity[0]} {identity[1]}:{identity[2]}{identity[3]}',
                'aligned_ligand_pdb': str(Path(ligand.path).resolve()),
                'source_ligand_id': 'input/' + '/'.join((identity[0], identity[1], identity[2] + identity[3])),
                'source': 'input_structure', 'ligand_sha256': ligand.sha256}]
            local['observation_count'] = 1
            # Preserve the original source and its normalized coordinate file
            # so the exact input ligand can be analyzed without a PDB lookup.
            normalized = next((a for a in artifacts if a.kind == 'normalized_receptor_input'), None)
            deposited = next((a for a in artifacts if a.kind == 'source_receptor_structure'), None)
            if normalized and deposited:
                local['observations'][0].update(
                    deposited_source=normalized.path, deposited_source_sha256=normalized.sha256,
                    component_source=deposited.path, component_source_sha256=deposited.sha256)
        for other_atoms, observation in _other_input_ligands(state, ligand):
            if all(all(abs(value - geometry['center_' + axis]) <= geometry['size_' + axis] / 2 + boundary_tolerance
                       for axis, value in zip('xyz', xyz)) for xyz in other_atoms):
                local.setdefault('additional_observations', []).append(observation)
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        local.update(status='unverified', detail=str(exc))
    return result


def input_ligand_candidate(target: str, cavity: Path, setup: dict[str, Any]) -> dict[str, Any]:
    """Retain the exact input ligand independently of any detector or network.

    Use the ligand-centroid 26 Å box policy, expanding individual axes if
    needed to enclose a large ligand plus 4 Å. This is not cavity geometry.
    """
    source = Path(setup["input_pdb"])
    identity = (setup["ligand_resname"], setup["ligand_chain_id"], str(setup["ligand_residue_number"]),
                setup.get("ligand_insertion_code") or "")
    altloc = setup.get("ligand_altloc") or ""
    lines, coordinates = [], []
    for line in source.read_text().splitlines():
        if not line.startswith("HETATM") or (
            line[17:20].strip(), line[21:22].strip() or "_", line[22:26].strip(), line[26:27].strip()
        ) != identity:
            continue
        if line[16:17].strip() and line[16:17].strip() != altloc:
            if not altloc:
                raise ValueError("Choose one alternate location for the bound-ligand site")
            continue
        element = line[76:78].strip().upper() or line[12:16].strip().lstrip("0123456789")[:1].upper()
        if element in {"H", "D"}:
            continue
        coordinates.append(tuple(float(line[start:start + 8]) for start in (30, 38, 46)))
        lines.append(line)
    if not coordinates:
        raise ValueError("The exact selected input ligand is unavailable for bound-site review")
    geometry = {}
    for axis, values in zip("xyz", zip(*coordinates)):
        center = sum(values) / len(values)
        geometry[f"center_{axis}"] = center
        geometry[f"size_{axis}"] = max(26., 2 * max(abs(value - center) for value in values) + 8.)
    ligand_path = cavity / f"{target}_input_bound_ligand.pdb"
    ligand_path.write_text("\n".join(lines) + "\nEND\n")
    box = write_box_files(cavity / f"{target}_bound_ligand.conf", geometry)
    return {"label": "B1", "path": box,
            "description": f"input bound-ligand site: {identity[0]} {identity[1]}:{identity[2]}{identity[3]} (not a predicted pocket)",
            "evidence": {"kind": "ligand_defined", "source": "input_bound_ligand", "automation_eligible": True,
                         "input_structure_sha256": setup.get("input_structure_sha256"),
                         "input_ligand_identity": dict(zip(("resname", "chain_id", "residue_number", "insertion_code"), identity)),
                         "input_ligand_reference": str(ligand_path.resolve()),
                         "evidence_role": "input site definition only; not independent supporting evidence"}}


def _pocket_coordinate_paths(cavity: Path, label: str) -> list[Path]:
    numbers = [int(value) for value in re.findall(r"P(\d+)", label)]
    paths = []
    for number in numbers:
        matches = sorted(cavity.rglob(f"pocket{number}_atm.pdb"))
        if matches:
            paths.append(matches[0].resolve())
    return paths


def _conformational_site_evidence(
    groups: list[dict[str, Any]], conformational: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return box-review evidence tied to the groups' deposited ligands."""
    from .molecule_inspection import is_supporting_component_observation
    source_ids = {
        member.get("source_ligand_id")
        for group in groups for member in group.get("members", [])
        if member.get("source_ligand_id") and not is_supporting_component_observation(member)
    }
    observations = []
    for observation in (conformational or {}).get("observations", []):
        matched = [
            item for item in observation.get("known_ligand_accessibility", [])
            if item.get("source_ligand_id") in source_ids
        ]
        if matched:
            observations.append({
                "residue": observation.get("residue"),
                "entry": observation.get("entry"),
                "alignment_id": observation.get("alignment_id"),
                "maximum_chi_difference_degrees": observation.get("maximum_chi_difference_degrees"),
                "side_chain_rmsd_angstrom": observation.get("side_chain_rmsd_angstrom"),
                "backbone_rmsd_angstrom": observation.get("backbone_rmsd_angstrom"),
                "ligands": matched,
            })
    occluding = [
        item for observation in observations for item in observation["ligands"]
        if item.get("consistent_with_side_chain_occlusion")
    ]
    residues = []
    for observation in observations:
        if any(item.get("consistent_with_side_chain_occlusion") for item in observation["ligands"]):
            residue = observation.get("residue")
            if residue and residue not in residues:
                residues.append(residue)
    return {
        "status": (
            "conformationally_incompatible" if occluding
            else "reviewed_no_geometric_incompatibility" if observations
            else "not_evaluated"
        ),
        "box_decision_warning": (
            "A deposited ligand placement conflicts with the current receptor conformation. "
            "An alternate side-chain conformation may restrict site accessibility or help explain "
            "a missing/reduced predicted cavity; this is supporting evidence, not proof of flexibility. "
            "Rigid docking in this box may not be a legitimate test."
            if occluding else None
        ),
        "occluding_residues": residues,
        "observation_count": len(observations),
        "observations": observations,
        "decision_role": "evidence_for_box_review_only",
    }


def _experimental_site_evidence(
    groups: list[dict[str, Any]], pocket_evidence: dict[str, Any] | None, evidence_root: Path,
) -> dict[str, Any]:
    """Compact, auditable deposited-ligand observations for one candidate."""
    source_ids = {
        member.get("source_ligand_id")
        for group in groups for member in group.get("members", [])
        if member.get("source_ligand_id")
    }
    records = []
    for item in (pocket_evidence or {}).get("evidence", []):
        if item.get("source_ligand_id") not in source_ids:
            continue
        aligned = evidence_root / str(item.get("aligned_ligand_pdb", ""))
        records.append({
            "source_ligand_id": item.get("source_ligand_id"),
            "entry": item.get("entry"), "ligand": item.get("ligand"),
            "evidence_class": item.get("evidence_class"),
            "sequence_identity": item.get("sequence_identity"),
            "query_coverage": item.get("query_coverage"),
            "ca_rmsd_angstrom": item.get("ca_rmsd_angstrom"),
            "aligned_ligand_pdb": str(aligned.resolve()) if aligned.is_file() else None,
        })
    from .molecule_inspection import split_component_observations
    records, supporting = split_component_observations(records)
    classes: dict[str, int] = {}
    for item in records:
        key = str(item.get("evidence_class") or "unclassified")
        classes[key] = classes.get(key, 0) + 1
    rmsds = [item["ca_rmsd_angstrom"] for item in records if isinstance(item.get("ca_rmsd_angstrom"), (int, float))]
    return {
        "observation_count": len(records),
        "pdb_entry_count": len({item["entry"] for item in records if item.get("entry")}),
        "ligand_count": len({item["ligand"] for item in records if item.get("ligand")}),
        "evidence_class_counts": classes,
        "minimum_ca_rmsd_angstrom": min(rmsds) if rmsds else None,
        "maximum_ca_rmsd_angstrom": max(rmsds) if rmsds else None,
        "observations": records,
        "supporting_components": {"observation_count": len(supporting), "observations": supporting,
                                  "decision_role": "supporting_components_not_ligand_evidence"},
        "decision_role": "evidence_for_box_review_only",
    }


def build_labeled_candidate_mappings(
    target: str,
    boxes: list[Path],
    pocket_evidence: dict[str, Any] | None,
    cavity: Path | str,
    *, include_predicted: bool = True,
) -> list[dict[str, Any]]:
    """Create the same selectable P#, consolidated P#/P#, and L# boxes."""
    cavity = Path(cavity)
    candidates: list[dict[str, Any]] = []
    provenance_path = cavity / "pocket_detection_provenance.json"
    provenance = json.loads(provenance_path.read_text()) if provenance_path.is_file() else {}
    detector = provenance.get("engine", "fpocket")
    equivalence_by_pocket: dict[int, list[dict[str, Any]]] = {}
    for equivalence in provenance.get("pocket_equivalences", []):
        for number in equivalence.get("pockets", []):
            equivalence_by_pocket.setdefault(int(number), []).append(equivalence)
    ligand_groups = (pocket_evidence or {}).get("ligand_site_groups") or []
    evidence_root = cavity / "pdb_site_evidence"
    conformational = (pocket_evidence or {}).get("_conformational_evidence")
    groups_by_pocket: dict[str, list[dict[str, Any]]] = {}
    for group in ligand_groups:
        pocket = (group.get("pocket_recovery") or group.get("fpocket_recovery") or {}).get("best_matching_pocket")
        if pocket:
            groups_by_pocket.setdefault(str(pocket), []).append(group)
    available = {path.resolve() for path in boxes}
    for fallback_index, path in enumerate(ordered_pocket_boxes(cavity) if include_predicted else (), 1):
        if available and path.resolve() not in available:
            continue
        match = re.search(r"_pocket(\d+)\.conf$", path.name)
        number = int(match.group(1)) if match else fallback_index
        supporting = groups_by_pocket.get(str(number), [])
        description = f"individual {detector} pocket box"
        sizing = (provenance.get("box_sizing") or {}).get(f"P{number}", {})
        if sizing.get("basis") == "p2rank_surface_atoms":
            description = "P2Rank box around the pocket-lining atoms"
        elif sizing.get("basis") == "prediction_center_default":
            description = "Default box at the prediction center. Pocket extent unavailable."
        related_record = _experimental_site_evidence(supporting, pocket_evidence, evidence_root)
        if related_record['observation_count']:
            description += "; direct deposited-ligand correspondence recorded"
        elif related_record['supporting_components']['observation_count']:
            description += "; supporting components observed (not ligand evidence)"
        equivalences = equivalence_by_pocket.get(number, [])
        if equivalences:
            equivalence_phrases = []
            for item in equivalences:
                peers = [int(peer) for peer in item.get("pockets", []) if int(peer) != number]
                rmsd = item.get("fitted_pocket_atom_rmsd_angstrom")
                chain_text = "/".join(str(chain) for chain in item.get("chains", []) if chain)
                for peer in peers:
                    detail = f"fitted pocket RMSD {rmsd:g} Å" if isinstance(rmsd, (int, float)) else "low fitted pocket RMSD"
                    if chain_text:
                        detail += f"; chains {chain_text}"
                    equivalence_phrases.append(
                        f"probable symmetry-related pocket copy of P{peer} ({detail}); "
                        "both sites may be relevant in the physiological assembly"
                    )
            description += "; " + "; ".join(equivalence_phrases)
        candidates.append({
            "label": f"P{number}",
            "path": path,
            "description": description,
            "evidence": {
                "kind": detector,
                "detector": detector,
                **({"box_sizing": sizing} if sizing else {}),
                "direct_ligand_site_groups": len(supporting),
                "pocket_equivalences": equivalences,
                "symmetry_equivalence_shown_in_box_selection": bool(equivalences),
                "conformational_site_evidence": _conformational_site_evidence(supporting, conformational),
                "experimental_ligand_evidence": related_record,
                "automation_eligible": True,
            },
        })

    diagnostics = cavity / "pocket_selection_diagnostics.tsv"
    if include_predicted and detector != 'p2rank' and diagnostics.is_file():
        with diagnostics.open(newline="") as handle:
            retained = [
                row for row in csv.DictReader(handle, delimiter="\t")
                if row.get("decision") == "selected"
            ]
        retained.sort(key=lambda row: int(row.get("rank_order", 999999)))
        displayed_files = [row.get("pocket_file", "") for row in retained[:3]]
        for group in grouped_fpocket_boxes(diagnostics, retained, displayed_files):
            if len(group["numbers"]) < 2:
                continue
            label = "/".join(f"P{number}" for number in group["numbers"])
            path = write_box_files(
                cavity / f"{target}_consolidated_{label.replace('/', '-')}.conf",
                group["geometry"],
            )
            candidates.append({
                "label": label,
                "path": path,
                "description": f"consolidated box spanning the named overlapping {detector} pockets",
                "evidence": {"kind": f"consolidated_{detector}", "detector": detector, "automation_eligible": True},
            })

    for group in ligand_groups:
        identity = group.get("site_identity") or {}
        matching_pocket = (group.get("pocket_recovery") or group.get("fpocket_recovery") or {}).get("best_matching_pocket")
        if matching_pocket and include_predicted:
            continue
        label = identity.get("canonical_label", f"L{group.get('site_number', '?')}")
        path = write_box_files(
            cavity / f"{target}_evidence_{_safe_label(label)}.conf",
            group["box"],
        )
        related_record = _experimental_site_evidence([group], pocket_evidence, evidence_root)
        classes = related_record.get("evidence_class_counts") or {}
        requires_homolog_approval = bool(classes.get("close_structural_homolog"))
        candidates.append({
            "label": label,
            "path": path,
            "description": ("supporting-component location; not ligand evidence" if not related_record['observation_count'] and related_record['supporting_components']['observation_count'] else
                            f"ligand-defined box without a corresponding {detector} cavity" if include_predicted
                            else "ligand-defined box from independent related-structure evidence; pocket prediction not requested"),
            "requires_homolog_approval": requires_homolog_approval,
            "evidence": {
                "kind": "ligand_defined",
                "evidence_class_counts": classes,
                "automation_eligible": not requires_homolog_approval,
                "conformational_site_evidence": _conformational_site_evidence([group], conformational),
                "experimental_ligand_evidence": related_record,
            },
        })
    return candidates


@dataclass(frozen=True)
class PocketReviewInputs:
    target: str
    cavity_directory: Path
    boxes: tuple[Path, ...]
    pocket_evidence_record: Path | None = None
    review_scene: Path | None = None
    bound_ligand_setup: dict[str, Any] | None = None


class PocketReviewService:
    """Translate retained cavity evidence into a UI-independent decision."""

    def __init__(self, controller: StudyController):
        self.controller = controller

    def start(
        self,
        study_id: str,
        inputs: PocketReviewInputs,
        *,
        automation: AutomationPolicy | None = None,
    ) -> DecisionRequired:
        cavity = Path(inputs.cavity_directory)
        if not cavity.is_dir():
            raise FileNotFoundError(f"Cavity directory does not exist: {cavity}")
        missing = [str(path) for path in inputs.boxes if not Path(path).is_file()]
        if missing:
            raise FileNotFoundError("Missing retained docking box(es): " + ", ".join(missing))
        evidence: dict[str, Any] = {}
        if inputs.pocket_evidence_record:
            evidence_path = Path(inputs.pocket_evidence_record)
            if not evidence_path.is_file():
                raise FileNotFoundError(f"Pocket evidence record does not exist: {evidence_path}")
            evidence = json.loads(evidence_path.read_text())
            conformational_value = (
                evidence.get("structural_ensemble") or {}
            ).get("conformational_evidence")
            if conformational_value:
                conformational_path = evidence_path.parent / conformational_value
                if conformational_path.is_file():
                    evidence["_conformational_evidence"] = json.loads(conformational_path.read_text())

        mappings = build_labeled_candidate_mappings(
            inputs.target,
            [Path(path) for path in inputs.boxes],
            evidence,
            cavity,
            include_predicted=not (inputs.bound_ligand_setup and not inputs.bound_ligand_setup.get("predict_pockets_with_ligand")),
        )
        if inputs.bound_ligand_setup:
            bound = input_ligand_candidate(inputs.target, cavity, inputs.bound_ligand_setup)
            # Retain every original box. The shared site grouping chooses one
            # exact geometry and preserves the others as inspectable sources.
            mappings.append(bound)
        if not mappings:
            raise ValueError("No selectable pocket candidates could be built from the retained artifacts")

        artifacts: list[ArtifactRecord] = []
        if inputs.bound_ligand_setup:
            ligand_path = cavity / f"{inputs.target}_input_bound_ligand.pdb"
            artifacts.append(ArtifactRecord("input-bound-ligand", "bound_ligand", str(ligand_path.resolve()),
                                            _sha256(ligand_path), "Exact input ligand retained without fitting"))
        candidates: list[PocketCandidate] = []
        for rank, item in enumerate(mappings, 1):
            path = Path(item["path"]).resolve()
            artifact_id = f"pocket-box-{_safe_label(item['label'])}"
            artifacts.append(ArtifactRecord(
                id=artifact_id,
                kind="docking_box",
                path=str(path),
                sha256=_sha256(path),
                description=item["description"],
                metadata={"label": item["label"], "geometry": config_geometry(path)},
            ))
            candidate_evidence = dict(item.get("evidence") or {})
            viewer_artifact_ids = []
            for pocket_path in _pocket_coordinate_paths(cavity, item["label"]):
                pocket_id = f"pocket-coordinates-{pocket_path.stem}"
                if pocket_id not in {artifact.id for artifact in artifacts}:
                    artifacts.append(ArtifactRecord(
                        id=pocket_id,
                        kind="pocket_coordinates",
                        path=str(pocket_path),
                        sha256=_sha256(pocket_path),
                        description=f"PyMOL coordinates for {item['label']}",
                        metadata={"candidate_label": item["label"]},
                    ))
                viewer_artifact_ids.append(pocket_id)
            candidate_evidence.update({
                "geometry": config_geometry(path),
                "requires_homolog_approval": item.get("requires_homolog_approval", False),
                "viewer_artifact_ids": viewer_artifact_ids,
            })
            candidates.append(PocketCandidate(
                id=item["label"],
                label=item["label"],
                rank=rank,
                box_artifact_id=artifact_id,
                summary=item["description"],
                evidence=candidate_evidence,
            ))

        review_ids = [artifact.id for artifact in artifacts]
        for artifact in self._supporting_artifacts(inputs, evidence):
            artifacts.append(artifact)
            review_ids.append(artifact.id)
        # Pin aligned ligand files themselves, in addition to their source
        # evidence record. Complete-ligand grouping and later expansion must
        # recheck exactly these coordinates at approval time.
        retained_paths = {a.path for a in artifacts}
        for candidate in candidates:
            record = candidate.evidence.get('experimental_ligand_evidence') or {}
            observations = list(record.get('observations') or []) + list((record.get('supporting_components') or {}).get('observations') or [])
            for observation in observations:
                path = Path(str(observation.get('aligned_ligand_pdb') or '')).resolve()
                if not path.is_file() or str(path) in retained_paths:
                    continue
                identity = 'evidence-ligand-' + hashlib.sha256(str(path).encode()).hexdigest()[:16]
                artifacts.append(ArtifactRecord(identity, 'aligned_ligand', str(path), _sha256(path),
                    'Exact aligned deposited ligand for site review'))
                review_ids.append(identity)
                retained_paths.add(str(path))
        source = {
            "cavity_directory": str(cavity.resolve()),
            "pocket_evidence_record": (
                str(Path(inputs.pocket_evidence_record).resolve())
                if inputs.pocket_evidence_record else None
            ),
            "candidate_count": len(candidates),
            "related_structure_evidence": (
                evidence.get("status") in {"completed", "available", "partial"}
                and bool(evidence.get("evidence") or evidence.get("ligand_site_groups"))
            ),
        }
        return self.controller.start_pocket_review(
            study_id,
            candidates,
            artifacts=tuple(artifacts),
            review_artifact_ids=tuple(review_ids),
            source=source,
            automation=automation,
        )

    @staticmethod
    def _supporting_artifacts(
        inputs: PocketReviewInputs,
        evidence: dict[str, Any],
    ) -> list[ArtifactRecord]:
        records = []
        paths: list[tuple[str, str, Path]] = []
        if inputs.pocket_evidence_record:
            paths.append(("pocket-evidence", "pocket_evidence", Path(inputs.pocket_evidence_record)))
            ensemble_value = (evidence.get("structural_ensemble") or {}).get("manifest")
            if ensemble_value:
                paths.append((
                    "structural-ensemble",
                    "structural_ensemble",
                    Path(inputs.pocket_evidence_record).parent / ensemble_value,
                ))
            conformational_value = (evidence.get("structural_ensemble") or {}).get("conformational_evidence")
            if conformational_value:
                paths.append((
                    "conformational-evidence", "conformational_evidence",
                    Path(inputs.pocket_evidence_record).parent / conformational_value,
                ))
        if inputs.review_scene:
            paths.append(("pocket-review-scene", "pymol_scene", Path(inputs.review_scene)))
        for artifact_id, kind, path in paths:
            if path.is_file():
                records.append(ArtifactRecord(
                    id=artifact_id,
                    kind=kind,
                    path=str(path.resolve()),
                    sha256=_sha256(path),
                    description={
                        "pocket_evidence": "Related-PDB ligand and pocket evidence",
                        "structural_ensemble": "Shared related-structure ensemble evidence",
                        "conformational_evidence": "Rotamer and site-accessibility evidence for docking-box review",
                        "pymol_scene": "Interactive pocket-review scene",
                    }[kind],
                ))
        return records
