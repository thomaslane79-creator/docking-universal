#!/usr/bin/env python3
"""Render one retained experimental ligand locally, with supervised children."""
import argparse
import json
import signal
import subprocess
import sys
import os
import hashlib
from uuid import uuid4
import xml.etree.ElementTree as ET
from pathlib import Path
from docking_universal.services.evidence_interactions import materialize_inputs, render_contact_summary
from docking_universal.poseedit_renderer import LAYOUT_REVISION

child = None


def stop(signum, frame):
    if child is not None and child.poll() is None:
        if os.name != "nt":
            os.killpg(child.pid, signal.SIGTERM)
        else:
            child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
    raise SystemExit(1)


def run(command):
    global child
    child = subprocess.Popen(list(map(str, command)), start_new_session=os.name != "nt")
    status = child.wait()
    if status:
        raise RuntimeError(f"Interaction worker failed (status {status}); inspect the retained log")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--diagram-only", action="store_true", help="Reuse retained PLIP contacts and coordinates; update only the drawing")
    args = parser.parse_args()
    record = json.loads(args.request.read_text())
    cache = Path(record["cache"])
    if args.diagram_only:
        previous = json.loads((cache / "result.json").read_text())
        if any(previous.get(key) != record.get(key) for key in ("entry", "ligand", "chain", "residue", "source", "chemistry")):
            raise ValueError("Cached interaction identity does not match the selected observation")
        for name in ("ligand.sdf", "receptor.pdb", "plip/report.xml"):
            if not (cache / name).is_file():
                raise ValueError("Retained inputs are missing for diagram-only rendering")
    else:
        cache = materialize_inputs(record)
    scripts = Path(__file__).resolve().parent
    if not args.diagram_only:
        attempt = cache / ("plip_attempt_" + uuid4().hex[:12])
        run([sys.executable, scripts / "docking-universal-interactions.py", cache / "complex.pdb",
             "--out-dir", attempt, "--ligand-resname", "UNL", "--ligand-chain", "Z",
             "--ligand-position", "1", "--typed-ligand-sdf", cache / "ligand.sdf", "--skip-native-visuals"])
        xml = ET.parse(attempt / "report.xml")
        root = xml.getroot()
        selected = []
        for site in root.findall("bindingsite"):
            if (site.findtext("identifiers/hetid") == "UNL"
                    and site.findtext("identifiers/chain") == "Z"
                    and site.findtext("identifiers/position") == "1"):
                selected.append(site)
            else:
                root.remove(site)
        if len(selected) != 1:
            raise ValueError("PLIP did not identify exactly the selected ligand")
        (cache / "plip").mkdir(exist_ok=True)
        xml.write(cache / "plip" / "report.xml", encoding="utf-8", xml_declaration=True)
    diagram_kind = "poseedit_interactions"
    rendered = False
    spacing = None
    # Never render over the last valid derivative: a failed layout must leave
    # every previous view available, even after changed inputs invalidate hashes.
    diagram = cache / f"interaction_diagram.{LAYOUT_REVISION}.{uuid4().hex[:12]}.png"
    for spacing in (15, 25, 30):
        try:
            run([sys.executable, scripts / "docking-universal-render-poseedit.py", "--ligand", cache / "ligand.sdf",
                 "--receptor", cache / "receptor.pdb", "--plip-xml", cache / "plip" / "report.xml",
                 "--output", diagram, "--scale", "3", "--ligand-spacing", spacing])
        except RuntimeError:
            continue
        rendered = True
        break
    if not rendered:
        if args.diagram_only:
            raise RuntimeError("Updated residue layout could not be rendered; the previous diagram and contacts were preserved")
        render_contact_summary(cache)
        diagram = cache / "interaction_diagram.png"
        diagram_kind = "ligand_and_plip_contact_summary"
    manifest = dict(record, network_used=False, interaction_basis="original_deposited_structure",
                    chemistry_source="retained_rcsb_ccd", coordinates_source="deposited_first_model",
                    diagram_kind=diagram_kind, ligand_spacing=spacing if rendered else None,
                    diagram_file=diagram.name, layout_revision=LAYOUT_REVISION, contacts_reused=args.diagram_only,
                    source_hashes={key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in {
                        "ligand": cache / "ligand.sdf", "receptor": cache / "receptor.pdb",
                        "plip": cache / "plip/report.xml", "diagram": diagram}.items()})
    if args.diagram_only:
        backup = cache / f"result.before-{LAYOUT_REVISION}.json"
        if not backup.exists():
            backup.write_text(json.dumps(previous, indent=2) + "\n")
    (cache / "result.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    main()
