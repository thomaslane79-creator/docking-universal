"""Audited path-quoting repair for one Conda-forge Windows activation build.

Only installer-owned prefixes are passed here. No OpenCL DLL, scientific code,
parameter or package version is changed. Unknown upstream scripts fail closed.
Upstream feedstock: conda-forge/khronos-opencl-icd-loader-feedstock,
80ef539ea6232963e476eb9e616dd4a3379603dc (Apache-2.0).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPAIRS = {
    "etc/conda/activate.d/khronos-opencl-icd-loader_activate.bat": (
        "167d2173f87838d9f2959456301d2f2958c0431a453dfc566f8c3f8c28192475",
        '@echo off\n\nset "OCL_ICD_FILENAMES_CONDA_BACKUP=%OCL_ICD_FILENAMES%"\n'
        'call "%CONDA_PREFIX%\\Library\\etc\\OpenCL\\vendors\\opencl-helper.bat"\n'
        'if errorlevel 1 exit /b 1\nset "OCL_ICD_FILENAMES_NEW="\n'
        'set /p OCL_ICD_FILENAMES_NEW=<"%CONDA_PREFIX%\\Library\\etc\\OpenCL\\vendors\\temp.txt"\n'
        'set "OCL_ICD_FILENAMES=%OCL_ICD_FILENAMES%%OCL_ICD_FILENAMES_NEW%"\n'
        'del "%CONDA_PREFIX%\\Library\\etc\\OpenCL\\vendors\\temp.txt"\n'
        'set "OCL_ICD_FILENAMES_NEW="\nexit /b 0\n'),
    "Library/etc/OpenCL/vendors/opencl-helper.bat": (
        "b7f1e6eb78989303cf6934d44710eb707563a53ded9208b60632fc4946e4eede",
        '@echo off\nsetlocal enabledelayedexpansion\n\nset "OCL_ICD_FILENAMES_NEW="\n'
        'for %%f in ("%CONDA_PREFIX%\\Library\\etc\\OpenCL\\vendors\\*.icd") do (\n'
        '  if exist "%%~f" (\n    set "dllname="\n    set /p dllname=<"%%~f"\n'
        '    if defined dllname set "OCL_ICD_FILENAMES_NEW=!OCL_ICD_FILENAMES_NEW!;!dllname!"\n  )\n)\n'
        'if NOT "%OCL_ICD_FILENAMES_NEW%" == "" (\n'
        '  echo %OCL_ICD_FILENAMES_NEW%>"%CONDA_PREFIX%\\Library\\etc\\OpenCL\\vendors\\temp.txt"\n'
        ') else (\n  type NUL > "%CONDA_PREFIX%\\Library\\etc\\OpenCL\\vendors\\temp.txt"\n)\nexit /b 0\n'),
}


def repair_opencl_activation(prefix: Path) -> dict:
    prepared = []
    for relative, (expected, replacement) in REPAIRS.items():
        path = prefix / relative
        original = path.read_bytes()
        if hashlib.sha256(original.replace(b"\r\n", b"\n")).hexdigest() != expected:
            raise ValueError(f"Unknown upstream OpenCL activation script; review required: {relative}")
        backup = path.with_suffix(path.suffix + ".docking-universal-original")
        if backup.exists():
            raise FileExistsError(f"Activation repair already has a retained backup: {backup}")
        content = replacement.replace("\n", "\r\n").encode("utf-8")
        prepared.append((relative, path, backup, original, content))
    # Validate both before modifying either. The caller owns this fresh prefix.
    record = {"schema": "docking-universal-windows-activation-repair-v1", "status": "repaired", "files": [],
              "package": "khronos-opencl-icd-loader=2024.10.24=hfd05255_2",
              "package_sha256": "245bd150a9f0b922dc34f173027631a20f18b009604d827a796d792a79bac178",
              "reason": "Quote spaced paths; synchronously call the same ICD-list helper; no DLL or scientific-method change"}
    for relative, path, backup, original, content in prepared:
        backup.write_bytes(original)
        path.write_bytes(content)
        record["files"].append({"relative_path": relative, "before_sha256": hashlib.sha256(original).hexdigest(),
                                "after_sha256": hashlib.sha256(content).hexdigest()})
    target = prefix / "share/docking-universal/windows-activation-repair.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record
