#!/usr/bin/env bash
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-bootstrap.XXXXXX")
trap 'rm -rf "$work_dir"' EXIT HUP INT TERM
mock_bin="$work_dir/bin"
state_file="$work_dir/environments"
log_file="$work_dir/conda.log"
mkdir -p "$mock_bin"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

cat > "$mock_bin/conda" <<'EOF'
#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$BOOTSTRAP_TEST_LOG"

case "${1:-} ${2:-}" in
  "env list")
    printf '# conda environments:\n'
    if [ -f "$BOOTSTRAP_TEST_STATE" ]; then
      while IFS= read -r environment_name; do
        [ -n "$environment_name" ] || continue
        printf '%s /mock/envs/%s\n' "$environment_name" "$environment_name"
      done < "$BOOTSTRAP_TEST_STATE"
    fi
    ;;
  "env create")
    case "$*" in
      *environments/qvinaw.yml*) environment_name=docking-universal-qvinaw ;;
      *environments/vina.yml*) environment_name=docking-universal-vina ;;
      *environment.yml*) environment_name=docking-universal ;;
      *) exit 2 ;;
    esac
    printf '%s\n' "$environment_name" >> "$BOOTSTRAP_TEST_STATE"
    ;;
  "env update")
    ;;
  "run --no-capture-output")
    ;;
  *)
    printf 'Unexpected fake Conda invocation: %s\n' "$*" >&2
    exit 2
    ;;
esac
EOF
chmod +x "$mock_bin/conda"

bootstrap_output=$(env PATH="$mock_bin:$PATH" \
  BOOTSTRAP_TEST_STATE="$state_file" BOOTSTRAP_TEST_LOG="$log_file" \
  DOCKING_UNIVERSAL_CONDA=conda "$project_dir/install.sh") || fail "fresh bootstrap installation"

grep -q "env create -f $project_dir/environment.yml" "$log_file" || fail "main environment creation"
grep -q "env create -f $project_dir/environments/vina.yml" "$log_file" || fail "Vina environment creation"
grep -q "env create -f $project_dir/environments/qvinaw.yml" "$log_file" || fail "QuickVina-W environment creation"
grep -q "run --no-capture-output -n docking-universal make -C $project_dir install-conda" "$log_file" || fail "command installation"
grep -q "run --no-capture-output -n docking-universal docking-universal check-install --full" "$log_file" || fail "full installation check"
case "$bootstrap_output" in
  *"Docking Universal installation completed successfully."*"docking-universal run"*"docking-universal prepare-ligand --help"*"conda activate docking-universal"*) ;;
  *) fail "completion guidance" ;;
esac
[ -x "$mock_bin/docking-universal" ] || fail "user-facing launcher installation"

: > "$log_file"
env PATH="$mock_bin:$PATH" BOOTSTRAP_TEST_STATE="$state_file" \
  BOOTSTRAP_TEST_LOG="$log_file" DOCKING_UNIVERSAL_CONDA=conda \
  "$mock_bin/docking-universal" prepare-ligand --help >/dev/null || fail "all-command launcher"
grep -q 'run --no-capture-output -n docking-universal docking-universal prepare-ligand --help' "$log_file" || fail "all-command environment routing"

: > "$log_file"
background_out="$work_dir/background-validation"
background_output=$(env PATH="$mock_bin:$PATH" BOOTSTRAP_TEST_STATE="$state_file" \
  BOOTSTRAP_TEST_LOG="$log_file" DOCKING_UNIVERSAL_CONDA=conda \
  "$mock_bin/docking-universal" validate quick --out "$background_out" --background) \
  || fail "background validation launcher"
attempt=0
while ! grep -q "docking-universal validate quick --out $background_out" "$log_file" && [ "$attempt" -lt 20 ]; do
  sleep 0.05
  attempt=$((attempt + 1))
done
grep -q "run --no-capture-output -n docking-universal docking-universal validate quick --out $background_out" "$log_file" \
  || fail "background validation environment routing"
case "$background_output" in
  *"Validation started in the background."*"Level: quick"*"Output: $background_out"*) ;;
  *) fail "background validation guidance" ;;
esac
[ -s "$background_out/pid" ] || fail "background validation PID"
[ -f "$background_out/status.json" ] || fail "background validation status"
[ -f "$background_out/run.log" ] || fail "background validation log"

: > "$log_file"
env PATH="$mock_bin:$PATH" BOOTSTRAP_TEST_STATE="$state_file" \
  BOOTSTRAP_TEST_LOG="$log_file" DOCKING_UNIVERSAL_CONDA=conda \
  "$project_dir/install.sh" >/dev/null || fail "repeat bootstrap installation"

grep -q "env update -f $project_dir/environment.yml" "$log_file" || fail "main environment update"
grep -q "env update -f $project_dir/environments/vina.yml" "$log_file" || fail "Vina environment update"
grep -q "env update -f $project_dir/environments/qvinaw.yml" "$log_file" || fail "QuickVina-W environment update"
if grep -q -- '--prune' "$log_file"; then
  fail "automatic update pruned user-added packages"
fi
if grep -q 'env create' "$log_file"; then
  fail "existing environment was recreated"
fi

missing_conda_output=""
if missing_conda_output=$(env PATH="$mock_bin:/usr/bin:/bin" DOCKING_UNIVERSAL_CONDA=missing-conda \
  "$project_dir/install.sh" 2>&1); then
  fail "missing Conda was accepted"
fi
case "$missing_conda_output" in
  *"Conda was not found"*"https://github.com/conda-forge/miniforge"*"./install.sh"*) ;;
  *) fail "missing Conda installation guidance" ;;
esac

: > "$log_file"
env PATH="$mock_bin:$PATH" BOOTSTRAP_TEST_STATE="$state_file" \
  BOOTSTRAP_TEST_LOG="$log_file" DOCKING_UNIVERSAL_CONDA=conda \
  "$project_dir/start.sh" --help >/dev/null || fail "beginner launcher"
grep -q 'run --no-capture-output -n docking-universal docking-universal run --help' "$log_file" || fail "launcher environment routing"

printf 'PASS: Conda bootstrap installer checks\n'
