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
            with (out / "install.log").open("w", encoding="utf-8") as stream:
                subprocess.run(command, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=1500)
            python = prefix / "python.exe"
            probe = subprocess.run([str(python), "-c",
                "import json,sys,importlib.metadata as m; import rdkit,openbabel,pymol,pdbfixer,openmm,gemmi,prody,cairo,meeko,reportlab,molscrub,pdb2pqr,plip; "
                "import mmtbx.command_line.reduce2; "
                "print(json.dumps({'python':sys.version,'packages':{k:m.version(k) for k in ['rdkit','meeko','pdb2pqr','reportlab']}}))"],
                env=environment, capture_output=True, text=True, encoding="utf-8", timeout=90)
            (out / "probe.stdout.json").write_text(probe.stdout, encoding="utf-8")
            (out / "probe.stderr.log").write_text(probe.stderr, encoding="utf-8")
            probe.check_returncode()
            state.update(status="dependencies_installed", imports=json.loads(probe.stdout))
            state["conda_packages"] = [json.loads(path.read_text(encoding="utf-8"))
                                       for path in sorted((prefix / "conda-meta").glob("*.json"))]
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
