#!/usr/bin/env bash
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
install_root=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-install-test.XXXXXX")
trap 'rm -rf "$install_root"' EXIT HUP INT TERM

make -C "$project_dir" install PREFIX="$install_root/prefix" >/dev/null
installed_cli="$install_root/prefix/bin/docking-universal"
package_root="$install_root/prefix/libexec/docking-universal"

[ "$($installed_cli --version)" = "Docking Universal 0.4.0" ]
[ -x "$package_root/bin/docking-universal" ]
[ -x "$package_root/libexec/docking-universal-run.py" ]
[ "$(sed -n '1p' "$package_root/VERSION")" = "0.4.0" ]
[ -x "$package_root/tests/test_cli.sh" ]
[ -s "$package_root/examples/tutorials/01_bound_ligand/inputs/1HVR.pdb" ]

for command_name in run screen calibrate prepare validate; do
  "$installed_cli" "$command_name" --help >/dev/null
done

printf 'PASS: user-local installation layout\n'
