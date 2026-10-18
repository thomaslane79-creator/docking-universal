"""Shared subprocess execution for auditable workflow stages."""

import subprocess
from docking_universal.tool_commands import script_command


def run_checked(command, cwd=None, env=None):
    """Print the exact command, normalize path objects, and fail on errors."""
    normalized = [str(value) for value in command]
    normalized = script_command(normalized[0], *normalized[1:])
    print("+ " + " ".join(normalized), flush=True)
    return subprocess.run(normalized, cwd=cwd, env=env, check=True)
