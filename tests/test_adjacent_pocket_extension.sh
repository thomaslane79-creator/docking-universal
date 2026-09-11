#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-adjacent-pocket.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

mkdir -p "$tmp/frozen"
printf 'ATOM      1 APOL STP C   1       0.000   0.000   0.000  1.00  0.00           C\n' > "$tmp/frozen/pocket1_atm.pdb"
printf 'ATOM      2 APOL STP C   2       7.900   0.000   0.000  1.00  0.00           C\n' > "$tmp/frozen/pocket2_atm.pdb"
printf 'ATOM      3 APOL STP C   3       8.000   0.000   0.000  1.00  0.00           C\n' > "$tmp/frozen/pocket3_atm.pdb"
printf 'ATOM      4 APOL STP C   4      20.000   0.000   0.000  1.00  0.00           C\n' > "$tmp/frozen/pocket4_atm.pdb"

build_adjacent_pocket_extension "$tmp/frozen/pocket1_atm.pdb" "$tmp/frozen" "$tmp/adjacent.pdb" 8.0
[ "$(grep -c '^ATOM' "$tmp/adjacent.pdb")" -eq 1 ] || fail "adjacent-pocket membership changed"
grep -q '   7.900' "$tmp/adjacent.pdb" || fail "touching pocket was not retained"
! grep -q '   8.000' "$tmp/adjacent.pdb" || fail "strict touching-distance boundary changed"
! grep -q '  20.000' "$tmp/adjacent.pdb" || fail "distant pocket was retained"
! awk '$2 == 1 {found=1} END {exit !found}' "$tmp/adjacent.pdb" || fail "core pocket was copied into its own extension"

printf 'PASS: adjacent-pocket extension characterization checks\n'
