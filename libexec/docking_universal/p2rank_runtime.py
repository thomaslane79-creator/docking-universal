"""Shell-free launch of the pinned P2Rank Java application.

Matches the upstream prank launcher: 2048 MB heap, identical jar/classpath and
main class, with INSTALL_DIR retained for models/configuration. In particular,
Windows paths and user-selected coordinates are never passed through prank.bat.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Mapping, Sequence


def java_invocation(installation: Path, java: Path, arguments: Sequence[str], *,
                    environment: Mapping[str, str] | None = None) -> tuple[tuple[str, ...], dict[str, str]]:
    installation, java = installation.resolve(), java.resolve()
    if not java.is_file():
        raise FileNotFoundError(f"Pinned Java runtime is unavailable: {java}")
    jar, libraries = installation / "bin/p2rank.jar", installation / "bin/lib"
    if not jar.is_file() or not libraries.is_dir():
        raise FileNotFoundError(f"P2Rank installation is incomplete: {installation}")
    values = dict(os.environ if environment is None else environment)
    values["INSTALL_DIR"] = str(installation)
    # Preserve the Windows prank.bat defaults, not arbitrary shell expansion.
    # The version/model remains the installed, checksum-verified P2Rank asset.
    command = (str(java), "-Xmx2048m", "-cp", str(jar) + os.pathsep + str(libraries / "*"),
               "cz.siret.prank.program.Main", *(str(value) for value in arguments))
    return command, values


def run_p2rank(installation: Path, java: Path, arguments: Sequence[str], *,
               environment: Mapping[str, str] | None = None, **options):
    command, values = java_invocation(installation, java, arguments, environment=environment)
    return subprocess.run(command, env=values, shell=False, **options)
