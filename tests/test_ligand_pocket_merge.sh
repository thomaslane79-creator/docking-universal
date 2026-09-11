#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-ligand-merge.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

cat > "$tmp/complex.pdb" <<'EOF'
HETATM    1  C1  LIG A 101       0.000   0.000   0.000  1.00 20.00           C
HETATM    2  O1  LIG A 101       2.000   0.000   0.000  1.00 20.00           O
EOF
cat > "$tmp/pockets.pqr" <<'EOF'
ATOM      1 APOL STP 1  0.000 0.000 0.000 0.0 1.500
ATOM      2 APOL STP 1  3.000 0.000 0.000 0.0 1.500
ATOM      3 APOL STP 1 12.000 0.000 0.000 0.0 9.000
ATOM      4 APOL STP 1  6.000 0.000 0.000 0.0 1.000
EOF

merge_ligand_overlapping_spheres "$tmp/complex.pdb" LIG "$tmp/pockets.pqr" 10.0 -0.5 "$tmp/merged.pdb" 2> "$tmp/merge.log"
[ "$(grep -c '^ATOM' "$tmp/merged.pdb")" -eq 2 ] || fail "ligand-overlap selection changed"
grep -q 'skipped 1 distant spheres' "$tmp/merge.log" || fail "centroid-distance filtering changed"
! grep -q '  12.000' "$tmp/merged.pdb" || fail "distant sphere was retained"
! grep -q '   6.000' "$tmp/merged.pdb" || fail "non-overlapping sphere was retained"

merge_ligand_overlapping_spheres "$tmp/complex.pdb" LIG "$tmp/pockets.pqr" OFF -0.5 "$tmp/unfiltered.pdb" 2> "$tmp/unfiltered.log"
[ "$(grep -c '^ATOM' "$tmp/unfiltered.pdb")" -eq 3 ] || fail "OFF centroid mode changed"
grep -q 'centroid filter OFF' "$tmp/unfiltered.log" || fail "OFF-mode audit message changed"

if merge_ligand_overlapping_spheres "$tmp/complex.pdb" BAD "$tmp/pockets.pqr" 10.0 -0.5 "$tmp/missing.pdb" 2> "$tmp/missing.log"; then
  fail "missing ligand unexpectedly succeeded"
fi
grep -q 'no ligand atoms were collected' "$tmp/missing.log" || fail "missing-ligand diagnosis changed"

printf 'PASS: ligand-local fpocket merge characterization checks\n'
