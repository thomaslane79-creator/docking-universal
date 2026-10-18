"""Shell-free scientific preparation candidate; not yet enabled in the desktop.

This bounded native port uses the existing filter, Reduce2 audit, conservative
PDBFixer helper, strict Meeko reader and P2Rank normalizer. Unsupported legacy
fallbacks stop for review; they never authorize residue loss or another method.
All child processes inherit the caller's owned Windows job, when applicable.
"""
from __future__ import annotations

from collections import defaultdict
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Callable

from .p2rank_runtime import java_invocation
from .receptor_filter import filter_receptor_pdb, disulfide_templates
from .services.preparation import ReceptorPreparationOptions, _canonical_name
from .services.preparation_interventions import write_intervention_record
from .services.structure_input import normalize_structure_input


class PreparationReviewRequired(RuntimeError):
    """An explicit chemical decision is required; no deletion is authorized."""


def meeko_command(source: Path, prefix: Path, pdbqt: Path, *, templates="",
                  additional_templates: Path | None = None, altloc="") -> list[str]:
    command = [sys.executable, "-m", "meeko.cli.mk_prepare_receptor",
               "--read_with_prody" if source.suffix.lower() in {".cif", ".mmcif"} else "--read_pdb",
               str(source), "-o", str(prefix), "-p", str(pdbqt)]
    if templates:
        command += ["--set_template", templates]
    if additional_templates:
        command += ["--add_templates", str(additional_templates)]
    if altloc:
        command += ["--default_altloc", altloc]
    return command


def prepare_native_candidate(options: ReceptorPreparationOptions, *,
                             p2rank: Path | None = None, java: Path | None = None,
                             libexec: Path | None = None,
                             runner: Callable = subprocess.run) -> Path:
    """Prepare into a fresh directory, without a shell or implicit approval.

    This candidate intentionally cannot replace the product Bash route yet.
    In particular, ADFR, fpocket and automatic disulfide allow-bad-res retries
    are not claimed as native support. The latter requires reviewed input.
    """
    options.validate()
    if options.preparation_backend == "adfr" or options.pocket_engine == "fpocket":
        raise ValueError("This native candidate supports strict Meeko and explicit P2Rank only; no method substitution")
    if options.site_mode != "pockets" and not options.predict_pockets_with_ligand:
        # The exact bound ligand can be selected independently in site review;
        # legacy fpocket ligand-context generation has not been ported here.
        raise ValueError("Native ligand-only artifact acceptance is not complete; no fallback detector was selected")
    if p2rank is None or java is None:
        raise ValueError("Explicit native P2Rank installation and Java executable are required")
    java_invocation(p2rank, java, ["-v"])
    if not importlib.util.find_spec("meeko"):
        raise ValueError("Pinned Meeko is unavailable in this scientific Python")
    if options.protonation == "required":
        raise ValueError("The explicit PDB2PQR-required route is not enabled in this native candidate")
    libexec = (libexec or Path(__file__).resolve().parents[1]).resolve()
    source = options.input_pdb.resolve()
    canonical = _canonical_name(source)
    root = options.working_directory.resolve() / (canonical + "_receptor_prep")
    if root.exists():
        raise FileExistsError(f"Native preparation requires a fresh output root: {root}")
    root.mkdir(parents=True)
    receptor, cavity = root / "receptor", root / "cavity"
    receptor.mkdir(); cavity.mkdir()
    filtered = receptor / f"{canonical}_filtered.pdb"
    pdb = receptor / f"{canonical}.pdb"
    pdbqt = receptor / f"{canonical}.pdbqt"
    prefix = receptor / canonical
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    # The bundled core is the same default as the legacy helper. No network
    # request for restraints or components is made here.
    if options.geostd_library:
        environment["DOCKING_UNIVERSAL_GEOSTD"] = str(options.geostd_library.resolve())
    attempts = []

    def log(message):
        print(message, flush=True)
        with (root / "run.log").open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")

    def execute(name, command, required: Path | None = None):
        log("Running " + name)
        path = receptor / (name + ".process.log")
        # A failed earlier attempt can leave a partial PDBQT. Retain it for
        # diagnosis, but never let it satisfy another attempt's output guard.
        if required is not None and required.exists():
            required.rename(required.with_name(required.name + f".before-{name}"))
        with path.open("w", encoding="utf-8") as stream:
            result = runner(command, cwd=root, env=environment, stdout=stream,
                            stderr=subprocess.STDOUT, shell=False, check=False)
        success = result.returncode == 0 and (required is None or (required.is_file() and required.stat().st_size > 0))
        attempts.append({"step": name, "returncode": result.returncode, "accepted": success,
                         "command": list(map(str, command)), "log": str(path)})
        return success

    def retain_status(status, **extra):
        (root / "native-preparation.json").write_text(json.dumps({
            "status": status, "candidate_only": True, "source": str(source),
            "attempts": attempts, **extra,
        }, indent=2) + "\n", encoding="utf-8")

    def review(message):
        logs = [Path(item["log"]) for item in attempts]
        content = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in logs)
        histidine = re.search(r"residue (\S+).*tied for fewest missing H: HIE HID", content)
        category = "Ambiguous histidine protonation" if histidine else "Native receptor preparation requires review"
        diagnosis = receptor / "receptor_failure_diagnosis.txt"
        diagnosis.write_text(f"Receptor preparation failure category: {category}\n"
                             f"Why this matters: {message}\n"
                             "Recommended next step: Review retained diagnostics and explicitly approve any chemical change; no component was removed.\n",
                             encoding="utf-8")
        write_intervention_record(diagnosis, filtered, receptor / "preparation_intervention.json",
                                  ambiguous_histidine=histidine.group(1) if histidine else "",
                                  diagnostic_logs=logs)
        retain_status("review_required", reason=message)
        raise PreparationReviewRequired(message)

    try:
        version_command, version_environment = java_invocation(p2rank, java, ["-v"], environment=environment)
        environment.update(version_environment)
        if not execute("p2rank_version", version_command):
            raise RuntimeError("The explicit P2Rank runtime did not start")
        version_text = (receptor / "p2rank_version.process.log").read_text(encoding="utf-8", errors="replace")
        if not re.search(r"\bP2Rank\s+2\.5\.1\b", version_text):
            raise ValueError("The native candidate requires primary P2Rank 2.5.1; no version substitution")
        normalized = normalize_structure_input(source, root / "source-input")
        from docking_universal_region import validate_protein_pdb
        validate_protein_pdb(normalized.engine_pdb_path)
        linked = filter_receptor_pdb(normalized.engine_pdb_path, filtered)
        shutil.copyfile(filtered, pdb)
        native_input = filtered
        if normalized.derived_for_legacy_engine:
            retained = root / "source"
            retained.mkdir()
            shutil.copyfile(source, retained / "structure.cif")
            shutil.copyfile(normalized.metadata_path, retained / "structure-input.json")
            native_input = receptor / f"{canonical}_filtered.cif"
            if not execute("native-receptor", [sys.executable, str(libexec / "docking-universal-native-receptor.py"),
                           str(source), str(filtered), str(native_input)], native_input):
                review("Native author-identifier/component projection failed")
        initial_input = native_input
        reduce_used = False
        if options.reduce2 != "off":
            reduced = receptor / f"{canonical}_reduce2H.pdb"
            reduce_used = execute("reduce2", [sys.executable, str(libexec / "docking-universal-reduce2-receptor.py"),
                str(native_input), str(reduced), str(receptor / "reduce2_audit.json"),
                str(receptor / "reduce2.log")], reduced)
            if reduce_used:
                shutil.copyfile(reduced, pdb)
                initial_input = pdb
            elif options.reduce2 == "required":
                review("Required Reduce2 did not produce an audited chemistry/frame-preserving model")
            # A failed available Reduce2 must not silently switch protonation
            # methods. The candidate records this just like the legacy route.
        route = "strict_meeko"
        success = execute("receptor_backend", meeko_command(initial_input, prefix, pdbqt,
            templates=options.meeko_templates, additional_templates=options.meeko_template_file), pdbqt)
        if not success and options.pdbfixer != "off":
            repaired = receptor / f"{canonical}_pdbfixer.pdb"
            if execute("pdbfixer", [sys.executable, str(libexec / "docking-universal-pdbfixer.py"),
                       str(native_input), str(repaired), str(receptor / "pdbfixer_audit.json")], repaired):
                shutil.copyfile(repaired, pdb)
                success = execute("receptor_after_pdbfixer", meeko_command(pdb, prefix, pdbqt,
                    templates=options.meeko_templates, additional_templates=options.meeko_template_file), pdbqt)
                if success:
                    route = "pdbfixer_then_strict_meeko"
        if not success:
            review("Strict Meeko rejected the model. Legacy ADFR/disulfide deletion-permitting retries are not silently applied")
        templates = options.meeko_template_file
        if templates:
            shutil.copyfile(templates, receptor / "meeko_additional_templates.json")
        if not execute("ccd_audit", [sys.executable, str(libexec / "docking-universal-ccd-audit.py"),
                       str(normalized.engine_pdb_path), str(pdbqt), str(receptor / "receptor_backend.process.log"),
                       route, str(receptor / "ccd_modification_audit.json"), str(receptor / "ccd_modification_audit.tsv"),
                       *(["--additional-templates", str(templates)] if templates else [])]):
            review("The retained-component audit did not complete")
        chains = defaultdict(lambda: [set(), 0])
        for line in pdb.read_text(encoding="utf-8").splitlines():
            if line.startswith(("ATOM  ", "HETATM")):
                chain = chains[line[21:22].strip() or "_"]
                chain[0].add(line[22:27]); chain[1] += 1
        (root / "chain_summary.tsv").write_text("".join(f"{key}\t{len(value[0])}\t{value[1]}\n"
            for key, value in sorted(chains.items())), encoding="utf-8")
        command, java_env = java_invocation(p2rank, java, ["predict", "-f", str(pdb), "-c", "default",
                                                                  "-visualizations", "0", "-o", str(cavity / "p2rank_output")],
                                           environment=environment)
        environment.update(java_env)
        if not execute("p2rank", command):
            raise RuntimeError("Native P2Rank failed; no fallback detector was selected")
        predictions = list((cavity / "p2rank_output").glob("*_predictions.csv"))
        if len(predictions) != 1:
            raise RuntimeError("Native P2Rank must produce exactly one prediction table")
        from .p2rank_adapter import materialize_p2rank_candidates
        materialize_p2rank_candidates(predictions[0], pdb, cavity, canonical,
                                      maximum_pockets=options.max_pockets, p2rank_version="2.5.1")
        retain_status("prepared", route=route, reduce2_used=reduce_used,
                      retained_linked_components=linked, deposited_disulfide_templates=disulfide_templates(normalized.engine_pdb_path),
                      box_policy="shared P2Rank candidate normalizer; no site approval or docking")
        log("Native receptor and pocket candidate preparation completed; site review remains required")
        return root
    except PreparationReviewRequired:
        raise
    except BaseException as exc:
        retain_status("failed", reason=str(exc))
        raise
