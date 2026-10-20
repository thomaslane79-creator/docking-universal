"""Bounded native desktop workflow, using the accepted owned scientific stack."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from .windows_scientific_runtime import scientific_environment

WORKFLOW = "strict-p2rank-vina-preview-v1"
CAPABILITIES = {"scientific_stages_supported": True, "native_scientific_preview": True,
    "supported_engines": ["vina"], "supported_site_modes": ["pockets"],
    "supported_pocket_engines": ["p2rank"], "known_ligand_control_supported": False,
    "preparation_interventions_supported": False, "interactive_viewer_accepted": False}


def preparation_guard(payload):
    if payload.get("site_mode", "pockets") != "pockets" or payload.get("predict_pockets_with_ligand"):
        raise ValueError("Native Windows ligand-guided/control preparation needs separate acceptance; no job was created")
    if payload.get("preparation_backend", "auto") not in {"auto", "meeko"}:
        raise ValueError("Native Windows preparation supports strict Meeko only; no backend substitution")
    if payload.get("pocket_engine", "auto") not in {"auto", "p2rank"}:
        raise ValueError("Native Windows preparation supports P2Rank only; no detector substitution")


def workflow_guard(command, controller, *, supported_engines=('vina',)):
    operation, payload = command.operation, command.payload
    if operation == "start_control_validation":
        raise ValueError("Known-ligand control is not accepted in the native Windows preview; no job was created")
    if operation == "start_receptor_preparation":
        preparation_guard(payload)
    if operation == "start_protocol_finalization" and payload.get("engine", "vina") not in supported_engines:
        raise ValueError("Native Windows finalization cannot use the selected engine; no engine substitution")
    if operation in {"import_protocol_bundle", "start_screening"}:
        from .services.protocol_import import inspect_protocol_bundle
        if operation == "import_protocol_bundle":
            bundle = payload.get("protocol_bundle", "")
        else:
            state = controller.get_study(command.study_id)
            bundle = next((item.path for item in state.artifacts if item.kind == "protocol_bundle"), "")
        if bundle and inspect_protocol_bundle(bundle)["engine"] not in supported_engines:
            raise ValueError("This native Windows preview cannot use the protocol's engine; no job/state change was made")
    if operation == "resolve_decision":
        state = controller.get_study(command.study_id)
        decision = next((item for item in state.pending_decisions if item.id == payload.get("decision_id")), None)
        if decision and decision.kind != "select_pockets":
            raise ValueError("This preparation intervention needs separate native acceptance; its pending decision was preserved")


def installed_capabilities(app, environment):
    configuration = json.loads((Path(app) / 'native-preview.json').read_text(encoding='utf-8'))
    from .windows_qvinaw import supported_engines, record
    capabilities = dict(CAPABILITIES)
    capabilities['supported_engines'] = list(supported_engines(configuration, environment))
    if 'qvinaw' in capabilities['supported_engines']:
        record(app, configuration)
    return capabilities


def installed_host(app, *, executing_python=None, inherited=None):
    """None for bootstrap-only; fail closed on a damaged/mismatched full host."""
    configuration_path = app / "native-preview.json"
    if not configuration_path.is_file():
        return None
    configuration = json.loads(configuration_path.read_text(encoding="utf-8"))
    if configuration.get("scientific_desktop_workflow") != WORKFLOW:
        return None
    python, environment, receipt = scientific_environment(app, configuration, os.environ if inherited is None else inherited)
    if Path(executing_python or sys.executable).resolve() != python.resolve():
        raise ValueError("The native scientific desktop must use its exact installation-owned scientific Python")
    script = app / "docking-universal-prepare-native.py"
    if not script.is_file():
        raise FileNotFoundError("Native desktop preparation service is missing")
    return script, environment, receipt


def preparation_options(source, working, environment):
    from .services.preparation import ReceptorPreparationOptions
    original = environment.get("DOCKING_UNIVERSAL_SOURCE_MMCIF") or source
    values = dict(input_pdb=Path(original), working_directory=Path(working),
        site_mode=environment.get("DOCKING_UNIVERSAL_SITE_MODE", "pockets"),
        preparation_backend=environment.get("DOCKING_UNIVERSAL_PREP_BACKEND", "auto"),
        pocket_engine=environment.get("DOCKING_UNIVERSAL_POCKET_ENGINE", "auto"))
    preparation_guard(values)
    for field, variable, default in (("feedback_level", "FEEDBACK_LEVEL", "guided"),
        ("center_mode", "DOCKING_UNIVERSAL_CENTER_MODE", "deepest"),
        ("pdbfixer", "DOCKING_UNIVERSAL_PDBFIXER", "auto"),
        ("protonation", "DOCKING_UNIVERSAL_PROTONATION", "auto"),
        ("reduce2", "DOCKING_UNIVERSAL_REDUCE2", "auto"),
        ("meeko_templates", "MEEKO_SET_TEMPLATE", "")):
        values[field] = environment.get(variable, default)
    for field, variable, default in (("cavity_mode", "DOCKING_UNIVERSAL_CAVITY_MODE", 1),
        ("max_pockets", "DOCKING_UNIVERSAL_MAX_POCKETS", 3),
        ("centroid_mode", "DOCKING_UNIVERSAL_CENTROID_MODE", 1)):
        values[field] = int(environment.get(variable, default))
    values["receptor_ph"] = float(environment.get("DOCKING_UNIVERSAL_RECEPTOR_PH", 7.4))
    for field, variable in (("geostd_library", "DOCKING_UNIVERSAL_GEOSTD"), ("meeko_template_file", "MEEKO_ADD_TEMPLATES")):
        if environment.get(variable):
            values[field] = Path(environment[variable])
    return ReceptorPreparationOptions(**values)
