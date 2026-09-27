"""Small, auditable RCSB coordinate acquisition boundary for GUI studies."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


PDB_ID = re.compile(r"^[0-9][A-Za-z0-9]{3}$")


def canonical_pdb_id(value: str) -> str:
    candidate = str(value).strip().upper()
    if not PDB_ID.fullmatch(candidate):
        raise ValueError("A PDB ID must contain four characters and begin with a number")
    return candidate


def download_pdb_entry(pdb_id: str, destination: Path | str) -> Path:
    """Download the canonical mmCIF source, retaining provenance.

    The historical function name is preserved for callers.  Its returned path
    is now the retained mmCIF source rather than a lossy legacy-PDB download.
    """
    entry = canonical_pdb_id(pdb_id)
    directory = Path(destination).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{entry}.cif"
    url = f"https://files.rcsb.org/download/{entry}.cif"
    request = Request(url, headers={"User-Agent": "Docking-Universal/GUI"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read()
    except Exception as exc:
        raise OSError(f"Could not download {entry} from RCSB PDB: {exc}") from exc
    text = payload.decode("utf-8", errors="replace")
    if not text.lstrip().lower().startswith("data_") or "_atom_site." not in text:
        raise OSError(
            f"RCSB did not return a usable PDBx/mmCIF coordinate file for {entry}"
        )
    temporary = output.with_suffix(".cif.part")
    temporary.write_bytes(payload)
    temporary.replace(output)
    provenance = {
        "schema_name": "docking-universal-rcsb-input",
        "schema_version": 2,
        "pdb_id": entry,
        "source": "RCSB Protein Data Bank",
        "url": url,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "coordinate_file": output.name,
        "coordinate_format": "mmcif",
        "policy": "mmCIF is retained as the source of record; legacy PDB is derived only for tools that require it",
    }
    (directory / f"{entry}_provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    return output
