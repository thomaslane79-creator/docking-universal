#!/usr/bin/env bash
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
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
[ -x "$libexec/docking-universal-validate" ] || fail "installed validation helper"
[ -f "$libexec/docking_universal_bundle.py" ] || fail "installed bundle helper"
[ -f "$libexec/VERSION" ] || fail "installed version file"
[ -f "$libexec/validation-assets/test_inputs/two_compounds.sdf" ] || fail "installed test input"
[ -f "$libexec/validation-assets/tutorials/01_bound_ligand/inputs/1HVR.pdb" ] || fail "installed bound-ligand fixture"
[ -f "$libexec/validation-assets/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb" ] || fail "installed cavity fixture"

installed_dir="$work_dir/outside-source"
mkdir -p "$installed_dir"
(
  cd "$installed_dir"
  unset DOCKING_UNIVERSAL_CLI DOCKING_UNIVERSAL_LIBEXEC
  PATH="$prefix/bin:$PATH"
  [ "$(docking-universal --version)" = "Docking Universal 0.6.0" ] || fail "installed version"
  docking-universal --help >/dev/null || fail "installed general help"
  docking-universal run --help >/dev/null || fail "installed run help"
  docking-universal prepare --help >/dev/null || fail "installed prepare help"
  docking-universal validate --help >/dev/null || fail "installed validate help"
  docking-universal validate quick --out "$installed_dir/quick" >/dev/null || fail "installed quick validation"
)

printf 'PASS: installed-copy checks\n'
