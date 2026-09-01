#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-pymol-scene.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

mkdir -p "$tmp/cavity" "$tmp/receptor" "$tmp/ligands"
for file in receptor/target.pdb cavity/center.pdb cavity/box.pdb cavity/core.pdb cavity/adjacent.pdb cavity/merged.pdb ligands/LIG.pdb ligands/REF.pdb; do
  printf 'ATOM\n' > "$tmp/$file"
done

write_pymol_review_scene "$tmp/pocket.pml" now input.pdb "$tmp/cavity" "$tmp/receptor/target.pdb" \
  target 2 "$tmp/cavity/center.pdb" "$tmp/cavity/box.pdb" 0 "$tmp/cavity/core.pdb" \
  "$tmp/cavity/adjacent.pdb" 1 1 "$tmp/ligands" '' 0 1 0.75 "$tmp/cavity/merged.pdb" REF
grep -q 'load .*core.pdb, cavity_core2' "$tmp/pocket.pml" || fail "core pocket reference changed"
grep -q 'show surface, cavity_core2' "$tmp/pocket.pml" || fail "surface representation changed"
grep -q 'load .*adjacent.pdb, cavity_ext2' "$tmp/pocket.pml" || fail "enabled adjacent extension missing"
grep -q 'label target_center2, "Pocket 2 | fpocket 0.75"' "$tmp/pocket.pml" || fail "pocket identity label changed"
grep -q 'load .*box.pdb, target_box2' "$tmp/pocket.pml" || fail "docking box reference changed"
grep -q 'disable target_REF_reference' "$tmp/pocket.pml" || fail "reference ligand is no longer disabled by default"

write_pymol_review_scene "$tmp/ligand.pml" now input.pdb "$tmp/cavity" "$tmp/receptor/target.pdb" \
  target 1 "$tmp/cavity/center.pdb" "$tmp/cavity/box.pdb" 1 "$tmp/cavity/core.pdb" '' \
  0 0 "$tmp/ligands" LIG 1 0 merged "$tmp/cavity/merged.pdb"
grep -q 'load .*merged.pdb, cavity_pocket1' "$tmp/ligand.pml" || fail "ligand-local cavity reference changed"
grep -q 'show spheres, cavity_pocket1' "$tmp/ligand.pml" || fail "sphere representation changed"
grep -q 'load .*LIG.pdb, cavity_ligand1' "$tmp/ligand.pml" || fail "enabled ligand volume missing"
! grep -q 'cavity_ext1' "$tmp/ligand.pml" || fail "adjacent extension leaked into ligand mode"

printf 'PASS: PyMOL review-scene contract checks\n'
