#!/usr/bin/env bash
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
conda_command=${DOCKING_UNIVERSAL_CONDA:-conda}

usage() {
  cat <<'EOF'
Install Docking Universal and its two Conda environments.

Usage:
  ./install.sh

The installer creates missing environments, updates existing environments,
installs the public command into the main environment, and verifies the full
pipeline. It is safe to run again after updating the repository.
EOF
}

case "${1:-}" in
  "") ;;
  -h|--help) usage; exit 0 ;;
  *) printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
esac

if ! command -v "$conda_command" >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Error: Conda was not found.

Recommended: install Miniforge for your operating system from:
  https://github.com/conda-forge/miniforge

After installation, open a new terminal (or initialize Conda as instructed by
the installer), return to this repository, and run:
  ./install.sh
EOF
  exit 1
fi

if [ ! -f "$project_dir/environment.yml" ] || [ ! -f "$project_dir/environments/vina.yml" ]; then
  printf 'Error: installation environment files were not found beside install.sh.\n' >&2
  exit 1
fi

conda_path=$(command -v "$conda_command")
case "$conda_path" in
  */*) ;;
  *)
    if [ -n "${CONDA_EXE:-}" ] && [ -x "$CONDA_EXE" ]; then
      conda_path=$CONDA_EXE
    else
      printf 'Error: the Conda executable path could not be determined.\n' >&2
      exit 1
    fi
    ;;
esac
launcher_path=$(dirname -- "$conda_path")/docking-universal

environment_exists() {
  "$conda_command" env list | awk -v requested_name="$1" '
    $1 == requested_name { found = 1 }
    END { exit(found ? 0 : 1) }
  '
}

install_environment() {
  environment_name=$1
  environment_file=$2

  if environment_exists "$environment_name"; then
    printf '\nUpdating Conda environment: %s\n' "$environment_name"
    "$conda_command" env update -f "$environment_file"
  else
    printf '\nCreating Conda environment: %s\n' "$environment_name"
    "$conda_command" env create -f "$environment_file"
  fi
}

printf 'Docking Universal setup\n'
printf 'Repository: %s\n' "$project_dir"

install_environment docking-universal "$project_dir/environment.yml"
install_environment docking-universal-vina "$project_dir/environments/vina.yml"

printf '\nInstalling the Docking Universal command into the main environment\n'
"$conda_command" run --no-capture-output -n docking-universal \
  make -C "$project_dir" install-conda

printf '\nVerifying the complete pipeline installation\n'
"$conda_command" run --no-capture-output -n docking-universal \
  docking-universal check-install --full

printf '\nInstalling the user-facing launcher: %s\n' "$launcher_path"
cp "$project_dir/bin/docking-universal-launcher" "$launcher_path"
chmod +x "$launcher_path"

cat <<'EOF'

Docking Universal installation completed successfully.

Start the guided pipeline with:
  docking-universal run

Every command works the same way, for example:
  docking-universal prepare-ligand --help
  docking-universal check-install --full

If you are comfortable activating Conda environments, that remains supported:
  conda activate docking-universal
  docking-universal run

The main environment remains active during normal use. Docking Universal runs
Vina from docking-universal-vina automatically when a docking stage starts.
EOF
