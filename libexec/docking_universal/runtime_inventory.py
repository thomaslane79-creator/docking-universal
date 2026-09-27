"""Read-only inventory of Docking Universal runtime dependencies.

The inventory deliberately reports observation separately from compatibility.
An absent package is not evidence that two installed packages are incompatible,
and this module never solves, installs, imports, or upgrades scientific packages.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SCHEMA_NAME = "docking-universal-runtime-inventory"
SCHEMA_VERSION = 1


def discover_poseedit_runtime(
    *, which: Callable[[str], str | None] = shutil.which,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Observe the complete local browser renderer without changing it."""
    values = dict(os.environ if environment is None else environment)
    renderer_root = Path(__file__).resolve().parent / "poseedit_renderer"
    explicit_node = values.get("DOCKING_UNIVERSAL_NODE")
    node = (
        str(Path(explicit_node).resolve()) if explicit_node and Path(explicit_node).is_file()
        else which("node")
    )
    node = str(Path(node).resolve()) if node else None
    explicit_chrome = values.get("DOCKING_UNIVERSAL_CHROME")
    candidates = [explicit_chrome, which("google-chrome"), which("chromium"), which("chromium-browser")]
    if platform.system() == "Darwin":
        candidates.extend((
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ))
    chrome = next((str(Path(item).resolve()) for item in candidates if item and Path(item).is_file()), None)
    playwright = None
    playwright_detail = None
    if node:
        try:
            result = subprocess.run(
                [node, "-e", "process.stdout.write(require.resolve('playwright'))"],
                capture_output=True, text=True, timeout=5, env=values, cwd=renderer_root,
            )
            if result.returncode == 0 and result.stdout.strip():
                playwright = str(Path(result.stdout.strip()).resolve())
            else:
                playwright_detail = (result.stderr or result.stdout).strip() or "module not resolved"
        except (OSError, subprocess.TimeoutExpired) as exc:
            playwright_detail = str(exc)
    assets = renderer_root / "assets"
    required_assets = (
        "interaction-drawer.js", "d3.min.js", "fraction.min.js",
        "smiles-drawer.min.js", "pack-scene.js",
    )
    missing_assets = [name for name in required_assets if not (assets / name).is_file()]
    components = {
        "node": {"status": "available" if node else "absent", "path": node},
        "playwright": {
            "status": "available" if playwright else ("unobserved" if not node else "absent"),
            "path": playwright, "detail": playwright_detail,
        },
        "chrome": {"status": "available" if chrome else "absent", "path": chrome},
        "bundled_assets": {
            "status": "available" if not missing_assets else "absent",
            "path": str(assets), "missing": missing_assets,
        },
    }
    ready = all(item["status"] == "available" for item in components.values())
    missing = [name for name, item in components.items() if item["status"] != "available"]
    return {
        "status": "available" if ready else "unavailable",
        "required_for": ["pose_interaction_rendering"],
        "components": components,
        "missing": missing,
        "detail": None if ready else "Missing local renderer components: " + ", ".join(missing),
    }


@dataclass(frozen=True)
class DependencySpec:
    id: str
    label: str
    role: str
    package_names: tuple[str, ...] = ()
    command_names: tuple[str, ...] = ()
    required_for: tuple[str, ...] = ()


@dataclass(frozen=True)
class DependencyObservation:
    id: str
    label: str
    role: str
    status: str
    version: str | None = None
    source: str | None = None
    path: str | None = None
    required_for: tuple[str, ...] = ()
    detail: str | None = None


@dataclass(frozen=True)
class EnvironmentObservation:
    name: str
    status: str
    prefix: str | None = None
    python_version: str | None = None
    python_executable: str | None = None
    packages: dict[str, str] = field(default_factory=dict)
    detail: str | None = None


PACKAGE_SPECS = (
    DependencySpec("pymol", "PyMOL Open Source", "required structural viewer", ("pymol-open-source", "pymol"), required_for=("visual_review", "render3d")),
    DependencySpec("rdkit", "RDKit", "chemistry, RMSD, clustering, and 2D depiction", ("rdkit",), required_for=("ligand_preparation", "analysis")),
    DependencySpec("meeko", "Meeko", "receptor and ligand parameterization", ("meeko",), required_for=("preparation",)),
    DependencySpec("pdbfixer", "PDBFixer", "conditional conservative receptor repair", ("pdbfixer",), required_for=("receptor_preparation",)),
    DependencySpec("openmm", "OpenMM", "PDBFixer runtime", ("openmm",), required_for=("receptor_preparation",)),
    DependencySpec("gemmi", "Gemmi", "Meeko receptor templates and structural data", ("gemmi",), required_for=("receptor_preparation",)),
    DependencySpec("molscrub", "MolScrub", "ligand state and conformer preparation", ("molscrub",), required_for=("ligand_preparation",)),
    DependencySpec("prody", "ProDy", "structural analysis dependency", ("prody",), required_for=("structural_analysis",)),
    DependencySpec("biopython", "Biopython", "structural sequence support", ("biopython",), required_for=("structural_analysis",)),
    DependencySpec("numpy", "NumPy", "scientific array runtime", ("numpy",), required_for=("scientific_core",)),
    DependencySpec("scipy", "SciPy", "scientific calculations", ("scipy",), required_for=("scientific_core",)),
    DependencySpec("pillow", "Pillow", "image handling", ("pillow",), required_for=("reports", "visualization")),
    DependencySpec("matplotlib", "Matplotlib", "plots and report figures", ("matplotlib", "matplotlib-base"), required_for=("reports",)),
    DependencySpec("reportlab", "ReportLab", "PDF report generation", ("reportlab",), required_for=("reports",)),
    DependencySpec("pycairo", "PyCairo", "PyMOL graphics runtime", ("pycairo",), required_for=("visual_review",)),
    DependencySpec("pyqt", "PyQt", "installed PyMOL Qt binding", ("pyqt", "PyQt5"), required_for=("visual_review",)),
    DependencySpec("qt", "Qt runtime", "installed PyMOL GUI runtime", ("qt-main", "qt"), required_for=("visual_review",)),
    DependencySpec("boost", "Boost runtime", "compiled PyMOL/scientific runtime", ("libboost", "boost-cpp"), required_for=("visual_review",)),
    DependencySpec("boost_python", "Boost.Python runtime", "PyMOL Python extension runtime", ("libboost-python",), required_for=("visual_review",)),
    DependencySpec("cairo", "Cairo", "graphics runtime", ("cairo",), required_for=("visual_review", "reports")),
    DependencySpec("glew", "GLEW", "PyMOL OpenGL runtime", ("glew",), required_for=("visual_review",)),
    DependencySpec("glm", "GLM", "PyMOL graphics mathematics runtime", ("glm",), required_for=("visual_review",)),
    DependencySpec("libjpeg", "JPEG runtime", "image encoding", ("libjpeg-turbo",), required_for=("visualization", "reports")),
    DependencySpec("libpng", "PNG runtime", "image encoding", ("libpng",), required_for=("visualization", "reports")),
    DependencySpec("pyside6", "PySide6", "candidate desktop GUI toolkit", ("pyside6",), required_for=("future_gui_candidate",)),
)


COMMAND_SPECS = (
    DependencySpec("fpocket", "fpocket", "cavity detection", command_names=("fpocket",), required_for=("site_guided_protocol",)),
    DependencySpec("p2rank", "P2Rank", "maintained machine-learning pocket detection", command_names=("prank", "p2rank"), required_for=("site_guided_protocol",)),
    DependencySpec("java", "Java runtime", "P2Rank runtime", command_names=("java",), required_for=("p2rank",)),
    DependencySpec("openbabel", "Open Babel", "molecular conversion and PLIP backend", command_names=("obabel",), required_for=("preparation", "analysis")),
    DependencySpec("plip", "PLIP", "interaction analysis", command_names=("plip",), required_for=("interactions",)),
    DependencySpec("pymol_command", "PyMOL executable", "required structural viewer", command_names=("pymol",), required_for=("visual_review", "render3d")),
    DependencySpec("meeko_receptor", "Meeko receptor command", "primary receptor preparation", command_names=("mk_prepare_receptor.py",), required_for=("receptor_preparation",)),
    DependencySpec("meeko_ligand", "Meeko ligand command", "primary ligand preparation", command_names=("mk_prepare_ligand.py",), required_for=("ligand_preparation",)),
    DependencySpec("adfr_receptor", "ADFRsuite prepare_receptor", "conditional linked-component compatibility fallback", command_names=("prepare_receptor",), required_for=("adfrsuite_fallback",)),
    DependencySpec("adfr_ligand", "ADFRsuite prepare_ligand", "legacy compatibility fallback", command_names=("prepare_ligand",), required_for=("adfrsuite_fallback",)),
    DependencySpec("make", "Make", "installation and source validation", command_names=("make",), required_for=("source_install",)),
    DependencySpec("conda", "Conda", "environment launching and installation", command_names=("conda",), required_for=("environment_management",)),
    DependencySpec("bash", "Bash", "installed launcher and scientific compatibility helpers", command_names=("bash",), required_for=("launcher",)),
    DependencySpec("awk", "AWK", "installed launcher support", command_names=("awk",), required_for=("launcher",)),
    DependencySpec("grep", "grep", "installed launcher support", command_names=("grep",), required_for=("launcher",)),
    DependencySpec("sed", "sed", "installed launcher support", command_names=("sed",), required_for=("launcher",)),
    DependencySpec("sort", "sort", "installed launcher support", command_names=("sort",), required_for=("launcher",)),
    DependencySpec("tee", "tee", "complete pipeline logging", command_names=("tee",), required_for=("launcher",)),
)


ENVIRONMENT_PACKAGES = {
    "docking-universal": (
        "python", "pymol-open-source", "rdkit", "meeko", "pdbfixer", "openmm", "gemmi",
        "molscrub", "prody", "biopython", "numpy", "scipy", "pillow", "matplotlib-base",
        "reportlab", "pycairo", "pyqt", "qt-main", "libboost", "libboost-python", "cairo",
        "glew", "glm", "libjpeg-turbo", "libpng", "fpocket", "openbabel", "plip",
    ),
    "docking-universal-vina": ("python", "vina", "libboost", "boost-cpp", "numpy"),
    "docking-universal-qvinaw": ("python", "qvina", "libboost", "boost-cpp"),
}


def _run_json(command: Sequence[str], timeout: float = 15.0) -> tuple[Any | None, str | None]:
    try:
        completed = subprocess.run(
            list(command), check=False, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if completed.returncode != 0:
        return None, (completed.stderr or completed.stdout).strip() or f"exit status {completed.returncode}"
    try:
        return json.loads(completed.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"


def _conda_environments(conda: str) -> tuple[dict[str, str], str | None]:
    payload, error = _run_json((conda, "env", "list", "--json"))
    if error:
        return {}, error
    environments = {}
    for value in payload.get("envs", []):
        path = Path(value)
        environments[path.name] = str(path)
    return environments, None


def _conda_packages(conda: str, environment: str) -> tuple[dict[str, dict[str, str]], str | None]:
    payload, error = _run_json((conda, "list", "-n", environment, "--json"))
    if error:
        return {}, error
    return {str(item["name"]).lower(): item for item in payload}, None


def _first_package(packages: Mapping[str, Mapping[str, str]], names: Sequence[str]) -> Mapping[str, str] | None:
    for name in names:
        if name.lower() in packages:
            return packages[name.lower()]
    return None


def _current_distribution(names: Sequence[str]) -> tuple[str | None, str | None]:
    for name in names:
        try:
            return importlib.metadata.version(name), name
        except importlib.metadata.PackageNotFoundError:
            continue
    return None, None


def _observe_package(spec: DependencySpec, packages: Mapping[str, Mapping[str, str]] | None) -> DependencyObservation:
    if packages is not None:
        item = _first_package(packages, spec.package_names)
        if item:
            return DependencyObservation(
                spec.id, spec.label, spec.role, "available", str(item.get("version", "unknown")),
                str(item.get("channel") or item.get("base_url") or "conda"),
                required_for=spec.required_for,
            )
        return DependencyObservation(spec.id, spec.label, spec.role, "absent", required_for=spec.required_for)
    version, source = _current_distribution(spec.package_names)
    return DependencyObservation(
        spec.id, spec.label, spec.role, "available" if version else "absent",
        version, source, required_for=spec.required_for,
    )


def _command_search_paths(environment_prefix: str | None) -> list[str]:
    paths = []
    if environment_prefix:
        paths.append(str(Path(environment_prefix) / ("Scripts" if os.name == "nt" else "bin")))
    paths.extend(os.environ.get("PATH", "").split(os.pathsep))
    return [path for path in paths if path]


def _which(names: Sequence[str], paths: Sequence[str]) -> str | None:
    search_path = os.pathsep.join(paths)
    for name in names:
        found = shutil.which(name, path=search_path)
        if found:
            return str(Path(found).resolve())
    return None


def _observe_command(spec: DependencySpec, paths: Sequence[str], version: str | None = None) -> DependencyObservation:
    path = _which(spec.command_names, paths)
    return DependencyObservation(
        spec.id, spec.label, spec.role, "available" if path else "absent",
        version=version, path=path, required_for=spec.required_for,
    )


def _platform_tools(paths: Sequence[str]) -> list[DependencyObservation]:
    system = platform.system()
    specs = []
    if system == "Darwin":
        specs = [
            DependencySpec("finder_chooser", "Finder chooser", "platform file selection", command_names=("osascript",), required_for=("interactive_file_selection",)),
            DependencySpec("open_command", "macOS open", "open retained artifacts", command_names=("open",), required_for=("artifact_viewing",)),
        ]
    elif system == "Linux":
        specs = [
            DependencySpec("zenity", "Zenity", "preferred graphical file selection", command_names=("zenity",), required_for=("interactive_file_selection",)),
        ]
    observations = [_observe_command(spec, paths) for spec in specs]
    tkinter_status = "available" if importlib.util.find_spec("tkinter") else "absent"
    observations.append(DependencyObservation(
        "tkinter", "Tkinter", "fallback graphical file selection", tkinter_status,
        source="Python standard library", required_for=("interactive_file_selection_fallback",),
    ))
    return observations


def _declared_packages(path: Path) -> dict[str, str]:
    """Read simple dependency declarations without adding a YAML dependency."""
    declared: dict[str, str] = {}
    if not path.is_file():
        return declared
    if path.name == "requirements-pip-lock.txt":
        for line in path.read_text().splitlines():
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            name, marker, version = value.partition("==")
            declared[name.lower()] = version if marker else "unversioned"
        return declared
    if path.suffix in {".yml", ".yaml"}:
        in_dependencies = False
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped == "dependencies:":
                in_dependencies = True
                continue
            if not in_dependencies or not stripped.startswith("-"):
                continue
            value = stripped[1:].strip()
            if not value or value == "pip:" or value == "pip":
                continue
            name, separator, version = value.partition("=")
            declared[name.lower()] = version.lstrip("=") if separator else "unversioned"
    return declared


def _declaration(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "status": "absent", "sha256": None, "dependencies": {}}
    content = path.read_bytes()
    return {
        "path": str(path),
        "status": "available",
        "sha256": hashlib.sha256(content).hexdigest(),
        "dependencies": _declared_packages(path),
    }


def collect_runtime_inventory(
    *,
    main_environment: str = "docking-universal",
    vina_environment: str = "docking-universal-vina",
    qvinaw_environment: str = "docking-universal-qvinaw",
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """Collect an observation-only inventory suitable for JSON persistence."""
    conda = which("conda")
    environment_names = (main_environment, vina_environment, qvinaw_environment)
    environments: list[EnvironmentObservation] = []
    conda_error = None
    prefixes: dict[str, str] = {}
    if conda:
        prefixes, conda_error = _conda_environments(conda)

    packages_by_environment: dict[str, dict[str, dict[str, str]]] = {}
    for name in environment_names:
        if not conda:
            environments.append(EnvironmentObservation(name, "unobserved", detail="Conda executable not found"))
            continue
        if name not in prefixes:
            environments.append(EnvironmentObservation(name, "absent"))
            continue
        packages, error = _conda_packages(conda, name)
        packages_by_environment[name] = packages
        wanted = ENVIRONMENT_PACKAGES.get(name, ())
        selected = {
            package: packages[package]["version"]
            for package in wanted if package in packages
        }
        environments.append(EnvironmentObservation(
            name=name,
            status="available" if not error else "error",
            prefix=prefixes[name],
            python_version=packages.get("python", {}).get("version"),
            python_executable=(
                str(Path(prefixes[name]) / ("python.exe" if os.name == "nt" else "bin/python"))
                if "python" in packages else None
            ),
            packages=selected,
            detail=error,
        ))

    main_prefix = prefixes.get(main_environment)
    main_packages = packages_by_environment.get(main_environment)
    paths = _command_search_paths(main_prefix)
    package_observations = [_observe_package(spec, main_packages) for spec in PACKAGE_SPECS]
    command_versions = {
        "fpocket": "fpocket", "openbabel": "openbabel", "plip": "plip",
        "pymol_command": "pymol-open-source", "meeko_receptor": "meeko", "meeko_ligand": "meeko",
    }
    command_observations = [
        _observe_command(
            spec,
            paths,
            (main_packages or {}).get(command_versions.get(spec.id, ""), {}).get("version"),
        )
        for spec in COMMAND_SPECS
    ]
    for identifier, label, environment_name, executable, package in (
        ("vina", "AutoDock Vina", vina_environment, "vina", "vina"),
        ("qvinaw", "QuickVina-W", qvinaw_environment, "qvinaw", "qvina"),
    ):
        environment_packages = packages_by_environment.get(environment_name, {})
        command_observations.append(_observe_command(
            DependencySpec(identifier, label, "docking engine", command_names=(executable,), required_for=("docking",)),
            _command_search_paths(prefixes.get(environment_name)),
            environment_packages.get(package, {}).get("version"),
        ))
    command_observations.extend(_platform_tools(paths))

    declarations = []
    project_root = Path(__file__).resolve().parents[2]
    for relative in ("environment.yml", "environment-lock-osx-arm64.txt", "requirements-pip-lock.txt", "environments/vina.yml", "environments/vina-lock-osx-arm64.txt", "environments/qvinaw.yml"):
        path = project_root / relative
        declarations.append(_declaration(path))

    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "observation_policy": "available, absent, unobserved, and error are observations; incompatibility is never inferred",
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
        },
        "conda": {"path": conda, "status": "available" if conda else "absent", "detail": conda_error},
        "environments": [asdict(item) for item in environments],
        "packages": [asdict(item) for item in package_observations],
        "commands": [asdict(item) for item in command_observations],
        "poseedit_renderer": discover_poseedit_runtime(which=which),
        "declarations": declarations,
    }


def render_runtime_inventory(inventory: Mapping[str, Any]) -> str:
    host = inventory["host"]
    lines = [
        f"Host: {host['system']} {host['release']} ({host['machine']})",
        f"Probe Python: {host['python_version']} ({host['python_executable']})",
        "",
        "Conda environments",
    ]
    for environment in inventory["environments"]:
        detail = f"; {environment['detail']}" if environment.get("detail") else ""
        python_version = f"; Python {environment['python_version']}" if environment.get("python_version") else ""
        lines.append(f"  {environment['status']:10} {environment['name']}{python_version}{detail}")
    for heading, key in (("Scientific packages", "packages"), ("Commands and platform tools", "commands")):
        lines.extend(("", heading))
        for item in inventory[key]:
            value = item.get("version") or item.get("path") or ""
            lines.append(f"  {item['status']:10} {item['label']}{(': ' + value) if value else ''}")
    renderer = inventory.get("poseedit_renderer", {})
    lines.extend(("", "PoseEdit-style local renderer"))
    lines.append(f"  {renderer.get('status', 'unobserved'):10} complete rendering capability")
    for name, item in renderer.get("components", {}).items():
        value = item.get("path") or item.get("detail") or ""
        lines.append(f"  {item['status']:10} {name}{(': ' + value) if value else ''}")
    lines.extend(("", "No compatibility conclusion is inferred from an absent or unobserved item."))
    return "\n".join(lines) + "\n"
