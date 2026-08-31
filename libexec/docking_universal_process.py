"""Shared subprocess execution for auditable workflow stages."""

import subprocess


def run_checked(command, cwd=None, env=None):
    """Print the exact command, normalize path objects, and fail on errors."""
    normalized = [str(value) for value in command]
    print("+ " + " ".join(normalized), flush=True)
    return subprocess.run(normalized, cwd=cwd, env=env, check=True)
