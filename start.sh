#!/usr/bin/env bash
set -eu

conda_command=${DOCKING_UNIVERSAL_CONDA:-conda}

if ! command -v "$conda_command" >/dev/null 2>&1; then
  printf 'Error: Conda was not found. Run bash install.sh for setup guidance.\n' >&2
  exit 1
fi

if ! "$conda_command" env list | awk '
  $1 == "docking-universal" { found = 1 }
  END { exit(found ? 0 : 1) }
'; then
  printf 'Error: the docking-universal environment is not installed.\n' >&2
  printf 'Run bash install.sh first.\n' >&2
  exit 1
fi

exec "$conda_command" run --no-capture-output -n docking-universal \
  docking-universal run "$@"
