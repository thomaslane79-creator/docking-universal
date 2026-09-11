#!/usr/bin/env python3
"""Run a prepared ligand batch with a Vina-family docking engine.

This module is independent of terminal and GUI frameworks. The command-line
adapter builds :class:`DockOptions`; future clients can call ``run_docking``
directly while preserving the same command construction and artifacts.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence, TextIO


USAGE = """Usage:
  docking-universal dock
  docking-universal dock --receptor receptor.pdbqt --ligands DIR --config box.conf --out DIR [options]

With no options, macOS Finder or an Ubuntu graphical chooser selects the prepared
receptor, docking box, ligand input, and output directory. Headless sessions ask
for exact paths. An SDF ligand input is prepared automatically.

Options:
  --engine NAME            vina or qvinaw (QuickVina-W)
  --engine-command PATH    Explicit engine executable
  --engine-env NAME        Conda environment containing the engine
  --exhaustiveness N       Forwarded to the selected engine when provided
  --num-modes N            Maximum output poses requested from the engine
  --energy-range KCAL      Maximum energy range retained from the best pose
  --seed N                 Reproducible engine random seed
  --skip-existing          Preserve existing output files
  -h, --help               Show this help
"""


class DockUsageError(Exception):
    """A command-line selection or option is invalid."""


class DockRuntimeError(Exception):
    """A required input or external executable is unavailable."""


@dataclass
class DockOptions:
    """Validated inputs and optional engine settings for one ligand batch."""

    engine: str = "vina"
    receptor: Path | None = None
    ligand_dir: Path | None = None
    config: Path | None = None
    output_dir: Path | None = None
    exhaustiveness: str | None = None
    num_modes: str | None = None
    energy_range: str | None = None
    seed: str | None = None
    skip_existing: bool = False
    engine_command: Path | None = None
    engine_env: str | None = None


@dataclass(frozen=True)
class EngineInvocation:
    """Resolved executable prefix and provenance label written to disk."""

    command: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class DockBatchResult:
    """Machine-readable summary of a completed batch attempt."""

    output_dir: Path
    successful: int
    failed: int
    skipped: int


def _print_usage(stream: TextIO) -> None:
    stream.write(USAGE)


def parse_arguments(arguments: Sequence[str]) -> DockOptions:
    """Parse the legacy option surface without changing accepted spellings."""

    options = DockOptions()
    value_options = {
        "--engine": "engine",
        "--engine-command": "engine_command",
        "--engine-env": "engine_env",
        "--receptor": "receptor",
        "--ligands": "ligand_dir",
        "--config": "config",
        "--out": "output_dir",
        "--exhaustiveness": "exhaustiveness",
        "--num-modes": "num_modes",
        "--energy-range": "energy_range",
        "--seed": "seed",
    }
    path_fields = {"engine_command", "receptor", "ligand_dir", "config", "output_dir"}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in ("-h", "--help"):
            raise SystemExit(0)
        if argument == "--skip-existing":
            options.skip_existing = True
            index += 1
            continue
        field = value_options.get(argument)
        if field is None:
            raise DockUsageError(f"Unknown option: {argument}")
        if index + 1 >= len(arguments):
            raise DockUsageError(f"ERROR: option requires a value: {argument}")
        value: str | Path = arguments[index + 1]
        if field in path_fields:
            value = Path(value)
        setattr(options, field, value)
        index += 2

    if options.engine in ("quickvina-w", "qvina-w"):
        options.engine = "qvinaw"
    return options


def _python_command(environment: Mapping[str, str]) -> str:
    return environment.get("DOCKING_UNIVERSAL_PYTHON", "python")


def _choose_interactively(
    prompt: str,
    kind: str,
    chooser: Path,
    environment: Mapping[str, str],
    stdin: TextIO,
    stderr: TextIO,
) -> str:
    """Use the existing graphical chooser when available, otherwise stdin."""

    python = _python_command(environment)
    available = subprocess.run(
        [python, str(chooser), "--available"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=dict(environment),
    ).returncode == 0
    if available:
        backend = subprocess.run(
            [python, str(chooser), "--label"],
            check=True,
            text=True,
            capture_output=True,
            env=dict(environment),
        ).stdout.strip()
        if backend == "Finder":
            print(f"{prompt} in Finder now.", file=stderr)
        else:
            print(f"{prompt} with {backend} now.", file=stderr)
        command = [python, str(chooser), "--prompt", prompt]
        if kind == "folder":
            command.append("--folder")
        selected = subprocess.run(
            command,
            text=True,
            capture_output=True,
            env=dict(environment),
        )
        if selected.returncode != 0:
            raise DockUsageError(f"ERROR: graphical selection cancelled: {prompt}")
        result = selected.stdout.strip()
    else:
        print(prompt, file=stderr)
        print("Exact path: ", end="", file=stderr, flush=True)
        result = stdin.readline().rstrip("\n")
    if not result:
        raise DockUsageError(f"ERROR: no selection was provided: {prompt}")
    return result


def collect_interactive_options(
    script_dir: Path,
    environment: Mapping[str, str],
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> DockOptions:
    """Collect the legacy no-argument workflow selections."""

    chooser = script_dir / "docking-universal-choose-path.py"
    if not chooser.is_file():
        raise DockUsageError(f"ERROR: graphical-selection helper is missing: {chooser}")

    receptor = Path(
        _choose_interactively(
            "Choose the prepared receptor PDBQT",
            "file",
            chooser,
            environment,
            stdin,
            stderr,
        )
    )
    config = Path(
        _choose_interactively(
            "Choose the prepared docking-box configuration (.conf file)",
            "file",
            chooser,
            environment,
            stdin,
            stderr,
        )
    )
    if receptor.suffix != ".pdbqt":
        raise DockUsageError(f"ERROR: prepared receptor must be a .pdbqt file: {receptor}")
    if config.suffix != ".conf":
        raise DockUsageError(f"ERROR: docking-box configuration must be a .conf file: {config}")

    print("Choose the ligand input:", file=stdout)
    print("  1) Raw ligand SDF (prepare it automatically)", file=stdout)
    print("  2) One prepared ligand PDBQT", file=stdout)
    print("  3) Directory of prepared ligand PDBQT files", file=stdout)
    ligand_choice = stdin.readline().rstrip("\n")
    ligand_sdf: Path | None = None
    ligand_file: Path | None = None
    ligand_dir: Path | None = None
    if ligand_choice == "1":
        ligand_sdf = Path(
            _choose_interactively(
                "Choose the ligand SDF", "file", chooser, environment, stdin, stderr
            )
        )
        if ligand_sdf.suffix != ".sdf":
            raise DockUsageError(f"ERROR: raw ligand input must be a .sdf file: {ligand_sdf}")
    elif ligand_choice == "2":
        ligand_file = Path(
            _choose_interactively(
                "Choose the prepared ligand PDBQT",
                "file",
                chooser,
                environment,
                stdin,
                stderr,
            )
        )
        if ligand_file.suffix != ".pdbqt":
            raise DockUsageError(f"ERROR: prepared ligand must be a .pdbqt file: {ligand_file}")
    elif ligand_choice == "3":
        ligand_dir = Path(
            _choose_interactively(
                "Choose the prepared ligand PDBQT directory",
                "folder",
                chooser,
                environment,
                stdin,
                stderr,
            )
        )
    else:
        raise DockUsageError("ERROR: choose ligand input 1, 2, or 3")

    output_dir = Path(
        _choose_interactively(
            "Choose the docking output directory",
            "folder",
            chooser,
            environment,
            stdin,
            stderr,
        )
    )
    if ligand_sdf is not None:
        cli = environment.get("DOCKING_UNIVERSAL_CLI") or shutil.which("docking-universal")
        if not cli:
            raise DockRuntimeError(
                "ERROR: docking-universal launcher not found for ligand preparation"
            )
        print("Cleaning and optimizing the selected SDF before docking...", file=stdout)
        subprocess.run(
            [
                cli,
                "ligands",
                str(ligand_sdf),
                "--out",
                str(output_dir / "ligand_preparation"),
                "--target-engines",
                "vina",
                "--geometry-mode",
                "optimize",
            ],
            check=True,
            env=dict(environment),
        )
        ligand_dir = output_dir / "ligand_preparation" / "pdbqt_ligands"
    elif ligand_file is not None:
        ligand_dir = output_dir / "selected_ligands"
        ligand_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ligand_file, ligand_dir / ligand_file.name)

    return DockOptions(
        receptor=receptor,
        ligand_dir=ligand_dir,
        config=config,
        output_dir=output_dir,
    )


def validate_options(options: DockOptions, region_check: Path) -> None:
    """Fail before engine discovery if prepared inputs are incomplete or invalid."""

    if not all((options.receptor, options.ligand_dir, options.config, options.output_dir)):
        raise DockUsageError(
            "ERROR: prepared docking inputs are required. Run 'docking-universal prepare' first.\n"
            "Then prepare the compounds with 'docking-universal ligands' before running dock."
        )
    if options.engine not in ("vina", "qvinaw"):
        raise DockUsageError("ERROR: --engine must be vina or qvinaw (QuickVina-W)")
    if not options.receptor.is_file():
        raise DockRuntimeError(
            f"ERROR: prepared receptor not found: {options.receptor}. "
            "Run 'docking-universal prepare' first."
        )
    if not options.config.is_file():
        raise DockRuntimeError(
            f"ERROR: prepared docking-box config not found: {options.config}. "
            "Run 'docking-universal prepare' first."
        )
    if not options.ligand_dir.is_dir():
        raise DockRuntimeError(
            f"ERROR: prepared ligand directory not found: {options.ligand_dir}. "
            "Run 'docking-universal ligands' first."
        )
    if not region_check.is_file():
        raise DockRuntimeError(f"ERROR: docking-box preflight helper is missing: {region_check}")


def resolve_engine(options: DockOptions, environment: Mapping[str, str]) -> EngineInvocation:
    """Resolve an explicit, PATH, or Conda engine using the legacy precedence."""

    explicit = options.engine_command
    if explicit is None:
        variable = (
            "DOCKING_UNIVERSAL_VINA"
            if options.engine == "vina"
            else "DOCKING_UNIVERSAL_QVINAW"
        )
        configured = environment.get(variable)
        explicit = Path(configured) if configured else None
    if explicit is not None:
        if not explicit.is_file() or not os.access(explicit, os.X_OK):
            raise DockRuntimeError(f"ERROR: engine executable is not executable: {explicit}")
        return EngineInvocation((str(explicit),), "explicit executable")

    path_engine = shutil.which(options.engine, path=environment.get("PATH"))
    if path_engine:
        return EngineInvocation((path_engine,), "PATH")

    engine_env = options.engine_env
    if not engine_env:
        variable = (
            "DOCKING_UNIVERSAL_VINA_ENV"
            if options.engine == "vina"
            else "DOCKING_UNIVERSAL_QVINAW_ENV"
        )
        default = (
            "docking-universal-vina"
            if options.engine == "vina"
            else "docking-universal-qvinaw"
        )
        engine_env = environment.get(variable, default)
    if not engine_env:
        raise DockRuntimeError(
            f"ERROR: {options.engine} not found in PATH; use --engine-command or --engine-env"
        )
    conda = shutil.which("conda", path=environment.get("PATH"))
    if not conda:
        raise DockRuntimeError(f"ERROR: conda is required to use --engine-env {engine_env}")
    probe = subprocess.run(
        [conda, "run", "-n", engine_env, options.engine, "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=dict(environment),
    )
    if probe.returncode != 0:
        raise DockRuntimeError(
            f"ERROR: {options.engine} is not runnable from Conda environment: {engine_env}"
        )
    return EngineInvocation(
        (conda, "run", "--no-capture-output", "-n", engine_env, options.engine),
        f"conda environment {engine_env}",
    )


def _engine_version(invocation: EngineInvocation, environment: Mapping[str, str]) -> str:
    completed = subprocess.run(
        [*invocation.command, "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=dict(environment),
    )
    return next((line for line in completed.stdout.splitlines() if line.strip()), "unknown")


def _write_manifest(options: DockOptions, invocation: EngineInvocation, version: str) -> None:
    manifest_values = (
        ("engine", options.engine),
        ("engine_version", version),
        ("engine_source", invocation.source),
        ("engine_command", " ".join(invocation.command)),
        ("date", datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")),
        ("receptor", str(options.receptor)),
        ("ligand_dir", str(options.ligand_dir)),
        ("config", str(options.config)),
        ("exhaustiveness", options.exhaustiveness or "engine_default"),
        ("num_modes", options.num_modes or "engine_default"),
        ("energy_range_kcal_per_mol", options.energy_range or "engine_default"),
        ("seed", options.seed or "engine_random"),
    )
    (options.output_dir / "run_manifest.tsv").write_text(
        "".join(f"{key}\t{value}\n" for key, value in manifest_values), encoding="utf-8"
    )
    shutil.copyfile(options.config, options.output_dir / f"{options.config.name}.used")


def _engine_arguments(options: DockOptions, ligand: Path, output: Path) -> list[str]:
    arguments = [
        "--receptor",
        str(options.receptor),
        "--ligand",
        str(ligand),
        "--config",
        str(options.config),
        "--out",
        str(output),
    ]
    for flag, value in (
        ("--exhaustiveness", options.exhaustiveness),
        ("--num_modes", options.num_modes),
        ("--energy_range", options.energy_range),
        ("--seed", options.seed),
    ):
        if value is not None:
            arguments.extend((flag, value))
    return arguments


def run_docking(
    options: DockOptions,
    invocation: EngineInvocation,
    environment: Mapping[str, str],
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> DockBatchResult:
    """Run every prepared ligand, retaining successful jobs after failures."""

    options.output_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest(options, invocation, _engine_version(invocation, environment))
    ligands = sorted(
        ligand
        for ligand in options.ligand_dir.glob("*.pdbqt")
        if not ligand.name.endswith("_out.pdbqt")
    )
    if not ligands:
        raise DockRuntimeError(f"ERROR: no PDBQT ligands found in {options.ligand_dir}")

    successful = failed = skipped = 0
    for ligand in ligands:
        base = ligand.stem
        output = options.output_dir / f"{base}_{options.engine}.pdbqt"
        log_file = options.output_dir / f"{base}_{options.engine}.log"
        if options.skip_existing and output.is_file() and output.stat().st_size > 0:
            print(f"skip  {base}", file=stdout)
            skipped += 1
            continue
        print(f"run   {base}", file=stdout)
        with log_file.open("wb") as log_stream:
            try:
                completed = subprocess.run(
                    [*invocation.command, *_engine_arguments(options, ligand, output)],
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    env=dict(environment),
                )
                returncode = completed.returncode
            except OSError as error:
                log_stream.write(f"{error}\n".encode())
                returncode = 1
        if returncode != 0:
            print(f"ERROR: {options.engine} failed for {base}; see {log_file}", file=stderr)
            failed += 1
            output.unlink(missing_ok=True)
            continue
        if not output.is_file() or output.stat().st_size == 0:
            print(f"ERROR: no output for {base}; see {log_file}", file=stderr)
            failed += 1
            output.unlink(missing_ok=True)
            continue
        successful += 1

    print(f"Batch complete: {options.output_dir}", file=stdout)
    print(f"Successful docking jobs: {successful}", file=stdout)
    print(f"Failed docking jobs: {failed}", file=stdout)
    print(f"Skipped existing jobs: {skipped}", file=stdout)
    return DockBatchResult(options.output_dir, successful, failed, skipped)


def main(arguments: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    environment = os.environ.copy()
    script_dir = Path(__file__).resolve().parent
    try:
        options = parse_arguments(arguments) if arguments else collect_interactive_options(
            script_dir, environment, sys.stdin, sys.stdout, sys.stderr
        )
        region_check = script_dir / "docking-universal-region-check.py"
        validate_options(options, region_check)
        subprocess.run(
            [
                _python_command(environment),
                str(region_check),
                "--receptor",
                str(options.receptor),
                "--config",
                str(options.config),
            ],
            check=True,
            env=environment,
        )
        invocation = resolve_engine(options, environment)
        result = run_docking(options, invocation, environment)
        return 1 if result.failed else 0
    except SystemExit as exit_request:
        _print_usage(sys.stdout)
        return int(exit_request.code or 0)
    except DockUsageError as error:
        print(error, file=sys.stderr)
        if (
            str(error).startswith("Unknown option:")
            or "prepared docking inputs are required" in str(error)
        ):
            _print_usage(sys.stderr)
        return 2
    except DockRuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        return error.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
