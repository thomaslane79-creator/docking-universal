#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-ligand-helpers.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

python=${DOCKING_UNIVERSAL_PYTHON:-python3}
"$python" - "$tmp/complex.pdb" <<'PY'
import sys
def atom(kind,n,name,res,chain,seq,x,y,z,el):
    return f"{kind:<6}{n:5d} {name:^4} {res:>3} {chain}{seq:4d}    {x:8.3f}{y:8.3f}{z:8.3f}{1:6.2f}{20:6.2f}          {el:>2}\n"
path=sys.argv[1]
with open(path,'w') as f:
    f.write('MODRES 1ABC CSO A   2   CYS  S-HYDROXYCYSTEINE\n')
    f.write(atom('ATOM',1,'CA','ALA','A',1,0,0,0,'C'))
    f.write(atom('ATOM',2,'CA','GLY','B',1,20,0,0,'C'))
    f.write(atom('ATOM',3,'CB','GLY','B',1,22,0,0,'C'))
    serial=4
    for res,count,offset in [('LIG',10,0),('SM2',11,10),('EDO',12,30),('CSO',12,40)]:
        for i in range(count):
            f.write(atom('HETATM',serial,f'C{i%9}',res,'A',100+offset,offset+i,0,0,'C'));serial+=1
    f.write(atom('HETATM',serial,'ZN','ZN','A',400,0,0,0,'ZN'))
PY

[ "$(detect_bound_ligand_resnames "$tmp/complex.pdb" 10)" = $'LIG\nSM2' ] || fail "ligand candidate exclusions changed"
write_detected_ligand_files "$tmp/complex.pdb" "$tmp/ligands" "$tmp/ligands.tsv" LIG SM2
[ "$(awk -F '\t' 'NR>1{print $1":"$2}' "$tmp/ligands.tsv")" = $'LIG:10\nSM2:11' ] || fail "ligand manifest changed"
[ -s "$tmp/ligands/LIG.pdb" ] && [ -s "$tmp/ligands/SM2.pdb" ] || fail "ligand reference PDB missing"
[ "$(ligand_coordinate_centroid "$tmp/complex.pdb" LIG)" = '4.500000 0.000000 0.000000' ] || fail "ligand centroid changed"
[ "$(protein_ranking_centroid "$tmp/complex.pdb" 1)" = '14.000000 0.000000 0.000000' ] || fail "whole-protein centroid changed"
[ "$(protein_ranking_centroid "$tmp/complex.pdb" 2)" = '21.000000 0.000000 0.000000' ] || fail "largest-chain centroid changed"

# Characterize the orchestration contract separately from the full receptor
# route: configured ligand mode publishes its selected site, while pocket mode
# retains the same deposited ligands only as review references.
INPUT_PDB="$tmp/complex.pdb"
ROOT="$tmp/ligand-strategy"
SITE_MODE=ligand
REQUESTED_LIGAND=LIG
resolve_site_ligand_strategy
[ "$LIG_PRESENT" -eq 1 ] && [ "$LIG" = LIG ] || fail "configured ligand strategy changed"
[ "$LIGX $LIGY $LIGZ" = '4.500000 0.000000 0.000000' ] || fail "strategy ligand center changed"
[ "$(awk 'END{print NR}' "$LIGAND_MANIFEST")" -eq 3 ] || fail "strategy did not retain every ligand reference"

ROOT="$tmp/pocket-strategy"
SITE_MODE=pockets
REQUESTED_LIGAND=""
resolve_site_ligand_strategy
[ "$LIG_PRESENT" -eq 0 ] && [ -z "$LIG" ] || fail "pocket strategy silently selected a ligand"
[ "$(awk 'END{print NR}' "$LIGAND_MANIFEST")" -eq 3 ] || fail "pocket strategy lost deposited ligand references"

cat > "$tmp/local-source.pdb" <<'EOF'
HETATM    1  C1  LIG A 100       0.000   0.000   0.000  1.00 20.00           C
EOF
cat > "$tmp/local-receptor.pdb" <<'EOF'
ATOM      1  CA  ALA A   1       5.000   0.000   0.000  1.00 20.00           C
ATOM      2  CA  GLY A   2      12.001   0.000   0.000  1.00 20.00           C
HETATM    3 ZN   ZN  A 400      20.000   0.000   0.000  1.00 20.00          ZN
HETATM    4 NA   NA  A 401      20.000   0.000   0.000  1.00 20.00          NA
EOF
write_ligand_local_fpocket_input "$tmp/local-source.pdb" "$tmp/local-receptor.pdb" LIG 12.0 "$tmp/local.pdb"
grep -q 'ALA A   1' "$tmp/local.pdb" || fail "near-site protein atom was excluded"
! grep -q 'GLY A   2' "$tmp/local.pdb" || fail "outside-cutoff protein atom was retained"
grep -q 'ZN  A 400' "$tmp/local.pdb" || fail "supported metal context was excluded"
! grep -q 'NA  A 401' "$tmp/local.pdb" || fail "unsupported ion was retained"
! grep -q 'LIG A 100' "$tmp/local.pdb" || fail "site-defining ligand leaked into fpocket receptor input"

printf 'PASS: ligand detection and centroid helper checks\n'
