"""Render a metadata-only report preview in a copy; never rerun analysis."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))


def snapshot(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.study.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    before = snapshot(source)
    copied = args.output / "retained-copy"
    shutil.copytree(source, copied)
    spec = importlib.util.spec_from_file_location("identity_preview_report", ROOT / "libexec/docking-universal-pdf-report.py")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    pdf = args.output / "2R8N-protein-identity-preview.pdf"
    original_run = subprocess.run
    skipped = []

    def retained_only(command, *a, **kw):
        if any(Path(str(item)).name == "docking-universal-report-figures.py" for item in command):
            skipped.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")
        return original_run(command, *a, **kw)

    with patch.object(sys, "argv", [str(report.__file__), str(copied), "--out", str(pdf)]), \
            patch.object(report.subprocess, "run", side_effect=retained_only):
        report.main()
    check = {"original_study_files_unchanged": before == snapshot(source),
             "retained_figures_used_no_analysis_rerun": len(skipped) == 1,
             "pdf_created": pdf.is_file(), "pdf": str(pdf.resolve())}
    (args.output / "verification.json").write_text(json.dumps(check, indent=2))
    print(json.dumps(check, indent=2))
    if not all(check[key] for key in ("original_study_files_unchanged", "retained_figures_used_no_analysis_rerun", "pdf_created")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
