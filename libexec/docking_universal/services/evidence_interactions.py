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
        return result.get("layout_revision") == LAYOUT_REVISION and all(
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
            selected.append(line)
        else:
            lines.append(line)
    if not selected:
        raise ValueError("The exact selected ligand instance is absent from the original structure")
    if any(line[16:17].strip() for line in selected):
        raise ValueError("This ligand has alternate conformations; an exact altloc must be resolved before 2D analysis")
    raw = Chem.MolFromPDBBlock("\n".join(selected) + "\nEND\n", removeHs=True, sanitize=False)
    templates = read_sdf(record["chemistry"], removeHs=True)
    template = next((item for item in templates if item is not None), None)
    if raw is None or template is None:
        raise ValueError("The retained ligand coordinates or CCD chemistry could not be read")
    elements = lambda mol: Counter(atom.GetSymbol() for atom in mol.GetAtoms() if atom.GetAtomicNum() > 1)
    if elements(raw) != elements(template):
        raise ValueError("Deposited ligand atoms do not match CCD chemistry; interaction rendering stopped")
    typed = AllChem.AssignBondOrdersFromTemplate(template, raw)
    Chem.AssignStereochemistryFrom3D(typed)
    writer = sdf_writer(cache / "ligand.sdf")
    writer.write(typed)
    writer.close()
    # Reidentify only the chosen ligand to reuse the validated single-site PLIP path.
    normalized = [line[:17] + "UNL" + line[20:21] + "Z" + "   1 " + line[27:] for line in selected]
    if any(line[21:22] == "Z" and line[22:26].strip() == "1" for line in lines):
        raise ValueError("Reserved ligand identity Z:1 conflicts with the deposited structure")
    (cache / "receptor.pdb").write_text("\n".join(lines) + "\nEND\n")
    (cache / "complex.pdb").write_text("\n".join(lines + normalized) + "\nEND\n")
    (cache / "input.json").write_text(json.dumps(record, indent=2) + "\n")
    return cache


def render_contact_summary(cache):
    """Readable fallback: chemistry and measured contacts, without invented geometry."""
    from rdkit import Chem
    from rdkit.Chem import Draw, rdDepictor
    from PIL import Image, ImageDraw, ImageFont
    from matplotlib import get_data_path
    import xml.etree.ElementTree as ET
    from collections import Counter
    import textwrap
    cache = Path(cache)
    mol = next(item for item in read_sdf(cache / "ligand.sdf") if item)
    rdDepictor.Compute2DCoords(mol)
    contacts = Counter()
    root = ET.parse(cache / "plip" / "report.xml").getroot()
    for item in root.findall("bindingsite/interactions/*/*"):
        residue, number = item.findtext("restype"), item.findtext("resnr")
        if residue and number:
            kind = item.tag.replace("_", " ")
            contacts[(kind, residue, item.findtext("reschain") or "", number)] += 1
    rows = []
    for (kind, residue, chain, number), count in sorted(contacts.items()):
        kind = kind.replace("hydrogen bond", "H bond").replace("hydrophobic interaction", "hydrophobic")
        rows.append(({"name": residue, "chain": chain, "number": number},
                     textwrap.wrap(f"{residue} {chain}:{number} — {kind} ({count})", width=36)))
    height = max(1500, 320 + sum(len(row) * 40 + 14 for _, row in rows))
    image = Image.new("RGB", (1800, height), "white")
    image.paste(Draw.MolToImage(mol, size=(1050, 1200)), (0, 180))
    draw = ImageDraw.Draw(image)
    font_path = str(Path(get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf")
    title = ImageFont.truetype(font_path, 38)
    font = ImageFont.truetype(font_path, 28)
    draw.text((40, 35), "Deposited ligand · PLIP contact summary", font=title, fill="#172b3a")
    draw.text((40, 95), "Compact view: ligand chemistry and contacts; distances are not drawn to scale.", font=font, fill="#333333")
    y = 195
    draw.text((1100, y), "Contacts in the original protein", font=font, fill="#172b3a")
    y += 65
    if not contacts:
        draw.text((1100, y), "No PLIP contacts detected", font=font, fill="#333333")
    regions = []
    for residue, row in rows:
        top = y
        for line in row:
            draw.text((1100, y), line, font=font, fill="#333333")
            y += 40
        regions.append({"residue": residue, "rect": [1100 / 1800, top / height,
                        min(690, max(draw.textlength(line, font=font) for line in row)) / 1800,
                        (y - top) / height]})
        y += 14
    image.save(cache / "interaction_diagram.png")
    diagram = cache / "interaction_diagram.png"
    Path(str(diagram) + ".hit-regions.json").write_text(json.dumps({
        "schema": 1, "image_sha256": hashlib.sha256(diagram.read_bytes()).hexdigest(),
        "plip_sha256": hashlib.sha256((cache / "plip" / "report.xml").read_bytes()).hexdigest(),
        "regions": regions,
    }, indent=2))
