"""Native Windows scientific dependency gate, before enabling any GUI stages.

The candidate retains every scientific version in environment.yml. Only make
(Unix installer tooling) and optional fpocket (not published for Windows) are
omitted explicitly. No replacement detector, chemistry, or docking is selected.
Dependency metadata/logs only are retained; no structures are read or uploaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--conda", required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != "Windows":
        parser.error("This gate must run on native Windows")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    state = {"status": "running", "platform": platform.platform(),
             "explicit_omissions": {"make": "Unix installation tool; native installer does not use Make",
                                    "fpocket=4.2.2": "Optional fallback has no pinned win-64 build; no detector substitution"},
             "scientific_stages_enabled": False}
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    try:
        specification = scientific_specification((ROOT / "environment.yml").read_text(encoding="utf-8"))
        state["source_environment_sha256"] = hashlib.sha256((ROOT / "environment.yml").read_bytes()).hexdigest()
        spec = out / "scientific-candidate.yml"
        spec.write_text(specification, encoding="utf-8")
        # Conda permits spaced ancestor paths, not a space in the environment
        # leaf name. The public bootstrap likewise uses fixed host/gui leaves.
        prefix = out / "Native scientific test" / "scientific"
        command = [str(args.conda), "env", "create", "--yes", "--prefix", str(prefix), "--file", str(spec)]
        plan = subprocess.run([*command, "--dry-run", "--json"], capture_output=True, text=True,
                              encoding="utf-8", env=environment, timeout=900)
        (out / "solve.stdout.json").write_text(plan.stdout, encoding="utf-8")
        (out / "solve.stderr.log").write_text(plan.stderr, encoding="utf-8")
        try:
            solved = json.loads(plan.stdout)
        except ValueError:
            solved = {}
        if plan.returncode != 0:
            state.update(status="dependency_solve_failed", error=solved.get("message") or solved.get("error") or plan.stderr[-5000:],
                         solver_record=solved)
        else:
            state["solve_passed"] = True
            conda_specification, requirements = split_pip_phase(specification)
            conda_spec = out / "scientific-conda.yml"
            conda_spec.write_text(conda_specification, encoding="utf-8")
            pip_spec = out / "scientific-pip.txt"
            pip_spec.write_text("\n".join(requirements) + "\n", encoding="utf-8")
            with (out / "install.log").open("w", encoding="utf-8") as stream:
                print("Native pins solved; installing Conda packages before the audited activation repair", flush=True)
                conda_command = [*command[:-1], str(conda_spec)]
                subprocess.run(conda_command, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=1500)
                sys.path.insert(0, str(ROOT / "libexec"))
                from docking_universal.windows_activation import repair_opencl_activation
                state["activation_repair"] = repair_opencl_activation(prefix)
                print("Installing the unchanged pip pins in the repaired native environment", flush=True)
                subprocess.run([str(args.conda), "run", "--no-capture-output", "--prefix", str(prefix),
                                "python", "-m", "pip", "install", "-U", "-r", str(pip_spec), "--exists-action=b"],
                               env=environment, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=900)
            python = prefix / "python.exe"
            probe = subprocess.run([str(args.conda), "run", "--no-capture-output", "--prefix", str(prefix), str(python), "-c",
                "import json,sys,importlib.metadata as m; import rdkit,openbabel,pymol,pdbfixer,openmm,gemmi,prody,cairo,meeko,reportlab,molscrub,pdb2pqr,plip; "
                "import mmtbx.command_line.reduce2; "
                "print(json.dumps({'python':sys.version,'packages':{k:m.version(k) for k in ['rdkit','meeko','pdb2pqr','reportlab']}}))"],
                env=environment, capture_output=True, text=True, encoding="utf-8", timeout=90)
            (out / "probe.stdout.json").write_text(probe.stdout, encoding="utf-8")
            (out / "probe.stderr.log").write_text(probe.stderr, encoding="utf-8")
            probe.check_returncode()
            state.update(status="dependencies_installed", imports=json.loads(probe.stdout))
            state["conda_packages"] = []
            for path in sorted((prefix / "conda-meta").glob("*.json")):
                package = json.loads(path.read_text(encoding="utf-8"))
                state["conda_packages"].append({key: package.get(key)
                    for key in ("name", "version", "build", "channel", "subdir", "sha256")})
    except Exception as exc:
        state.update(status="failed", error=str(exc))
        for name in ("install.log", "probe.stderr.log"):
            path = out / name
            if path.is_file():
                state[name] = path.read_text(encoding="utf-8", errors="replace")[-5000:]
    (out / "summary.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: state.get(key) for key in ("status", "error", "solve_passed")}))
    return 0 if state["status"] == "dependencies_installed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
