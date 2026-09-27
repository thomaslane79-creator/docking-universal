"""Detect deposited non-water hetero-residues without deciding for the user."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


WATER_NAMES = {"HOH", "WAT", "DOD", "H2O"}


@dataclass(frozen=True)
class BoundLigandInstance:
    resname: str
    chain_id: str
    residue_number: str
    insertion_code: str = ""
    altlocs: tuple[str, ...] = ()
    heavy_atom_count: int = 0

    @property
    def identity(self) -> dict[str, str]:
        return {
            "resname": self.resname,
            "chain_id": self.chain_id,
            "residue_number": self.residue_number,
            "insertion_code": self.insertion_code,
            "altloc": self.altlocs[0] if len(self.altlocs) == 1 else "",
        }

    @property
    def label(self) -> str:
        insertion = self.insertion_code or ""
        altloc = f"; altloc {','.join(self.altlocs)}" if self.altlocs else ""
        return (
            f"{self.resname} — chain {self.chain_id}, residue "
            f"{self.residue_number}{insertion}; {self.heavy_atom_count} heavy atoms{altloc}"
        )


@dataclass(frozen=True)
class BoundLigandCandidate:
    resname: str
    residue_count: int
    heavy_atom_count: int
    locations: tuple[str, ...]
    instances: tuple[BoundLigandInstance, ...] = ()

    @property
    def label(self) -> str:
        kind = "ligand/cofactor" if self.heavy_atom_count >= 6 else "small hetero group"
        residues = "residue" if self.residue_count == 1 else "residues"
        locations = ", ".join(self.locations[:4])
        if len(self.locations) > 4:
            locations += f", +{len(self.locations) - 4} more"
        return (
            f"{self.resname} — {self.residue_count} {residues}, "
            f"{self.heavy_atom_count} heavy atoms ({locations}); {kind}"
        )


def detect_bound_ligands(path: Path | str) -> list[BoundLigandCandidate]:
    pdb = Path(path)
    if not pdb.is_file() or pdb.suffix.lower() not in {".pdb", ".cif", ".mmcif"}:
        raise FileNotFoundError(f"Ligand detection requires an existing PDB or mmCIF file: {pdb}")
    if pdb.suffix.lower() in {".cif", ".mmcif"}:
        return _detect_mmcif_bound_ligands(pdb)
    residues: dict[tuple[str, str, str, str], set[str]] = {}
    altlocs: dict[tuple[str, str, str, str], set[str]] = {}
    for line in pdb.read_text(errors="replace").splitlines():
        if not line.startswith("HETATM") or len(line) < 27:
            continue
        resname = line[17:20].strip().upper()
        if not resname or resname in WATER_NAMES:
            continue
        chain = line[21:22].strip() or "_"
        resseq = line[22:26].strip() or "?"
        insertion = line[26:27].strip()
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        atom_name = line[12:16].strip().upper()
        altloc = line[16:17].strip()
        if not element:
            element = atom_name.lstrip("0123456789")[:1]
        if element in {"H", "D"}:
            continue
        residues.setdefault((resname, chain, resseq, insertion), set()).add(atom_name)
        if altloc:
            altlocs.setdefault((resname, chain, resseq, insertion), set()).add(altloc)
    grouped: dict[str, list[tuple[tuple[str, str, str, str], set[str]]]] = {}
    for identity, atoms in residues.items():
        grouped.setdefault(identity[0], []).append((identity, atoms))
    candidates = []
    for resname, instances in grouped.items():
        locations = tuple(
            f"{identity[1]}:{identity[2]}{identity[3]}" for identity, _atoms in instances
        )
        candidates.append(BoundLigandCandidate(
            resname=resname,
            residue_count=len(instances),
            heavy_atom_count=sum(len(atoms) for _identity, atoms in instances),
            locations=locations,
            instances=tuple(
                BoundLigandInstance(
                    resname=identity[0], chain_id=identity[1],
                    residue_number=identity[2], insertion_code=identity[3],
                    altlocs=((altloc,) if altloc else ()),
                    heavy_atom_count=len(atoms),
                )
                for identity, atoms in instances
                for altloc in (tuple(sorted(altlocs.get(identity, set()))) or ("",))
            ),
        ))
    return sorted(
        candidates,
        key=lambda item: (-item.heavy_atom_count, -item.residue_count, item.resname),
    )


def _detect_mmcif_bound_ligands(path: Path) -> list[BoundLigandCandidate]:
    try:
        import gemmi
    except ImportError as exc:
        raise RuntimeError("mmCIF ligand detection requires gemmi") from exc
    structure = gemmi.read_structure(str(path))
    residues: dict[str, list[BoundLigandInstance]] = {}
    for model in structure:
        for chain in model:
            for residue in chain:
                resname = residue.name.strip().upper()
                # This reflects atom_site.group_PDB and remains reliable when
                # optional entity/polymer categories are absent.
                if not resname or resname in WATER_NAMES or residue.het_flag != "H":
                    continue
                atoms = [atom for atom in residue if atom.element.name not in {"H", "D"}]
                if not atoms:
                    continue
                altlocs = tuple(sorted({str(atom.altloc) for atom in atoms if str(atom.altloc).strip("\x00 ")}))
                sequence = str(residue.seqid.num)
                insertion = str(residue.seqid.icode).strip("\x00 ?.")
                residues.setdefault(resname, []).append(BoundLigandInstance(
                    resname=resname,
                    chain_id=chain.name or "_",
                    residue_number=sequence,
                    insertion_code=insertion,
                    altlocs=altlocs,
                    heavy_atom_count=len(atoms),
                ))
    candidates = []
    for resname, instances in residues.items():
        candidates.append(BoundLigandCandidate(
            resname=resname,
            residue_count=len(instances),
            heavy_atom_count=sum(item.heavy_atom_count for item in instances),
            locations=tuple(
                f"{item.chain_id}:{item.residue_number}{item.insertion_code}" for item in instances
            ),
            instances=tuple(instances),
        ))
    return sorted(candidates, key=lambda item: (-item.heavy_atom_count, -item.residue_count, item.resname))
