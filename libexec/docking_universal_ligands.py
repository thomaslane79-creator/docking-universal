#!/usr/bin/env python3
"""Prepare SDF records for Vina-family engines through external chemistry tools.

The workflow stays in Python while Open Babel, Meeko, and ADFRsuite remain
replaceable scientific executables at explicit subprocess boundaries.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence, TextIO


USAGE = """Usage:
  docking-universal prepare-ligand <ligands.sdf> [options]

Options:
  -n, --name-field FIELD     SDF property used as the compound name
  -o, --out DIR              Output root (default: sanitized SDF basename)
  --backend NAME             auto, meeko, or adfr (default: auto)
  --target-engines NAME      vina or qvinaw (QuickVina-W)
  --geometry-mode NAME       optimize or preserve (default: optimize)
  --charge-model NAME        gasteiger, espaloma, or zero (default: gasteiger)
  --prepare-ligand PATH      Backend executable path
  --obabel PATH              Open Babel executable
  -h, --help                 Show this help

Environment equivalents:
  DOCKING_UNIVERSAL_PREP_LIGAND
  DOCKING_UNIVERSAL_OBABEL
"""


class LigandUsageError(Exception):
    """The requested ligand-preparation configuration is invalid."""


class LigandRuntimeError(Exception):
    """A required input, tool, or preparation output is unavailable."""


@dataclass
class LigandOptions:
    sdf_file: Path
    name_field: str = ""
    output_root: Path | None = None
    backend: str = "auto"
    target_engines: str = "vina"
    geometry_mode: str = "optimize"
    charge_model: str = "gasteiger"
    prepare_ligand: Path | None = None
    obabel: Path | None = None


@dataclass(frozen=True)
class LigandPreparationResult:
    total: int
    successful: int
    failed: int
    output_dir: Path


def parse_arguments(arguments: Sequence[str], environment: Mapping[str, str]) -> LigandOptions:
    if not arguments:
        raise LigandUsageError("")
    if arguments[0] in ("-h", "--help"):
        raise SystemExit(0)
    options = LigandOptions(
        sdf_file=Path(arguments[0]),
        backend=environment.get("DOCKING_UNIVERSAL_PREP_BACKEND", "auto"),
        target_engines=environment.get("DOCKING_UNIVERSAL_TARGET_ENGINES", "vina"),
        prepare_ligand=Path(environment["DOCKING_UNIVERSAL_PREP_LIGAND"])
        if environment.get("DOCKING_UNIVERSAL_PREP_LIGAND") else None,
        obabel=Path(environment["DOCKING_UNIVERSAL_OBABEL"])
        if environment.get("DOCKING_UNIVERSAL_OBABEL") else None,
    )
    fields = {
        "-n": "name_field", "--name-field": "name_field",
        "-o": "output_root", "--out": "output_root",
        "--backend": "backend", "--target-engines": "target_engines",
        "--geometry-mode": "geometry_mode", "--charge-model": "charge_model",
        "--prepare-ligand": "prepare_ligand", "--obabel": "obabel",
    }
    path_fields = {"output_root", "prepare_ligand", "obabel"}
    index = 1
    while index < len(arguments):
        argument = arguments[index]
        if argument in ("-h", "--help"):
            raise SystemExit(0)
        field = fields.get(argument)
        if field is None:
            raise LigandUsageError(f"Unknown option: {argument}")
        if index + 1 >= len(arguments):
            raise LigandUsageError(f"ERROR: option requires a value: {argument}")
        value = arguments[index + 1]
        setattr(options, field, Path(value) if field in path_fields else value)
        index += 2
    if options.target_engines in ("quickvina-w", "qvina-w"):
        options.target_engines = "qvinaw"
    return options


def _executable(path: Path | None) -> bool:
    return bool(path and path.is_file() and os.access(path, os.X_OK))


def validate_and_resolve(options: LigandOptions, environment: Mapping[str, str]) -> None:
    if options.target_engines not in ("vina", "qvinaw"):
        raise LigandUsageError("ERROR: --target-engines must be vina or qvinaw (QuickVina-W)")
    if options.geometry_mode not in ("optimize", "preserve"):
        raise LigandUsageError("ERROR: --geometry-mode must be optimize or preserve")
    if options.charge_model not in ("gasteiger", "espaloma", "zero"):
        raise LigandUsageError("ERROR: unsupported --charge-model")
    if options.backend not in ("auto", "meeko", "adfr"):
        raise LigandUsageError("ERROR: --backend must be auto, meeko, or adfr")

    if options.backend == "auto":
        if options.prepare_ligand:
            options.backend = "meeko" if options.prepare_ligand.name == "mk_prepare_ligand.py" else "adfr"
        else:
            meeko = shutil.which("mk_prepare_ligand.py", path=environment.get("PATH"))
            options.backend = "meeko" if meeko else "adfr"
            found = meeko or shutil.which("prepare_ligand", path=environment.get("PATH"))
            options.prepare_ligand = Path(found) if found else None
    elif not options.prepare_ligand:
        name = "mk_prepare_ligand.py" if options.backend == "meeko" else "prepare_ligand"
        found = shutil.which(name, path=environment.get("PATH"))
        options.prepare_ligand = Path(found) if found else None
    if not options.obabel:
        found = shutil.which("obabel", path=environment.get("PATH"))
        options.obabel = Path(found) if found else None

    if not options.sdf_file.is_file():
        raise LigandUsageError(f"ERROR: SDF input not found: {options.sdf_file}")
    if not _executable(options.prepare_ligand):
        raise LigandRuntimeError(
            "ERROR: no executable ligand-preparation backend found. Install Meeko or use "
            "--backend adfr --prepare-ligand PATH."
        )
    if not _executable(options.obabel):
        raise LigandRuntimeError(
            "ERROR: obabel is not executable. Use --obabel or DOCKING_UNIVERSAL_OBABEL."
        )


def _run(command: Sequence[str], *, cwd: Path | None = None, quiet: bool = True) -> int:
    target = subprocess.DEVNULL if quiet else None
    return subprocess.run(command, cwd=cwd, stdout=target, stderr=target).returncode


def _compound_name(record: Path, field: str, fallback: str) -> str:
    lines = record.read_text(encoding="utf-8", errors="replace").splitlines()
    if field:
        marker = re.compile(rf"^> *<{re.escape(field)}>")
        for index, line in enumerate(lines[:-1]):
            if marker.search(line):
                return lines[index + 1].replace("\r", "") or fallback
        return fallback
    return (lines[0] if lines else "") or fallback


def prepare_ligands(
    options: LigandOptions,
    environment: Mapping[str, str],
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> LigandPreparationResult:
    raw_base = options.sdf_file.stem
    base_name = re.sub(r"[^A-Za-z0-9._-]", "_", raw_base)
    output_root = options.output_root or Path(base_name)
    work_dir = output_root / "ligand_work"
    output_dir = output_root / "pdbqt_ligands"
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_root / "preparation_manifest.tsv"
    manifest.write_text(
        "compound_id\tcompound_name\tbackend\ttarget_engines\tgeometry_mode\t"
        "charge_model\tinput\toutput\n", encoding="utf-8"
    )
    print(f"Ligand preparation backend: {options.backend} ({options.prepare_ligand})", file=stdout)
    print(f"Target docking engines: {options.target_engines}", file=stdout)

    total = successful = failed = 0
    with tempfile.TemporaryDirectory(prefix="docking-universal-ligands-") as temporary:
        temp_root = Path(temporary)
        shutil.copyfile(options.sdf_file, temp_root / "input.sdf")
        print("Splitting SDF...", file=stdout)
        subprocess.run(
            [str(options.obabel), str(temp_root / "input.sdf"), "-O", str(temp_root / "ligand.sdf"), "-m"],
            check=True, stdout=subprocess.DEVNULL, env=dict(environment)
        )
        records = sorted(temp_root.glob("ligand*.sdf"))
        if not records:
            raise LigandRuntimeError("ERROR: Open Babel did not split any SDF records")
        for total, record in enumerate(records, 1):
            compound_id = f"{base_name}_{total}"
            optimized_sdf = temp_root / f"{compound_id}_opt.sdf"
            optimized_mol2 = temp_root / f"{compound_id}_opt.mol2"
            prepared = temp_root / f"{compound_id}_opt.pdbqt"
            output_pdbqt = output_dir / f"{compound_id}.pdbqt"
            name = _compound_name(record, options.name_field, compound_id).replace("\n", "")
            smiles_run = subprocess.run(
                [str(options.obabel), str(record), "-osmi"], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=dict(environment)
            )
            smiles = smiles_run.stdout.split()[0] if smiles_run.stdout.split() else ""
            print(f"prepare  {compound_id}", file=stdout)
            if options.geometry_mode == "preserve":
                shutil.copyfile(record, optimized_sdf)
            elif _run(
                [
                    str(options.obabel),
                    str(record),
                    "-O",
                    str(optimized_sdf),
                    "--gen3d",
                    "--minimize",
                ]
            ) != 0:
                print(f"warning  3D optimization failed for {compound_id}", file=stderr)
                failed += 1
                continue
            if _run([str(options.obabel), str(optimized_sdf), "-O", str(optimized_mol2)]) != 0:
                print(f"warning  MOL2 conversion failed for {compound_id}", file=stderr)
                failed += 1
                continue
            if options.backend == "meeko":
                command = [
                    str(options.prepare_ligand),
                    "-i",
                    str(optimized_sdf),
                    "-o",
                    str(prepared),
                    "--charge_model",
                    options.charge_model,
                ]
                if options.target_engines == "qvinaw":
                    command.append("--rigid_macrocycles")
                failed_stage = _run(command) != 0
                warning = "Meeko ligand preparation"
            else:
                failed_stage = _run(
                    [str(options.prepare_ligand), "-l", optimized_mol2.name], cwd=temp_root
                ) != 0
                warning = "ADFRsuite ligand preparation"
            if failed_stage:
                print(f"warning  {warning} failed for {compound_id}", file=stderr)
                failed += 1
                continue
            alternate = temp_root / f"{compound_id}.pdbqt"
            if (
                (not prepared.is_file() or prepared.stat().st_size == 0)
                and alternate.is_file()
                and alternate.stat().st_size
            ):
                prepared = alternate
            if not prepared.is_file() or prepared.stat().st_size == 0:
                print(f"warning  no PDBQT was produced for {compound_id}", file=stderr)
                failed += 1
                continue
            with output_pdbqt.open("w", encoding="utf-8") as stream:
                if smiles:
                    stream.write(f"REMARK SMILES {smiles}\n")
                stream.write(f"REMARK NAME {name}\n")
                stream.write(prepared.read_text(encoding="utf-8", errors="replace"))
            shutil.copyfile(record, work_dir / f"{compound_id}.sdf")
            shutil.copyfile(optimized_sdf, work_dir / f"{compound_id}_opt.sdf")
            shutil.copyfile(optimized_mol2, work_dir / f"{compound_id}_opt.mol2")
            with manifest.open("a", encoding="utf-8") as stream:
                stream.write(
                    f"{compound_id}\t{name}\t{options.backend}\t{options.target_engines}\t"
                    f"{options.geometry_mode}\t{options.charge_model}\t{options.sdf_file}\t{output_pdbqt}\n"
                )
            successful += 1
    print("\nLigand preparation complete.", file=stdout)
    print(f"Total molecules:  {total}", file=stdout)
    print(f"Prepared PDBQT:   {successful}", file=stdout)
    print(f"Failed/skipped:   {failed}", file=stdout)
    print(f"Output directory: {output_dir}", file=stdout)
    return LigandPreparationResult(total, successful, failed, output_dir)


def main(arguments: Sequence[str] | None = None) -> int:
    environment = os.environ.copy()
    try:
        options = parse_arguments(sys.argv[1:] if arguments is None else arguments, environment)
        validate_and_resolve(options, environment)
        result = prepare_ligands(options, environment)
        return 0 if result.successful > 0 and result.failed == 0 else 1
    except SystemExit:
        print(USAGE, end="")
        return 0
    except LigandUsageError as error:
        if str(error):
            print(error, file=sys.stderr)
        if not str(error) or str(error).startswith("Unknown option:"):
            print(USAGE, end="", file=sys.stderr)
        return 2
    except LigandRuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        return error.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
