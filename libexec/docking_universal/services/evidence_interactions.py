"""Local, exact-instance interaction diagrams for deposited ligand evidence."""
from pathlib import Path
from ..sdf_io import read_sdf, sdf_writer
import hashlib
import json
from ..poseedit_renderer import LAYOUT_REVISION


def evidence_diagram_path(cache):
    """Resolve a versioned display derivative without replacing historical PNGs."""
    cache = Path(cache)
    try:
        name = json.loads((cache / "result.json").read_text()).get("diagram_file", "interaction_diagram.png")
        if not isinstance(name, str) or Path(name).name != name or not name.startswith("interaction_diagram") or not name.endswith(".png"):
            raise ValueError("Invalid cached diagram filename")
        return cache / name
    except (OSError, ValueError, TypeError, AttributeError):
        return cache / "interaction_diagram.png"


def evidence_diagram_current(cache):
    cache = Path(cache)
    try:
        result = json.loads((cache / "result.json").read_text())
        sources = {"ligand": cache / "ligand.sdf", "receptor": cache / "receptor.pdb",
                   "plip": cache / "plip/report.xml", "diagram": evidence_diagram_path(cache)}
        return result.get("diagram_kind") == "poseedit_interactions" and result.get("layout_revision") == LAYOUT_REVISION and all(
            result.get("source_hashes", {}).get(key) == hashlib.sha256(path.read_bytes()).hexdigest()
            for key, path in sources.items())
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def evidence_inputs(observation):
    aligned = Path(observation.get("aligned_ligand_pdb") or "")
    identity = str(observation.get("source_ligand_id") or "").split("/")
    if len(identity) != 4 or not aligned.is_file():
        raise ValueError("This observation has no retained exact ligand identity")
    entry, ligand, chain, residue = identity
    if observation.get('source') == 'input_structure':
        source = Path(observation.get('deposited_source') or '')
        chemistry = Path(observation.get('component_source') or '')
        for path, key in ((source, 'deposited_source_sha256'), (chemistry, 'component_source_sha256'),
                          (aligned, 'ligand_sha256')):
            if not path.is_file() or not observation.get(key) or hashlib.sha256(path.read_bytes()).hexdigest() != observation[key]:
                raise ValueError('The original input structure, normalized coordinates or selected ligand could not be verified')
        if chemistry.suffix.lower() not in ('.cif', '.mmcif'):
            raise ValueError('The input structure has no retained mmCIF component definition for 2D interactions')
        digest = hashlib.sha256(b'input-deposited-interactions-v1')
        digest.update(json.dumps(identity).encode())
        digest.update(str(observation.get('altloc') or '').encode())
        digest.update(source.read_bytes())
        digest.update(chemistry.read_bytes())
        digest.update(aligned.read_bytes())
        cache = aligned.parent / 'input_evidence_interactions' / digest.hexdigest()[:24]
        return dict(entry='Input', ligand=ligand, chain=chain, residue=residue,
                    source=str(source.resolve()), source_sha256=observation['deposited_source_sha256'],
                    chemistry=str(chemistry.resolve()), chemistry_sha256=observation['component_source_sha256'],
                    chemistry_kind='input_mmcif', altloc=observation.get('altloc') or '', aligned=str(aligned.resolve()),
                    aligned_sha256=observation['ligand_sha256'], cache=str(cache.resolve()))
    root = aligned.parent.parent
    source = root / "structural_ensemble" / "source_structures" / f"{entry.upper()}.pdb"
    chemistry = root / "ccd" / f"{ligand}_ideal.sdf"
    if not source.is_file() or not chemistry.is_file():
        raise ValueError("The original deposited structure or CCD chemistry was not retained for this observation")
    digest = hashlib.sha256()
    digest.update("deposited-interactions-v3-residue-links".encode())
    digest.update(json.dumps(identity).encode())
    digest.update(source.read_bytes())
    digest.update(chemistry.read_bytes())
    cache = root / "evidence_interactions" / digest.hexdigest()[:24]
    return dict(entry=entry, ligand=ligand, chain=chain, residue=residue,
                source=str(source.resolve()), chemistry=str(chemistry.resolve()),
                aligned=str(aligned.resolve()), cache=str(cache.resolve()))


def materialize_inputs(record):
    """Use CCD bonds with deposited coordinates; never seed from ideal geometry."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from collections import Counter
    source = Path(record["source"])
    if record.get('chemistry_kind') == 'input_mmcif':
        for path, key in ((source, 'source_sha256'), (Path(record['chemistry']), 'chemistry_sha256'),
                          (Path(record['aligned']), 'aligned_sha256')):
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record.get(key):
                raise ValueError('Input structure or selected ligand changed before 2D analysis')
    cache = Path(record["cache"])
    cache.mkdir(parents=True, exist_ok=True)
    lines = []
    selected = []
    for line in source.read_text().splitlines():
        if line.startswith("ENDMDL"):
            break  # the retained evidence collector uses the first model
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        match = (line[17:20].strip() == record["ligand"]
                 and line[21:22].strip() == record["chain"]
                 and (line[22:26].strip() + line[26:27].strip()) == record["residue"])
        if match:
            requested_altloc = record.get('altloc') or ''
            if not requested_altloc or not line[16:17].strip() or line[16:17].strip() == requested_altloc:
                selected.append(line)
        else:
            lines.append(line)
    if not selected:
        raise ValueError("The exact selected ligand instance is absent from the original structure")
    if any(line[16:17].strip() for line in selected) and not record.get('altloc'):
        raise ValueError("This ligand has alternate conformations; an exact altloc must be resolved before 2D analysis")
    raw = Chem.MolFromPDBBlock("\n".join(selected) + "\nEND\n", removeHs=False, sanitize=False)
    # RDKit does not remove explicit PDB hydrogens during an unsanitized
    # parse. Remove them explicitly before applying the heavy-atom template;
    # otherwise its hydrogen counts can produce impossible valences.
    if raw is not None:
        raw = Chem.RemoveHs(raw, sanitize=False)
    if record.get('chemistry_kind') == 'input_mmcif':
        from .molecule_inspection import _component_molecule
        template = Chem.RemoveHs(_component_molecule({'path': record['chemistry'],
            'sha256': record['chemistry_sha256'], 'resname': record['ligand']}))
    else:
        templates = read_sdf(record["chemistry"], removeHs=True)
        template = next((item for item in templates if item is not None), None)
    if raw is None or template is None:
        raise ValueError("The retained ligand coordinates or CCD chemistry could not be read")
    elements = lambda mol: Counter(atom.GetSymbol() for atom in mol.GetAtoms() if atom.GetAtomicNum() > 1)
    if elements(raw) != elements(template):
        raise ValueError("Deposited ligand atoms do not match CCD chemistry; interaction rendering stopped")
    if record.get('chemistry_kind') == 'input_mmcif':
        # Use exact component atom names instead of guessing bonds from
        # distances: close contacts can create spurious bonds in PDB parsing.
        deposited = {}
        for line in selected:
            if line[76:78].strip().upper() in {'H', 'D'}:
                continue
            name = line[12:16].strip()
            if name in deposited:
                raise ValueError('The selected input ligand has duplicate atom names')
            deposited[name] = (line[76:78].strip().upper(),
                               tuple(float(line[i:i + 8]) for i in (30, 38, 46)))
        retained = {}
        for line in Path(record['aligned']).read_text().splitlines():
            if not line.startswith(('ATOM  ', 'HETATM')) or line[76:78].strip().upper() in {'H', 'D'}:
                continue
            name = line[12:16].strip()
            if name in retained:
                raise ValueError('The retained input ligand has duplicate atom names')
            retained[name] = (line[76:78].strip().upper(),
                              tuple(float(line[i:i + 8]) for i in (30, 38, 46)))
        if set(retained) != set(deposited) or any(
                retained[name][0] != deposited[name][0] or
                any(abs(a - b) > 0.002 for a, b in zip(retained[name][1], deposited[name][1]))
                for name in deposited):
            raise ValueError('Retained input ligand does not match the exact original structure instance')
        names = [atom.GetProp('_du_component_atom_id') for atom in template.GetAtoms()]
        if len(set(names)) != len(names) or set(names) != set(deposited):
            raise ValueError('Deposited input-ligand atom names do not match its component definition')
        typed = Chem.Mol(template)
        typed.RemoveAllConformers()
        conformer = Chem.Conformer(typed.GetNumAtoms())
        for atom, name in zip(typed.GetAtoms(), names):
            element, xyz = deposited[name]
            if atom.GetSymbol().upper() != element:
                raise ValueError('Deposited input-ligand element does not match its component definition')
            conformer.SetAtomPosition(atom.GetIdx(), xyz)
        typed.AddConformer(conformer)
    else:
        typed = AllChem.AssignBondOrdersFromTemplate(template, raw)
    Chem.AssignStereochemistryFrom3D(typed)
    writer = sdf_writer(cache / "ligand.sdf")
    writer.write(typed)
    writer.close()
    # Reidentify only the chosen ligand to reuse the validated single-site PLIP path.
    normalized = [line[:16] + ' ' + "UNL" + line[20:21] + "Z" + "   1 " + line[27:] for line in selected]
    if any(line[21:22] == "Z" and line[22:26].strip() == "1" for line in lines):
        raise ValueError("Reserved ligand identity Z:1 conflicts with the deposited structure")
    (cache / "receptor.pdb").write_text("\n".join(lines) + "\nEND\n")
    (cache / "complex.pdb").write_text("\n".join(lines + normalized) + "\nEND\n")
    (cache / "input.json").write_text(json.dumps(record, indent=2) + "\n")
    return cache
