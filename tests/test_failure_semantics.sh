#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-failure-tests.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

mock_obabel="$tmp/obabel"
cat > "$mock_obabel" <<'EOF'
#!/usr/bin/env bash
input=$1
shift
if [ "${1:-}" = "-osmi" ]; then
  printf 'C mock\n'
  exit 0
fi
output=""
split=0
optimize=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    -O) output=$2; shift 2 ;;
    -m) split=1; shift ;;
    --gen3d|--minimize) optimize=1; shift ;;
    *) shift ;;
  esac
done
if [ "$split" -eq 1 ]; then
  for index in 1 2 3; do printf 'ligand%s\n$$$$\n' "$index" > "${output%.sdf}${index}.sdf"; done
  exit 0
fi
case "$input" in *ligand2.sdf) [ "$optimize" -eq 0 ] || exit 1 ;; esac
printf 'converted\n' > "$output"
EOF
chmod +x "$mock_obabel"

mock_meeko="$tmp/mk_prepare_ligand.py"
cat > "$mock_meeko" <<'EOF'
#!/usr/bin/env bash
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in -o) output=$2; shift 2 ;; *) shift ;; esac
done
printf 'MODEL\nENDMDL\n' > "$output"
EOF
chmod +x "$mock_meeko"

printf 'one\n$$$$\nbroken\n$$$$\nthree\n$$$$\n' > "$tmp/library.sdf"

set +e
"$root/libexec/docking-universal-ligands" "$tmp/library.sdf" \
  --out "$tmp/output" --backend meeko --prepare-ligand "$mock_meeko" \
  --obabel "$mock_obabel" > "$tmp/stdout" 2> "$tmp/stderr"
status=$?
set -e

[ "$status" -ne 0 ] || fail "partial ligand preparation returned success"
[ -s "$tmp/output/pdbqt_ligands/library_1.pdbqt" ] || fail "first successful ligand was not retained"
[ -s "$tmp/output/pdbqt_ligands/library_3.pdbqt" ] || fail "third successful ligand was not retained"
[ ! -e "$tmp/output/pdbqt_ligands/library_2.pdbqt" ] || fail "failed ligand produced an output"
grep -q 'Prepared PDBQT:   2' "$tmp/stdout" || fail "success count was not reported"
grep -q 'Failed/skipped:   1' "$tmp/stdout" || fail "failure count was not reported"

mkdir -p "$tmp/dock_ligands"
printf 'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n' > "$tmp/receptor.pdbqt"
printf 'center_x = 0\ncenter_y = 0\ncenter_z = 0\nsize_x = 20\nsize_y = 20\nsize_z = 20\n' > "$tmp/box.conf"
printf 'MODEL\n' > "$tmp/dock_ligands/first.pdbqt"
printf 'MODEL\n' > "$tmp/dock_ligands/second.pdbqt"
mock_vina="$tmp/vina"
cat > "$mock_vina" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in --version) printf 'AutoDock Vina mock\n'; exit 0 ;; esac
ligand=""
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --ligand) ligand=$2; shift 2 ;;
    --out) output=$2; shift 2 ;;
    *) shift ;;
  esac
done
case "$ligand" in *first.pdbqt) exit 1 ;; esac
printf 'MODEL\nENDMDL\n' > "$output"
EOF
chmod +x "$mock_vina"

set +e
"$root/libexec/docking-universal-dock" --engine vina --engine-command "$mock_vina" \
  --receptor "$tmp/receptor.pdbqt" --ligands "$tmp/dock_ligands" \
  --config "$tmp/box.conf" --out "$tmp/dock_output" > "$tmp/dock_stdout" 2> "$tmp/dock_stderr"
dock_status=$?
set -e

[ "$dock_status" -ne 0 ] || fail "partial docking failure returned success"
[ -s "$tmp/dock_output/second_vina.pdbqt" ] || fail "dock did not continue after the first ligand failed"
grep -q 'Failed docking jobs: 1' "$tmp/dock_stdout" || fail "dock failure summary was not reported"

printf 'PASS: batch failure-semantics checks\n'
