#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-structural-audits.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

cat > "$tmp/disulfides.pdb" <<'EOF'
SSBOND   1 CYS A   10    CYS B   20
SSBOND   2 CYS A   10    CYS B   20
SSBOND   3 SER A   30    CYS A   40
EOF
[ "$(disulfide_template_assignments "$tmp/disulfides.pdb")" = 'A:10=CYX,B:20=CYX' ] || fail "SSBOND-to-CYX assignments changed"

cat > "$tmp/filtered.pdb" <<'EOF'
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N
ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 20.00           C
ATOM      3  N   GLY A   2       2.000   0.000   0.000  1.00 20.00           N
HETATM    4  C1  MOD B  10       3.000   0.000   0.000  1.00 20.00           C
HETATM    5  C2  MOD B  10       4.000   0.000   0.000  1.00 20.00           C
EOF
cat > "$tmp/final.pdbqt" <<'EOF'
ATOM      1  N   ALA A   1       0.000   0.000   0.000  0.00  0.00      N
ATOM      2  CA  ALA A   1       1.000   0.000   0.000  0.00  0.00      C
EOF
write_removed_component_manifest "$tmp/final.pdbqt" "$tmp/filtered.pdb" "$tmp/removed.tsv"
grep -q $'A\t2\t\tGLY\t1' "$tmp/removed.tsv" || fail "removed standard residue audit changed"
grep -q $'B\t10\t\tMOD\t2' "$tmp/removed.tsv" || fail "removed component atom count changed"
[ "$(wc -l < "$tmp/removed.tsv" | tr -d ' ')" -eq 3 ] || fail "removed manifest inventory changed"

cat > "$tmp/histidines.pdb" <<'EOF'
ATOM      1  ND1 HIS A  10       0.000   0.000   0.000  1.00 20.00           N
ATOM      2  NE2 HIS A  10       1.000   0.000   0.000  1.00 20.00           N
ATOM      3  ND1 HIS B  20       2.000   0.000   0.000  1.00 20.00           N
ATOM      4  HD1 HIS B  20       3.000   0.000   0.000  1.00 20.00           H
ATOM      5  NE2 HIS C  30       4.000   0.000   0.000  1.00 20.00           N
ATOM      6  HE2 HIS C  30       5.000   0.000   0.000  1.00 20.00           H
EOF
[ "$(histidines_without_explicit_ring_proton "$tmp/histidines.pdb")" = 'A:10' ] || fail "explicit histidine proton evidence was not respected"
printf "for residue_key='A:10' tied for fewest missing H: HIE HID\n" > "$tmp/his1.log"
printf "for residue_key='D:40' tied for fewest missing H: HIE HID\n" > "$tmp/his2.log"
[ "$(ambiguous_histidine_residue "$tmp/his1.log" "$tmp/his2.log")" = 'D:40' ] || fail "last Meeko histidine ambiguity changed"

printf 'PASS: receptor structural-audit helper checks\n'
