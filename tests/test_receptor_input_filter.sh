#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-input-filter.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

. "$root/libexec/docking-universal-prepare-support.sh"

python=${DOCKING_UNIVERSAL_PYTHON:-python3}
"$python" - "$tmp/input.pdb" <<'PY'
import sys

def record(kind, serial, atom, residue, chain, number, x, element):
    return f"{kind:<6}{serial:5d} {atom:^4} {residue:>3} {chain}{number:4d}    {x:8.3f}{0:8.3f}{0:8.3f}{1:6.2f}{20:6.2f}          {element:>2}\n"

path = sys.argv[1]
with open(path, "w") as out:
    out.write("MODRES 1ABC CSO A   2  CYS  S-HYDROXYCYSTEINE\n")
    out.write("LINK         CA  ALA A   1                 C1  ADX A 101\n")
    out.write(record("ATOM", 1, "CA", "ALA", "A", 1, 0, "C"))
    out.write(record("HETATM", 2, "CA", "CSO", "A", 2, 1, "C"))
    out.write(record("HETATM", 3, "C1", "ADX", "A", 101, 2, "C"))
    out.write(record("HETATM", 4, "C2", "ADX", "A", 101, 3, "C"))
    out.write(record("HETATM", 5, "C1", "LIG", "A", 201, 4, "C"))
    out.write(record("HETATM", 6, "O", "HOH", "A", 301, 5, "O"))
    out.write(record("HETATM", 7, "ZN", "ZN", "A", 401, 6, "ZN"))
    out.write(record("HETATM", 8, "MG", "MG", "A", 402, 7, "MG"))
    out.write(record("HETATM", 9, "NA", "NA", "A", 403, 8, "NA"))
PY

filter_receptor_input "$tmp/input.pdb" "$tmp/filtered.pdb"

[ "$(grep -c '^ATOM  ' "$tmp/filtered.pdb")" -eq 2 ] || fail "ATOM/MODRES normalization changed"
[ "$(grep -c '^HETATM' "$tmp/filtered.pdb")" -eq 4 ] || fail "linked-component/metal retention changed"
grep -q ' CSO A   2' "$tmp/filtered.pdb" || fail "MODRES polymer residue was not retained"
[ "$(grep ' CSO A   2' "$tmp/filtered.pdb" | cut -c1-6)" = 'ATOM  ' ] || fail "MODRES record was not normalized to ATOM"
[ "$(grep -c ' ADX A 101' "$tmp/filtered.pdb")" -eq 2 ] || fail "linked multi-atom component was not retained"
awk '$1 == "HETATM" && $4 == "ZN" && $6 == 401 {found=1} END {exit !found}' "$tmp/filtered.pdb" || fail "supported zinc was not retained"
awk '$1 == "HETATM" && $4 == "MG" && $6 == 402 {found=1} END {exit !found}' "$tmp/filtered.pdb" || fail "supported magnesium was not retained"
! grep -q ' LIG A 201' "$tmp/filtered.pdb" || fail "ordinary ligand was retained"
! grep -q ' HOH A 301' "$tmp/filtered.pdb" || fail "water was retained"
! grep -q ' NA  A 403' "$tmp/filtered.pdb" || fail "unsupported ion was retained"

[ "$(list_retained_linked_components "$tmp/input.pdb" "$tmp/filtered.pdb")" = 'ADX:A:101' ] || \
  fail "retained linked-component identity changed"

printf 'PASS: receptor input-filter characterization checks\n'
