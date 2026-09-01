#!/usr/bin/env bash
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

grep -q 'conda env create -f environments/vina.yml' "$project_dir/.github/workflows/test.yml" || {
  printf 'FAIL: CI must create the real Vina engine environment\n' >&2
  exit 1
}
grep -q 'make test-integration' "$project_dir/.github/workflows/test.yml" || {
  printf 'FAIL: CI must run real-tool integration validation\n' >&2
  exit 1
}

grep -q '^[[:space:]]*- gemmi' "$project_dir/environment.yml" || {
  printf 'FAIL: environment.yml must declare Meeko receptor dependency gemmi\n' >&2
  exit 1
}
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-install.XXXXXX")
trap 'rm -rf "$work_dir"' EXIT HUP INT TERM
prefix="$work_dir/prefix"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

make -C "$project_dir" install PREFIX="$prefix" >/dev/null
cli="$prefix/bin/docking-universal"
libexec="$prefix/libexec/docking-universal"

[ -x "$cli" ] || fail "installed public command"
[ -x "$libexec/docking-universal-prepare" ] || fail "installed preparation helper"
[ -r "$libexec/docking-universal-prepare-support.sh" ] || fail "installed preparation support library"
for module in interaction runtime receptor ligands pockets artifacts; do
  [ -r "$libexec/docking-universal-prepare.d/$module.sh" ] || fail "installed preparation module: $module"
done
[ -x "$libexec/docking-universal-validate" ] || fail "installed validation helper"
[ -f "$libexec/docking_universal_bundle.py" ] || fail "installed bundle helper"
[ -f "$libexec/docking_universal_pocket_review.py" ] || fail "installed pocket-review helper"
[ -f "$libexec/docking_universal_region.py" ] || fail "installed protocol-region helper"
[ -f "$libexec/VERSION" ] || fail "installed version file"
[ -f "$libexec/validation-assets/test_inputs/two_compounds.sdf" ] || fail "installed test input"
[ -f "$libexec/validation-assets/tutorials/01_bound_ligand/inputs/1HVR.pdb" ] || fail "installed bound-ligand fixture"
[ -f "$libexec/validation-assets/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb" ] || fail "installed cavity fixture"
[ -x "$project_dir/install.sh" ] || fail "user-facing installer"
[ -x "$project_dir/bin/docking-universal-launcher" ] || fail "host-side Conda launcher"

installed_dir="$work_dir/outside-source"
mkdir -p "$installed_dir"
(
  cd "$installed_dir"
  unset DOCKING_UNIVERSAL_CLI DOCKING_UNIVERSAL_LIBEXEC
  PATH="$prefix/bin:$PATH"
expected_version="Docking Universal $(cat "$project_dir/VERSION")"
[ "$(docking-universal --version)" = "$expected_version" ] || fail "installed version"
  docking-universal --help >/dev/null || fail "installed general help"
  docking-universal run --help >/dev/null || fail "installed run help"
  docking-universal create-protocol --help >/dev/null || fail "installed create-protocol help"
  docking-universal prepare --help >/dev/null || fail "installed prepare help"
  docking-universal validate --help >/dev/null || fail "installed validate help"
  docking-universal validate smoke --out "$installed_dir/smoke" >/dev/null || fail "installed smoke validation"
  if docking-universal validate quick --out "$installed_dir/quick" >"$installed_dir/quick.stdout" 2>"$installed_dir/quick.stderr"; then
    fail "installed quick validation claimed to run the unavailable source test suite"
  fi
  grep -q "requires a source checkout" "$installed_dir/quick.stderr" || fail "installed quick validation guidance"
  grep -q "validate smoke" "$installed_dir/quick.stderr" || fail "installed smoke replacement guidance"
)

bash -n "$project_dir/install.sh" || fail "installer syntax"

printf 'PASS: installed-copy checks\n'
