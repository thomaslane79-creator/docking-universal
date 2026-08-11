#!/usr/bin/env bash
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cli="$project_dir/bin/docking-universal"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

bash -n "$cli" || fail "shell syntax"

help_output=$("$cli" --help)
case "$help_output" in
  *"Docking Universal - structural docking"*"docking-universal <command>"*) ;;
  *) fail "help output" ;;
esac

version_output=$("$cli" --version)
case "$version_output" in
  "Docking Universal 0.4.0"*) ;;
  *) fail "version output" ;;
esac

mock_dir=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-test.XXXXXX")
trap 'rm -rf "$mock_dir"' EXIT HUP INT TERM
: > "$mock_dir/fpocket"
: > "$mock_dir/prepare_receptor"
chmod +x "$mock_dir/fpocket" "$mock_dir/prepare_receptor"

doctor_output=$(PATH="$mock_dir:$PATH" "$cli" doctor)
case "$doctor_output" in
  *"Core tools"*"available  fpocket"*"available  prepare_receptor"*) ;;
  *) fail "doctor output" ;;
esac

mock_engine="$mock_dir/smina"
cat > "$mock_engine" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then
  echo "smina fake-0.1"
  exit 0
fi
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --out) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[ -n "$output" ] || exit 2
printf 'MODEL 1\nENDMDL\n' > "$output"
EOF
chmod +x "$mock_engine"
mkdir -p "$mock_dir/ligands"
printf 'ATOM\n' > "$mock_dir/receptor.pdbqt"
printf 'MODEL\n' > "$mock_dir/ligands/example.pdbqt"
printf 'MODEL\n' > "$mock_dir/ligands/example_two.pdbqt"
printf 'center_x = 0\ncenter_y = 0\ncenter_z = 0\nsize_x = 20\nsize_y = 20\nsize_z = 20\n' > "$mock_dir/box.conf"
"$cli" dock --engine smina --engine-command "$mock_engine" \
  --receptor "$mock_dir/receptor.pdbqt" --ligands "$mock_dir/ligands" \
  --config "$mock_dir/box.conf" --out "$mock_dir/results" >/dev/null || fail "dock engine command"
grep -q $'engine_version\tsmina fake-0.1' "$mock_dir/results/run_manifest.tsv" || fail "dock version manifest"
[ -s "$mock_dir/results/example_smina.pdbqt" ] || fail "dock output"
[ -s "$mock_dir/results/example_two_smina.pdbqt" ] || fail "multi-ligand dock output"

for command_name in run control calibrate ensemble prepare ligands pockets dock collect compare-redock evaluate-control screen cluster-poses interactions render3d depict2d; do
  "$cli" "$command_name" --help >/dev/null || fail "$command_name help"
done

PYTHONPYCACHEPREFIX="$mock_dir/pycache" "${DOCKING_UNIVERSAL_PYTHON:-python}" -m py_compile "$project_dir"/libexec/*.py || fail "Python syntax"

"$cli" evaluate-control --help | grep -q -- '--no-prompt' || fail "evaluate-control no-prompt help"
"$cli" control --help | grep -q -- '--infer-ligand-chemistry' || fail "provisional PDB chemistry help"

# A synthetic five-seed control verifies the v1 approval record without running
# an external docking engine. Each seed contains one conformer comparison.
comparison_args=""
seed_args=""
for seed in 101 102 103 104 105; do
  comparison_dir="$mock_dir/control_$seed/example_comparison"
  mkdir -p "$comparison_dir"
  printf '{"pose_count": 3, "top_score_affinity_kcal_per_mol": -7.0, "top_score_rmsd_angstrom": 1.2, "best_rmsd_angstrom": 0.8}\n' > "$comparison_dir/comparison_summary.json"
  comparison_args="$comparison_args $mock_dir/control_$seed"
  seed_args="$seed_args --seed $seed"
done
# Word splitting is intentional here: the generated arguments contain no spaces.
# shellcheck disable=SC2086
"$cli" evaluate-control $comparison_args --engine vina --out "$mock_dir/protocol.json" \
  --receptor "$mock_dir/receptor.pdbqt" --box "$mock_dir/box.conf" --threshold 2 \
  --exhaustiveness 16 --num-modes 15 --energy-range 8 $seed_args --min-seeds 5 \
  --conformers 3 --macrocycle-treatment flexible_meeko --no-prompt >/dev/null || fail "protocol evaluation"
grep -q '"schema_name": "docking-universal-protocol"' "$mock_dir/protocol.json" || fail "protocol schema"
grep -q '"unknown_docking_allowed": true' "$mock_dir/protocol.json" || fail "protocol approval"

# Screening must fail closed before launching chemistry tools when a protocol is
# unapproved. This protects automation from accidentally bypassing calibration.
printf 'test\n$$$$\n' > "$mock_dir/unknown.sdf"
sed 's/"unknown_docking_allowed": true/"unknown_docking_allowed": false/' "$mock_dir/protocol.json" > "$mock_dir/unapproved.json"
if "$cli" screen --protocol "$mock_dir/unapproved.json" --ligand "$mock_dir/unknown.sdf" --out "$mock_dir/blocked" --non-interactive >/dev/null 2>&1; then
  fail "unapproved protocol was accepted"
fi

"$cli" collect "$project_dir/tests/expected_outputs/engine_parser/vina_result.pdbqt" --out "$mock_dir/vina.csv" >/dev/null
grep -q 'example_vina,1,CCO,vina,-7.500,0.000,0.000,' "$mock_dir/vina.csv" || fail "Vina result parsing"
"$cli" collect "$project_dir/tests/expected_outputs/engine_parser/smina_result.pdbqt" --out "$mock_dir/smina.csv" >/dev/null
grep -q 'example_smina,1,CCO,smina,-8.250,,,1.125' "$mock_dir/smina.csv" || fail "smina result parsing"

printf 'PASS: Docking Universal CLI checks\n'
