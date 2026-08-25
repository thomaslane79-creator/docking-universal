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
  *"Docking Universal - structural docking"*"docking-universal <command>"*"prepare-receptor"*"prepare-ligand"*) ;;
  *) fail "help output" ;;
esac

"$cli" prepare-receptor --help >/dev/null || fail "prepare-receptor alias"
"$cli" prepare-ligand --help >/dev/null || fail "prepare-ligand alias"

version_output=$("$cli" --version)
case "$version_output" in
  "Docking Universal 0.6.3"*) ;;
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

mkdir -p "$mock_dir/ligands"
printf 'ATOM\n' > "$mock_dir/receptor.pdbqt"
printf 'MODEL\n' > "$mock_dir/ligands/example.pdbqt"
printf 'MODEL\n' > "$mock_dir/ligands/example_two.pdbqt"
printf 'center_x = 0\ncenter_y = 0\ncenter_z = 0\nsize_x = 20\nsize_y = 20\nsize_z = 20\n' > "$mock_dir/box.conf"
# Exercise the primary AutoDock Vina routing independently of a local Vina
# installation. The mock validates argument/output plumbing; scientific engine
# behavior is covered by the retained completed example studies.
mock_vina="$mock_dir/vina"
cat > "$mock_vina" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then
  echo "AutoDock Vina fake-0.1"
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
printf 'MODEL 1\nREMARK VINA RESULT: -7.0 0.0 0.0\nENDMDL\n' > "$output"
EOF
chmod +x "$mock_vina"
"$cli" dock --engine vina --engine-command "$mock_vina" \
  --receptor "$mock_dir/receptor.pdbqt" --ligands "$mock_dir/ligands" \
  --config "$mock_dir/box.conf" --out "$mock_dir/vina_results" >/dev/null || fail "vina dock engine command"
grep -q $'engine_version\tAutoDock Vina fake-0.1' "$mock_dir/vina_results/run_manifest.tsv" || fail "vina version manifest"
[ -s "$mock_dir/vina_results/example_vina.pdbqt" ] || fail "vina dock output"
[ -s "$mock_dir/vina_results/example_two_vina.pdbqt" ] || fail "vina multi-ligand dock output"

# The research-preview interface is deliberately Vina-only. Obsolete smina
# selections must fail before any external engine is launched.
if "$cli" dock --engine smina --engine-command "$mock_vina" \
  --receptor "$mock_dir/receptor.pdbqt" --ligands "$mock_dir/ligands" \
  --config "$mock_dir/box.conf" --out "$mock_dir/rejected_smina" >/dev/null 2>&1; then
  fail "obsolete smina engine option was accepted"
fi

for command_name in run control calibrate ensemble prepare ligands pockets dock collect compare-redock evaluate-control screen cluster-poses interactions render3d depict2d validate; do
  "$cli" "$command_name" --help >/dev/null || fail "$command_name help"
done

"$cli" check-install >/dev/null || fail "check-install alias"

# A strict full-install check must accept either supported preparation backend,
# require Vina and the complete analysis stack, and use the selected Python for
# the PDBFixer/OpenMM import probe.
for tool in mk_prepare_receptor.py mk_prepare_ligand.py obabel plip pymol; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$mock_dir/$tool"
  chmod +x "$mock_dir/$tool"
done
cat > "$mock_dir/full-python" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$mock_dir/full-python"
PATH="$mock_dir:$PATH" DOCKING_UNIVERSAL_PYTHON="$mock_dir/full-python" \
  "$cli" check-install --full | grep -q 'Full pipeline check: PASS' \
  || fail "full installation check"

mock_graphical_chooser="$mock_dir/graphical-chooser"
cat > "$mock_graphical_chooser" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"prepared receptor PDBQT"*) printf '%s\n' "$DOCK_TEST_RECEPTOR" ;;
  *"docking-box configuration (.conf file)"*) printf '%s\n' "$DOCK_TEST_CONFIG" ;;
  *"ligand SDF"*) printf '%s\n' "$DOCK_TEST_SDF" ;;
  *"prepared ligand PDBQT directory"*) printf '%s\n' "$DOCK_TEST_LIGAND_DIR" ;;
  *"docking output directory"*) printf '%s\n' "$DOCK_TEST_OUTPUT" ;;
  *) exit 2 ;;
esac
EOF
chmod +x "$mock_graphical_chooser"

mkdir -p "$mock_dir/graphical_prepared_results"
graphical_prepared_output=$(printf '3\n' | env DISPLAY=:99 \
  DOCKING_UNIVERSAL_OSASCRIPT="$mock_graphical_chooser" \
  DOCKING_UNIVERSAL_ZENITY="$mock_graphical_chooser" \
  DOCKING_UNIVERSAL_VINA="$mock_vina" DOCK_TEST_RECEPTOR="$mock_dir/receptor.pdbqt" \
  DOCK_TEST_CONFIG="$mock_dir/box.conf" DOCK_TEST_LIGAND_DIR="$mock_dir/ligands" \
  DOCK_TEST_OUTPUT="$mock_dir/graphical_prepared_results" "$cli" dock 2>&1) \
  || fail "graphical prepared-ligand dock"
[ -s "$mock_dir/graphical_prepared_results/example_vina.pdbqt" ] || fail "graphical prepared-ligand output"
case "$graphical_prepared_output" in
  "Choose the prepared receptor PDBQT in Finder now."*|\
  "Choose the prepared receptor PDBQT with Zenity now."*) ;;
  *) fail "graphical receptor pre-launch feedback" ;;
esac
case "$graphical_prepared_output" in
  *"Choose the prepared docking-box configuration (.conf file) in Finder now."*|\
  *"Choose the prepared docking-box configuration (.conf file) with Zenity now."*) ;;
  *) fail "graphical docking-box file-type feedback" ;;
esac

mock_ligand_cli="$mock_dir/mock-ligand-cli"
cat > "$mock_ligand_cli" <<'EOF'
#!/usr/bin/env bash
[ "${1:-}" = "ligands" ] || exit 2
shift
original_args="$*"
out=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --out) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[ -n "$out" ] || exit 2
mkdir -p "$out/pdbqt_ligands"
printf 'MODEL\n' > "$out/pdbqt_ligands/from_sdf.pdbqt"
[ -z "${DOCK_TEST_LIGAND_LOG:-}" ] || printf '%s\n' "$original_args" > "$DOCK_TEST_LIGAND_LOG"
EOF
chmod +x "$mock_ligand_cli"
printf 'ligand\n$$$$\n' > "$mock_dir/ligand.sdf"
mkdir -p "$mock_dir/graphical_sdf_results"
printf '1\n' | env DISPLAY=:99 \
  DOCKING_UNIVERSAL_OSASCRIPT="$mock_graphical_chooser" \
  DOCKING_UNIVERSAL_ZENITY="$mock_graphical_chooser" \
  DOCKING_UNIVERSAL_CLI="$mock_ligand_cli" DOCKING_UNIVERSAL_VINA="$mock_vina" \
  DOCK_TEST_RECEPTOR="$mock_dir/receptor.pdbqt" DOCK_TEST_CONFIG="$mock_dir/box.conf" \
  DOCK_TEST_SDF="$mock_dir/ligand.sdf" DOCK_TEST_OUTPUT="$mock_dir/graphical_sdf_results" \
  DOCK_TEST_LIGAND_LOG="$mock_dir/graphical_sdf_ligand_args.txt" \
  "$cli" dock >/dev/null || fail "graphical SDF dock"
[ -s "$mock_dir/graphical_sdf_results/from_sdf_vina.pdbqt" ] || fail "graphical SDF output"
grep -q -- '--geometry-mode optimize' "$mock_dir/graphical_sdf_ligand_args.txt" || fail "graphical SDF optimization mode"

dock_prerequisite_output=""
if dock_prerequisite_output=$("$cli" dock --engine vina 2>&1); then
  fail "low-level dock without prepared inputs was accepted"
fi
case "$dock_prerequisite_output" in
  *"Run 'docking-universal prepare' first."*) ;;
  *) fail "dock preparation prerequisite feedback" ;;
esac

PYTHONPYCACHEPREFIX="$mock_dir/pycache" "${DOCKING_UNIVERSAL_PYTHON:-python}" -m py_compile "$project_dir"/libexec/*.py || fail "Python syntax"

"$cli" evaluate-control --help | grep -q -- '--no-prompt' || fail "evaluate-control no-prompt help"
"$cli" control-stage --help | grep -q -- '--infer-ligand-chemistry' || fail "provisional PDB chemistry stage help"

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

# A complete approved protocol must validate its locked inputs and drive the
# high-level screen planner, not merely contain an approval boolean.
approved_ligand="$project_dir/examples/tutorials/01_bound_ligand/inputs/rilpivirine_pubchem.sdf"
"$cli" _screen-stage --protocol "$mock_dir/protocol.json" --ligand "$approved_ligand" \
  --out "$mock_dir/approved_check" --check-only --non-interactive >/dev/null \
  || fail "approved protocol check"
"$cli" screen --protocol "$mock_dir/protocol.json" --ligands "$approved_ligand" \
  --out "$mock_dir/approved_plan" --name approved_protocol_test --plan-only --non-interactive >/dev/null \
  || fail "public approved protocol screen planning"
[ -s "$mock_dir/approved_plan/study_manifest.json" ] || fail "approved protocol study manifest"

missing_protocol_output=""
if missing_protocol_output=$("$cli" screen --protocol "$mock_dir/missing_protocol.json" \
  --ligands "$approved_ligand" --out "$mock_dir/missing_plan" --plan-only --non-interactive 2>&1); then
  fail "missing protocol was accepted"
fi
case "$missing_protocol_output" in
  *"Protocol does not exist:"*) ;;
  *) fail "missing protocol feedback" ;;
esac

# Screening must fail closed before launching chemistry tools when a protocol is
# unapproved. This protects automation from accidentally bypassing calibration.
printf 'test\n$$$$\n' > "$mock_dir/unknown.sdf"
sed 's/"unknown_docking_allowed": true/"unknown_docking_allowed": false/' "$mock_dir/protocol.json" > "$mock_dir/unapproved.json"
if "$cli" screen --protocol "$mock_dir/unapproved.json" --ligands "$mock_dir/unknown.sdf" --out "$mock_dir/blocked" --non-interactive >/dev/null 2>&1; then
  fail "unapproved protocol was accepted"
fi

"$cli" collect "$project_dir/tests/expected_outputs/engine_parser/vina_result.pdbqt" --out "$mock_dir/vina.csv" >/dev/null
grep -q 'example_vina,1,CCO,vina,-7.500,0.000,0.000' "$mock_dir/vina.csv" || fail "Vina result parsing"

printf 'PASS: Docking Universal CLI checks\n'
