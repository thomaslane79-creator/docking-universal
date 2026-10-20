"""Owned Windows scientific CLI; GUI/control capabilities remain separately gated."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from .runtime_layout import executable_directories


STAGES = {
    "_screen-stage": "docking-universal-screen.py",
    "depict2d": "docking-universal-depict2d.py",
    "ligands": "docking_universal_ligands.py",
    "dock": "docking_universal_dock.py",
    "collect": "docking-universal-collect.py",
    "cluster-poses": "docking-universal-cluster-poses.py",
    "render3d": "docking-universal-render3d.py",
    "interactions": "docking-universal-interactions.py",
    "screen": "docking-universal-run.py",
}


def owned_scientific_python(app: Path, configuration: dict):
    """Only this application's owned manager may host an external runtime."""
    root = app.parent.resolve()
    manager = configuration.get("scientific_manager")
    expected = root / "runtimes/scientific/python.exe"
    if manager:
        prefix = Path(manager["prefix"]).resolve()
        identity = manager["install_id"]
        if not re.fullmatch(r"[a-f0-9]{32}", identity) or prefix.name != identity:
            raise ValueError("Invalid owned scientific manager identity")
        owner = json.loads((prefix / "docking-universal-owner.json").read_text(encoding="utf-8"))
        if (owner.get("schema") != "docking-universal-private-manager-v1"
                or Path(owner.get("installation", "")).resolve() != root
                or owner.get("install_id") != identity or owner.get("sha256") != manager["asset"]["sha256"]
                or Path(configuration["package_manager_conda"]).resolve() != (prefix / "Scripts/conda.exe").resolve()):
            raise ValueError("Scientific manager belongs to another installation or its ownership record changed")
        expected = prefix / "runtimes/scientific/python.exe"
    selected = (root / configuration["scientific_python"]).resolve()
    if selected != expected.resolve():
        raise ValueError("Scientific interpreter escaped its exact owned runtime")
    return selected


def scientific_environment(app: Path, configuration: dict, inherited: dict):
    root = app.parent.resolve()
    receipt_path = (root / configuration["scientific_receipt"]).resolve()
    python = owned_scientific_python(app, configuration)
    if not receipt_path.is_relative_to(root):
        raise ValueError("Scientific runtime receipt escaped the owned installation")
    if hashlib.sha256(receipt_path.read_bytes()).hexdigest() != configuration["scientific_receipt_sha256"]:
        raise ValueError("Scientific dependency receipt changed; no job was started")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "dependencies_installed" or Path(receipt.get("python", "")).resolve() != python or not python.is_file():
        raise ValueError("Scientific dependency installation is incomplete")
    for name in ("java", "node"):
        executable = Path(receipt[name]).resolve()
        if not executable.is_relative_to(python.parent) or not executable.is_file():
            raise ValueError(f"Owned scientific executable is missing: {name}")
    if Path(receipt["p2rank"]).resolve() != (python.parent.parent.parent / "share/p2rank-2.5.1").resolve():
        raise ValueError("P2Rank escaped the owned installation")
    transport = receipt.get("java_argument_transport")
    if not isinstance(transport, dict):
        raise ValueError("Scientific runtime is missing its accepted Unicode argument transport")
    launcher = Path(receipt["p2rank"]) / "docking-universal-launcher"
    for filename, key in (("NativeArguments.java", "source_sha256"), ("NativeArguments.class", "class_sha256")):
        if hashlib.sha256((launcher / filename).read_bytes()).hexdigest() != transport.get(key):
            raise ValueError("Unicode Java argument transport changed; no job was started")
    engine = (root / configuration["vina_executable"]).resolve()
    if not engine.is_relative_to(root / "engines"):
        raise ValueError("Pinned Vina escaped the owned engine directory")
    if hashlib.sha256(engine.read_bytes()).hexdigest() != configuration["vina_sha256"]:
        raise ValueError("Pinned native Vina checksum mismatch; no job was started")
    environment = dict(inherited)
    for name in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH",
                 'QT_OPENGL', 'QT_OPENGL_DLL', 'GALLIUM_DRIVER', 'LIBGL_ALWAYS_SOFTWARE'):
        environment.pop(name, None)
    environment["PATH"] = os.pathsep.join([*(str(path) for path in executable_directories(python.parent, windows=True)), environment.get("PATH", "")])
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", DOCKING_UNIVERSAL_PYTHON=str(python),
        DOCKING_UNIVERSAL_LIBEXEC=str(app), DOCKING_UNIVERSAL_CLI=str(app / "docking-universal-native.py"),
        DOCKING_UNIVERSAL_VINA=str(engine), DOCKING_UNIVERSAL_VINA_BACKEND="cli",
        DOCKING_UNIVERSAL_NODE=receipt["node"], DOCKING_UNIVERSAL_CHROME=receipt["browser"],
        DOCKING_UNIVERSAL_NATIVE_STAGING_ROOT=str(python.parent / 'share/docking-universal/native-staging'),
        DOCKING_UNIVERSAL_P2RANK_DIR=receipt["p2rank"])
    return python, environment, receipt


def require_vina_options(options):
    """Never reinterpret another engine or an API request as native Vina CLI."""
    for index, value in enumerate(options):
        name, separator, selected = value.partition("=")
        if not separator and name in {"--engine", "--vina-backend"}:
            selected = options[index + 1] if index + 1 < len(options) else ""
        if name == "--engine" and selected != "vina":
            raise ValueError("This native scientific preview supports Vina only; no engine substitution")
        if name == "--vina-backend" and selected != "cli":
            raise ValueError("This native scientific preview supports the pinned Vina CLI, not an API substitution")
        if name in {"--engine-command", "--engine-env"}:
            raise ValueError("Native scientific preview engine-path/environment overrides require separate acceptance")


def protocol_preflight(command, options):
    """Check locked engine authority before an outer runner creates any output."""
    protocol = None
    for index, value in enumerate(options):
        name, separator, selected = value.partition("=")
        if command == "screen" and name == "--mode":
            mode = selected if separator else (options[index + 1] if index + 1 < len(options) else "")
            if mode != "screen":
                raise ValueError("Native scientific screening does not provide a control/preparation fallback")
        if name == "--protocol":
            protocol = selected if separator else (options[index + 1] if index + 1 < len(options) else "")
    if command == "screen" and not protocol:
        raise ValueError("Native screening requires an explicit approved --protocol bundle; no interactive preparation fallback")
    if command == "screen" and options and options[0] in {"control", "exploratory"}:
        raise ValueError("Native scientific screening cannot be reinterpreted as another workflow")
    if protocol is not None:
        source = Path(protocol)
        if source.suffix.lower() == ".duprotocol":
            from .services.protocol_import import inspect_protocol_bundle
            record = inspect_protocol_bundle(source)
        else:
            from .services.screening import read_protocol_record
            record = read_protocol_record(source)
        if record.get("engine") != "vina":
            raise ValueError("This native scientific preview cannot run the protocol's engine; no Vina substitution or job was started")


def stage_command(app: Path, configuration: dict, command: str, options: list[str], inherited: dict):
    if command not in STAGES:
        raise ValueError("Unsupported native scientific command; no shell fallback")
    require_vina_options(options)
    protocol_preflight(command, options)
    python, environment, _receipt = scientific_environment(app, configuration, inherited)
    arguments = list(options)
    if command == "dock":
        arguments.extend(["--engine", "vina", "--engine-command", environment["DOCKING_UNIVERSAL_VINA"], "--vina-backend", "cli"])
    return [str(python), str(app / STAGES[command]), *arguments], environment
