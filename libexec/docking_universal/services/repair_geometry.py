"""Reject gross overlaps introduced by repair; never choose replacement geometry."""
import math
from itertools import product
from pathlib import Path


def _heavy_atoms(path):
    path = Path(path)
    if path.suffix.lower() in {'.cif', '.mmcif'}:
        import gemmi
        structure = gemmi.read_structure(str(path))
        if len(structure) != 1:
            raise ValueError('Repair geometry review requires one explicit structural model')
        result = []
        for chain in structure[0]:
            for residue in chain:
                number = str(residue.seqid.num) + residue.seqid.icode.strip()
                for atom in residue:
                    if atom.element.name in {'H', 'D'}:
                        continue
                    identity = (chain.name, number, residue.name, atom.name)
                    result.append((identity, (atom.pos.x, atom.pos.y, atom.pos.z)))
    else:
        result = []
        for line in path.read_text().splitlines():
            if not line.startswith(('ATOM  ', 'HETATM')):
                continue
            element = line[76:78].strip().upper() or line[12:16].strip().lstrip('0123456789')[:1].upper()
            if element in {'H', 'D'}:
                continue
            identity = (line[21:22].strip(), line[22:27].strip(), line[17:20].strip(), line[12:16].strip())
            result.append((identity, tuple(float(line[i:i + 8]) for i in (30, 38, 46))))
    if not result or any(not all(math.isfinite(v) for v in xyz) for _, xyz in result):
        raise ValueError('Repair geometry review requires finite, nonempty heavy-atom coordinates')
    return result


def introduced_heavy_atom_overlaps(source, repaired):
    return introduced_heavy_atom_overlaps_from_atoms(_heavy_atoms(source), _heavy_atoms(repaired))


def introduced_heavy_atom_overlaps_from_atoms(source_atoms, repaired_atoms):
    """Same gross-overlap guard for an in-memory, reviewed candidate."""
    original={identity for identity,_ in source_atoms}
    hits=[];grid={}
    for a,xyz in repaired_atoms:
        cell=tuple(math.floor(v) for v in xyz)
        for offset in product((-1,0,1),repeat=3):
            for b,other in grid.get(tuple(c+d for c,d in zip(cell,offset)),()):
                if a in original and b in original:
                    continue
                distance=math.dist(xyz,other)
                # Catch only gross sub-Angstrom heavy-atom overlaps, not subtle
                # clashes or a claim of valid stereochemistry.
                if distance < 1.0:
                    hits.append({'first':a,'second':b,'distance_angstrom':distance})
        grid.setdefault(cell,[]).append((a,xyz))
    return hits
