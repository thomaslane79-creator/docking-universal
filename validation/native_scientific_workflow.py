"""Real native preparation-to-report rehearsal using public/synthetic fixtures.

The only exported file is summary.json: stage status/counts/runtime metadata.
Receptors, poses, diagrams, reports and detailed tool logs stay on the runner.
This does not enable product GUI stages or authorize any user study.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))


def pinned_p2rank(out):
    record = json.loads((ROOT / "dependencies/p2rank.json").read_text(encoding="utf-8"))
    # This fixture gate is explicitly the installed primary 2.5.1 model, not
    # the separate alpha visualization model or a different pocket method.
    archive = out / "p2rank_2.5.1.tar.gz"
    with urllib.request.urlopen("https://github.com/rdk/p2rank/releases/download/2.5.1/p2rank_2.5.1.tar.gz", timeout=90) as response:
        data = response.read()
    expected = "d243f2d9036ac053fefb9407b5fe1c85f4fe077c519fd975ac585e995feab274"
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Pinned P2Rank asset checksum mismatch")
    archive.write_bytes(data)
    destination = out / "p2rank"
    destination.mkdir()
    with tarfile.open(archive, "r:gz") as package:
        for member in package.getmembers():
            parts = Path(member.name.replace("\\", "/")).parts
            if member.issym() or member.islnk() or not (member.isdir() or member.isfile()) or any(part in {"..", "/"} or ":" in part for part in parts):
                raise ValueError("Unsafe member in pinned P2Rank archive")
            relative = Path(*parts[1:])
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("P2Rank extraction escaped its fresh directory")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif relative.parts:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.extractfile(member) as source, target.open("wb") as stream:
                    shutil.copyfileobj(source, stream)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--p2rank", type=Path)
    parser.add_argument("--vina", type=Path)
    parser.add_argument("--local-development", action="store_true", help="Never counts as native Windows acceptance")
    args = parser.parse_args()
    if platform.system() != "Windows" and not args.local_development:
        parser.error("Native Windows execution is required")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    state = {"status": "running", "native_windows": platform.system() == "Windows",
             "platform": platform.platform(), "python": sys.version,
             "product_scientific_stages_enabled": False, "steps": [],
             "scope": "public 2R8N preparation and synthetic chemical-library process rehearsal; not docking accuracy validation"}

    def save():
        (out / "summary.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def stage(name, action):
        item = {"name": name, "status": "running"}
        state["steps"].append(item); save()
        print("Native validation: " + name, flush=True)
        started = time.monotonic()
        try:
            value = action()
        except BaseException:
            item.update(status="failed", seconds=round(time.monotonic() - started, 3))
            save()
            raise
        item.update(status="passed", seconds=round(time.monotonic() - started, 3)); save()
        return value

    def run(name, command):
        with (out / (name + ".local.log")).open("w", encoding="utf-8") as log:
            result = subprocess.run(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT,
                                    env=os.environ.copy(), shell=False, timeout=1200)
        if result.returncode:
            raise RuntimeError(f"{name} exited {result.returncode}; detailed scientific log retained locally, not uploaded")

    try:
        from docking_universal.native_preparation import prepare_native_candidate
        from docking_universal.services.preparation import ReceptorPreparationOptions
        from docking_universal.runtime_layout import executable_directories
        prefix = Path(sys.prefix)
        os.environ["PATH"] = os.pathsep.join([*(str(path) for path in executable_directories(prefix, windows=os.name == "nt")), os.environ.get("PATH", "")])
        os.environ.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", DOCKING_UNIVERSAL_PYTHON=sys.executable,
                          DOCKING_UNIVERSAL_CLI=str(ROOT / "validation/native_science_dispatch.py"),
                          DOCKING_UNIVERSAL_LIBEXEC=str(ROOT / "libexec"), DOCKING_UNIVERSAL_CPU="2", DOCKING_UNIVERSAL_VINA_BACKEND="cli")
        p2rank = args.p2rank or stage("pinned_p2rank_install", lambda: pinned_p2rank(out))
        java = shutil.which("java")
        if not java:
            raise ValueError("Pinned Java 17 executable is unavailable")
        inputs = out / "Public inputs — native Unicode"
        inputs.mkdir()
        source = inputs / "2R8N.pdb"
        shutil.copyfile(ROOT / "examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb", source)
        from docking_universal.services.geostd_components import bundled_minimal_library
        options = ReceptorPreparationOptions(source, out / "Preparation — native", "pockets", reduce2="required", max_pockets=0,
                                             geostd_library=bundled_minimal_library(), pocket_engine="p2rank", preparation_backend="meeko")
        preparation = stage("public_pdb_reduce2_meeko_p2rank", lambda: prepare_native_candidate(options, p2rank=p2rank, java=Path(java)))
        audit = json.loads((preparation / "receptor/reduce2_audit.json").read_text(encoding="utf-8"))
        state["reduce2_status"] = audit.get("status")
        # Rehearse the native mmCIF reader/projection as a separate starting
        # path. Gemmi writes the same public fixture locally; no download or
        # structure upload is involved.
        import gemmi
        cif = inputs / "2R8N.cif"
        gemmi.read_structure(str(source)).make_mmcif_document().write_file(str(cif))
        cif_options = ReceptorPreparationOptions(cif, out / "mmCIF preparation", "pockets", reduce2="required", max_pockets=0,
                                                 geostd_library=bundled_minimal_library(), pocket_engine="p2rank", preparation_backend="meeko")
        stage("public_mmcif_reduce2_meeko_p2rank", lambda: prepare_native_candidate(cif_options, p2rank=p2rank, java=Path(java)))
        from docking_universal.services.pocket_review import ordered_pocket_boxes
        boxes = ordered_pocket_boxes(preparation / "cavity")
        if not boxes:
            raise ValueError("No retained P2Rank candidate was available")
        state["retained_candidate_count"] = len(boxes)
        from docking_universal.protocol_finalization import FinalizationSettings, ProtocolFinalizationRequest, selected_region_records
        from docking_universal.services.finalization import finalize_site_guided_protocol
        from docking_universal.state import StudyState
        settings = FinalizationSettings(conformers=1, seed_count=1, base_seed=41001, exhaustiveness=1, num_modes=3)
        state["fixture_search_settings"] = settings.protocol_parameters()
        request = ProtocolFinalizationRequest("native-fixture", "2R8N", preparation, source,
            preparation / "receptor/2R8N.pdb", preparation / "receptor/2R8N.pdbqt",
            tuple(selected_region_records([boxes[0]], [{"label": "P1", "path": boxes[0]}])),
            settings, "fixture-only-approval-not-user-authority", 1, out / "Protocol report", True)
        study = StudyState("native-fixture", "Native public fixture", "site_guided_protocol")
        outputs = stage("protocol_pdf_and_portable_bundle", lambda: finalize_site_guided_protocol(study, request, libexec=ROOT / "libexec",
            command_runner=lambda command: run("protocol_report", command)))
        if not outputs.report.read_bytes().startswith(b"%PDF-"):
            raise ValueError("Protocol renderer did not produce a PDF")
        from rdkit import Chem
        ligand = inputs / "synthetic_carbamate.sdf"
        molecule = Chem.MolFromSmiles("CCOC(=O)N1CCCCC1")
        molecule.SetProp("_Name", "Synthetic carbamate process fixture")
        with Chem.SDWriter(str(ligand)) as writer:
            writer.write(molecule)
        if args.vina:
            engine = args.vina.resolve()
        else:
            asset = json.loads((ROOT / "dependencies/vina-windows.json").read_text(encoding="utf-8"))
            with urllib.request.urlopen(asset["url"], timeout=90) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != asset["sha256"]:
                raise ValueError("Official Windows Vina checksum mismatch")
            engine = out / asset["filename"]; engine.write_bytes(data)
        os.environ["DOCKING_UNIVERSAL_VINA"] = str(engine)
        screen = out / "Screening — native"
        stage("ligand_states_docking_clusters_interactions_and_report", lambda: run("screen", [sys.executable,
            ROOT / "libexec/docking-universal-run.py", "--mode", "screen", "--protocol", outputs.bundle,
            "--ligands", ligand, "--out", screen, "--non-interactive", "--accept-exploratory-protocol",
            "--analysis", "representatives", "--stop-on-error"]))
        summary = json.loads((screen / "report/study_summary.json").read_text(encoding="utf-8"))
        pdfs = list((screen / "report").glob("*.pdf"))
        if summary.get("completion_status") != "COMPLETED" or not pdfs or not all(path.read_bytes().startswith(b"%PDF-") for path in pdfs):
            raise ValueError("The screen did not finish with its report")
        state.update(status="passed", report_pdf_count=len(pdfs), scientific_accuracy_claim=False)
    except BaseException as exc:
        state.update(status="failed", error=str(exc), error_type=type(exc).__name__)
    save()
    print(json.dumps({key: state.get(key) for key in ("status", "error", "native_windows")}))
    return 0 if state["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
