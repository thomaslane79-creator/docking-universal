"""Install the already validated Windows scientific stack into owned prefixes.

Only installation/import/render-runtime checks happen here, never a study,
structure lookup, preparation or docking. Unsupported GUI/GPU capabilities are
not enabled by this receipt. Existing environments are never updated.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

from .runtime_layout import executable_directories


def scientific_specification(source: str) -> str:
    lines = source.splitlines()
    expected = {"  - make", "  - fpocket=4.2.2"}
    if not expected.issubset(set(lines)):
        raise ValueError("Scientific environment changed; review native-only omissions before proceeding")
    return "\n".join(line for line in lines if line not in expected and not line.startswith("name:")) + "\n"


def split_pip_phase(specification: str) -> tuple[str, list[str]]:
    before, marker, after = specification.partition("  - pip:\n")
    if not marker:
        raise ValueError("Scientific pip specification changed; review required")
    requirements = []
    for line in after.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith("      - "):
            raise ValueError("Scientific pip specification changed; review required")
        requirements.append(line[len("      - "):])
    return before, requirements


def extract_p2rank(archive: Path, destination: Path):
    if destination.exists():
        raise FileExistsError("P2Rank installation requires a fresh directory")
    # Validate the entire member list before creating/extracting anything.
    with tarfile.open(archive, "r:gz") as package:
        planned = []
        for member in package.getmembers():
            name = member.name.replace("\\", "/")
            parts = name.split("/")
            if (member.issym() or member.islnk() or not (member.isdir() or member.isfile())
                    or name.startswith("/") or any(part == ".." or ":" in part for part in parts)):
                raise ValueError("Unsafe member in pinned P2Rank archive")
            relative = Path(*parts[1:])
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("P2Rank extraction escaped its fresh directory")
            planned.append((member, relative, target))
        destination.mkdir(parents=True)
        for member, relative, target in planned:
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif relative.parts:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.extractfile(member) as source, target.open("wb") as stream:
                    shutil.copyfileobj(source, stream)


def install_scientific_runtime(*, conda: Path, prefix: Path, app: Path,
                               source_assets: Path, work: Path, environment=None):
    """Fresh prefix + pinned packages/assets, without granting workflow support."""
    if prefix.exists() or work.exists():
        raise FileExistsError("Scientific setup requires fresh runtime and audit directories")
    work.mkdir(parents=True)
    environment = dict(os.environ if environment is None else environment)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", CONDA_REPORT_ERRORS="false")
    receipt = {"schema": "docking-universal-windows-scientific-install-v1", "status": "installing",
               "scientific_gui_enabled": False, "interactive_viewer_accepted": False,
               "gpu_accepted": False, "steps": [],
               "omissions": {"make": "Unix installer only", "fpocket=4.2.2": "No pinned Windows build; no detector substitution"}}

    def save():
        (work / "scientific-install.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    def run(name, command, *, env=None, capture=False):
        print("Windows dependency setup: " + name, flush=True)
        with (work / (name + ".log")).open("w", encoding="utf-8") as log:
            result = subprocess.run(list(map(str, command)), env=env or environment, shell=False,
                                    stdout=subprocess.PIPE if capture else log, stderr=log,
                                    encoding="utf-8", errors="replace", check=False, timeout=1500)
            if capture:
                log.write(result.stdout)
        if result.returncode:
            # These probes run before any structure/study exists. Retain only
            # their startup diagnostics, never later scientific process logs.
            if name in {"pinned_java_probe", "pinned_p2rank_probe"}:
                receipt["startup_diagnostics"] = {"probe": name, "returncode": result.returncode,
                    "text": (work / (name + ".log")).read_text(encoding="utf-8", errors="replace")[-5000:]}
                save()
            raise RuntimeError(f"Dependency setup failed: {name} (exit {result.returncode}); local logs retained")
        receipt["steps"].append(name); save()
        return result.stdout if capture else None

    try:
        text = (source_assets / "environment.yml").read_text(encoding="utf-8")
        specification, requirements = split_pip_phase(scientific_specification(text))
        receipt["environment_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        conda_file = work / "scientific-conda.yml"
        conda_file.write_text(specification, encoding="utf-8")
        pip_file = work / "scientific-pip.txt"
        pip_file.write_text("\n".join(requirements) + "\n", encoding="utf-8")
        run("conda_scientific_packages", [conda, "env", "create", "--yes", "--prefix", prefix, "--file", conda_file])
        from .windows_activation import repair_opencl_activation
        receipt["activation_repair"] = repair_opencl_activation(prefix)
        run("pinned_pip_packages", [conda, "run", "--no-capture-output", "--prefix", prefix,
            "python", "-m", "pip", "install", "-U", "-r", pip_file, "--exists-action=b"])
        runtime_env = dict(environment)
        runtime_env["PATH"] = os.pathsep.join([*(str(path) for path in executable_directories(prefix, windows=True)), environment.get("PATH", "")])
        python = prefix / "python.exe"
        probe = run("scientific_import_probe", [python, "-c",
            "import json,sys,importlib.metadata as m; import rdkit,openbabel,pymol,pdbfixer,openmm,gemmi,prody,cairo,meeko,reportlab,molscrub,pdb2pqr,plip; "
            "import mmtbx.programs.reduce2; print('DU_IMPORTS='+json.dumps({'python':sys.version,'packages':{k:m.version(k) for k in ['rdkit','meeko','pdb2pqr','reportlab']}}))"],
            env=runtime_env, capture=True)
        frames = [line.partition("=")[2] for line in probe.splitlines() if line.startswith("DU_IMPORTS=")]
        if len(frames) != 1:
            raise ValueError("Scientific import probe did not finish with its runtime identity")
        receipt["imports"] = json.loads(frames[0])
        pin = json.loads((source_assets / "dependencies/p2rank.json").read_text(encoding="utf-8"))
        archive = work / pin["filename"]
        with urllib.request.urlopen(pin["url"], timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != pin["sha256"]:
            raise ValueError("Pinned P2Rank archive checksum mismatch; archive was not extracted")
        archive.write_bytes(data)
        p2rank = prefix.parent.parent / "share" / ("p2rank-" + pin["version"])
        extract_p2rank(archive, p2rank)
        from .p2rank_runtime import JAVA_ARGUMENT_SOURCE, java_invocation, prefix_java
        java = prefix_java(prefix)
        run("pinned_java_probe", [java, "-version"], env=runtime_env)
        bridge = p2rank / "docking-universal-launcher"
        bridge.mkdir()
        source = bridge / "NativeArguments.java"
        source.write_text(JAVA_ARGUMENT_SOURCE, encoding="utf-8")
        run("java_argument_transport_compile", [java.with_name("javac.exe"), "-encoding", "UTF-8", "-d", bridge, source], env=runtime_env)
        receipt["java_argument_transport"] = {"format": "DUJ1 UTF-8 strings; original Main.main unchanged",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "class_sha256": hashlib.sha256((bridge / "NativeArguments.class").read_bytes()).hexdigest()}
        command, java_env = java_invocation(p2rank, java, ["-v"], environment=runtime_env)
        version = run("pinned_p2rank_probe", command, env=java_env, capture=True)
        if "P2Rank 2.5.1" not in version + (work / "pinned_p2rank_probe.log").read_text(encoding="utf-8"):
            raise ValueError("Installed primary P2Rank did not report its pinned version")
        nodes = [parent / "node.exe" for parent in executable_directories(prefix, windows=True)]
        node = next((path for path in nodes if path.is_file()), None)
        npm_files = []
        for path in (prefix / "conda-meta").glob("nodejs-*.json"):
            metadata = json.loads(path.read_text(encoding="utf-8"))
            npm_files.extend(prefix / name for name in metadata.get("files", []) if name.replace("\\", "/").endswith("/npm/bin/npm-cli.js"))
        npm = next((path for path in npm_files if path.is_file()), None)
        if node is None or npm is None:
            raise ValueError("Declared Node/npm is missing from the owned scientific prefix")
        renderer = app / "docking_universal/poseedit_renderer"
        run("pinned_local_renderer", [node, npm, "ci", "--prefix", renderer, "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"], env=runtime_env)
        from .browser_runtime import find_chromium
        browser = find_chromium(environment=runtime_env, system="Windows")
        if browser is None:
            # Revision is selected by the exact integrity-pinned Playwright
            # package. Download only a private browser; no system registration.
            runtime_env["PLAYWRIGHT_BROWSERS_PATH"] = str(app.parent / "share/playwright-browsers")
            run("private_chromium", [node, renderer / "node_modules/playwright/cli.js", "install", "chromium"], env=runtime_env)
            value = run("private_chromium_path", [node, "-e", "process.stdout.write(require(process.argv[1]).chromium.executablePath())",
                renderer / "node_modules/playwright"], env=runtime_env, capture=True).strip()
            browser = Path(value)
            if not browser.is_file() or not browser.resolve().is_relative_to((app.parent / "share/playwright-browsers").resolve()):
                raise ValueError("Private Chromium escaped its owned directory or is missing")
        receipt.update(status="dependencies_installed", python=str(python), p2rank=str(p2rank), java=str(java),
                       node=str(node), browser=str(browser), browser_sha256=hashlib.sha256(browser.read_bytes()).hexdigest(),
                       renderer_lock_sha256=hashlib.sha256((renderer / "package-lock.json").read_bytes()).hexdigest())
    except Exception as exc:
        receipt.update(status="failed", error=str(exc)); save()
        raise
    save()
    return receipt
