#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_command=${DOCKING_UNIVERSAL_PYTHON:-python}
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-preparation-routes.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

write_base_pdb() {
  cat > "$1" <<'EOF'
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N
ATOM      2  CA  ALA A   1       1.500   0.000   0.000  1.00 20.00           C
ATOM      3  C   ALA A   1       2.000   1.500   0.000  1.00 20.00           C
ATOM      4  O   ALA A   1       1.500   2.500   0.000  1.00 20.00           O
END
EOF
}

write_fpocket_mock() {
  cat > "$1" <<'EOF'
#!/usr/bin/env bash
set -eu
input=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -f) input="$2"; shift 2 ;;
    *) shift ;;
  esac
done
out="${input%.pdb}_out"
mkdir -p "$out/pockets"
cat > "$out/pockets/pocket1_atm.pdb" <<'PDB'
HEADER  Pocket Score : 0.50
ATOM      1 APOL STP C   1       0.000   0.000   0.000  1.00  0.00           C
ATOM      2 APOL STP C   2       5.000   4.000   3.000  1.00  0.00           C
PDB
EOF
  chmod +x "$1"
}

write_meeko_mock() {
  cat > "$1" <<'EOF'
#!/usr/bin/env bash
set -eu
out=""
input=""
args=" $* "
count=0
if [ -f "${PREP_MOCK_STATE:?}" ]; then count=$(cat "$PREP_MOCK_STATE"); fi
count=$((count + 1))
printf '%s\n' "$count" > "$PREP_MOCK_STATE"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --read_pdb) input="$2"; shift 2 ;;
    -p) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done

succeed=0
case "${PREP_ROUTE_CASE:?}" in
  strict|ligand|parameterize|protonation_mmcif) succeed=1 ;;
  pdbfixer) [ "$count" -ge 2 ] && succeed=1 ;;
  disulfide)
    case "$args" in
      *--allow_bad_res*|*--default_altloc*)
        printf 'Automatic disulfide retry attempted unapproved omission or alternate-location selection\n' >&2
        exit 2 ;;
    esac
    case "$args" in *CYX*) succeed=1 ;; esac
    ;;
  histidine)
    case "$args" in
      *"--set_template A:1=HIE"*) succeed=1 ;;
      *) printf "for residue_key='A:1' tied for fewest missing H: HIE HID\n" >&2 ;;
    esac
    ;;
  adfr|adfr_unavailable|adfr_nonexecutable|adfr_disabled|adfr_startup|adfr_failed|adfr_no_artifact|adfr_atom_loss|adfr_charge_warning)
    printf "RuntimeError: Element Co doesn't have an implemented covalent radius\n" >&2
    printf 'linking fragments cannot be parameterized\n' >&2 ;;
  ineligible) printf "RuntimeError: Element Co doesn't have an implemented covalent radius\n" >&2 ;;
  removal) case "$args" in *--allow_bad_res*) succeed=1 ;; esac ;;
esac

if [ "$succeed" -ne 1 ]; then
  printf 'Template matching failed for: test fixture\n' >&2
  exit 1
fi

if [ "$PREP_ROUTE_CASE" = removal ]; then
  # Retain ALA but omit GLY so the production manifest records the approved
  # model change by comparing residue identities.
  cat > "$out" <<'PDBQT'
ATOM      1  N   ALA A   1       0.000   0.000   0.000  0.00  0.00      N
ATOM      2  CA  ALA A   1       1.500   0.000   0.000  0.00  0.00      C
PDBQT
else
  cat > "$out" <<'PDBQT'
ATOM      1  N   ALA A   1       0.000   0.000   0.000  0.00  0.00      N
PDBQT
fi
EOF
  chmod +x "$1"
}

write_adfr_mock() {
  cat > "$1" <<'EOF'
#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "${PREP_ADFR_STATE:?}"
# The application probes startup before sending a receptor. A usable backend
# fixture must support help without trying to write an unspecified output.
case "${1:-}" in
  -h|--help)
    [ "$PREP_ROUTE_CASE" != adfr_startup ] || { printf 'incompatible architecture fixture\n' >&2; exit 1; }
    printf 'usage: prepare_receptor -r receptor -o output\n'; exit 0 ;;
esac
[ "$PREP_ROUTE_CASE" != adfr_failed ] || { printf 'legacy parameterization failed\n' >&2; exit 1; }
[ "$PREP_ROUTE_CASE" != adfr_no_artifact ] || exit 0
out=""
input=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -r) input="$2"; shift 2 ;;
    -o) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
awk '/^(ATOM  |HETATM)/ {
  if (ENVIRON["PREP_ROUTE_CASE"] ~ /atom_loss$/ && $1 == "HETATM") next
  element=substr($0,77,2); gsub(/[[:space:]]/, "", element)
  atom_type=(element == "O" ? "OA" : element)
  printf "%s    %6.3f %s\n", substr($0,1,66), 0, atom_type
}' "$input" > "$out"
case "$PREP_ROUTE_CASE" in
  *charge_warning) printf 'Sorry, there are no Gasteiger parameters available for atom target:A:ALA1:O\n' >&2 ;;
esac
EOF
  chmod +x "$1"
}

run_route() {
  route_case="$1"
  interactive_input="${2:-}"
  expected_outcome="${3:-success}"
  case_dir="$tmp/$route_case"
  mkdir -p "$case_dir/tools"
  input="$case_dir/${route_case}.pdb"
  write_base_pdb "$input"
  protonation_mode=off
  pdb2pqr_command=pdb2pqr30

  case "$route_case" in
    protonation_mmcif)
      "$python_command" - "$input" "$case_dir/protonation_mmcif.cif" <<'PY'
import sys
import gemmi
gemmi.read_structure(sys.argv[1]).make_mmcif_document().write_file(sys.argv[2])
PY
      input="$case_dir/protonation_mmcif.cif"
      protonation_mode=required
      pdb2pqr_command="$case_dir/tools/pdb2pqr"
      cat > "$pdb2pqr_command" <<'PQR'
#!/usr/bin/env bash
set -eu
output=""
source_input=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --pdb-output) output="$2"; shift 2 ;;
    --with-ph) shift 2 ;;
    --*) shift ;;
    *) source_input="$1"; shift; break ;;
  esac
done
case "$source_input" in *.pdb) ;; *) echo 'Filtered mmCIF sent to PDB2PQR' >&2; exit 3 ;; esac
grep -q '^ATOM  ' "$source_input"
cp "$source_input" "$output"
PQR
      chmod +x "$pdb2pqr_command"
      ;;
    ligand)
      awk '/^END/ {
        for (i=0; i<10; i++)
          printf "HETATM%5d  C%-2d LIG A 101    %8.3f%8.3f%8.3f  1.00 20.00           C\n", 5+i, i, 10.0+i, 2.0, 3.0
      } { print }' "$input" > "$case_dir/with-ligand.pdb"
      input="$case_dir/with-ligand.pdb"
      ;;
    disulfide)
      {
        printf '%s\n' 'SSBOND   1 CYS A    1    CYS A    2'
        cat "$input"
      } > "$case_dir/with-ssbond.pdb"
      input="$case_dir/with-ssbond.pdb"
      ;;
    adfr|adfr_primary_atom_loss|adfr_primary_charge_warning|adfr_unavailable|adfr_nonexecutable|adfr_disabled|adfr_startup|adfr_failed|adfr_no_artifact|adfr_atom_loss|adfr_charge_warning)
      {
        printf '%s\n' 'LINK         CA  ALA A   1                 C1  ADX A 101'
        cat "$input"
        printf '%s\n' \
          'HETATM    5  C1  ADX A 101       3.000   1.500   0.000  1.00 20.00           C' \
          'HETATM    6  C2  ADX A 101       4.000   1.500   0.000  1.00 20.00           C'
      } > "$case_dir/with-link.pdb"
      input="$case_dir/with-link.pdb"
      ;;
    removal)
      awk '/^END/ { print "ATOM      5  N   GLY A   2       3.000   1.500   0.000  1.00 20.00           N" } { print }' \
        "$input" > "$case_dir/with-gly.pdb"
      input="$case_dir/with-gly.pdb"
      ;;
  esac

  write_fpocket_mock "$case_dir/tools/fpocket"
  write_meeko_mock "$case_dir/tools/mk_prepare_receptor.py"
  write_adfr_mock "$case_dir/tools/prepare_receptor"
  prep_backend=meeko
  prep_executable="$case_dir/tools/mk_prepare_receptor.py"
  adfr_executable="$case_dir/tools/prepare_receptor"
  adfr_enabled=1
  case "$route_case" in
    adfr_primary|adfr_primary_atom_loss|adfr_primary_charge_warning) prep_backend=adfr; prep_executable="$adfr_executable" ;;
    adfr_unavailable) adfr_executable="$case_dir/tools/missing_prepare_receptor" ;;
    adfr_nonexecutable) chmod -x "$adfr_executable" ;;
    adfr_disabled) adfr_enabled=0 ;;
  esac

  site_mode=pockets
  requested_ligand=""
  parameterization_only=0
  [ "$route_case" != parameterize ] || parameterization_only=1
  if [ "$route_case" = ligand ]; then
    site_mode=ligand
    requested_ligand=LIG
  fi

  command=(env
    PREP_ROUTE_CASE="$route_case"
    PREP_MOCK_STATE="$case_dir/meeko.count"
    PREP_ADFR_STATE="$case_dir/adfr.calls"
    FEEDBACK_LEVEL=concise
    DOCKING_UNIVERSAL_LOG_MODE=file
    DOCKING_UNIVERSAL_SITE_MODE="$site_mode"
    DOCKING_UNIVERSAL_PARAMETERIZATION_ONLY="$parameterization_only"
    DOCKING_UNIVERSAL_LIGAND_RESNAME="$requested_ligand"
    DOCKING_UNIVERSAL_CAVITY_MODE=1
    DOCKING_UNIVERSAL_POCKET_ENGINE=fpocket
    DOCKING_UNIVERSAL_MAX_POCKETS=3
    DOCKING_UNIVERSAL_CENTER_MODE=deepest
    DOCKING_UNIVERSAL_CENTROID_MODE=1
    DOCKING_UNIVERSAL_FPOCKET="$case_dir/tools/fpocket"
    DOCKING_UNIVERSAL_PREP_BACKEND="$prep_backend"
    DOCKING_UNIVERSAL_PREP_RECEPTOR="$prep_executable"
    DOCKING_UNIVERSAL_ADFR_FALLBACK_BIN="$adfr_executable"
    DOCKING_UNIVERSAL_ADFR_FALLBACK="$adfr_enabled"
    DOCKING_UNIVERSAL_PYTHON="$python_command"
    DOCKING_UNIVERSAL_PDBFIXER=off
    DOCKING_UNIVERSAL_PROTONATION="$protonation_mode"
    PDB2PQR_COMMAND="$pdb2pqr_command"
    DOCKING_UNIVERSAL_REDUCE2=off
    "$root/libexec/docking-universal-prepare" "$input")

  if [ "$route_case" = pdbfixer ]; then
    command=(env "${command[@]:1}")
    # Replace the final off setting without relying on duplicate-variable order.
    command=(env PREP_ROUTE_CASE="$route_case" PREP_MOCK_STATE="$case_dir/meeko.count" PREP_ADFR_STATE="$case_dir/adfr.calls" FEEDBACK_LEVEL=concise
      DOCKING_UNIVERSAL_LOG_MODE=file DOCKING_UNIVERSAL_SITE_MODE=pockets
      DOCKING_UNIVERSAL_CAVITY_MODE=1 DOCKING_UNIVERSAL_MAX_POCKETS=3
      DOCKING_UNIVERSAL_POCKET_ENGINE=fpocket
      DOCKING_UNIVERSAL_CENTER_MODE=deepest DOCKING_UNIVERSAL_CENTROID_MODE=1
      DOCKING_UNIVERSAL_FPOCKET="$case_dir/tools/fpocket"
      DOCKING_UNIVERSAL_PREP_BACKEND=meeko
      DOCKING_UNIVERSAL_PREP_RECEPTOR="$case_dir/tools/mk_prepare_receptor.py"
      DOCKING_UNIVERSAL_ADFR_FALLBACK_BIN="$case_dir/tools/prepare_receptor"
      DOCKING_UNIVERSAL_ADFR_FALLBACK=1 DOCKING_UNIVERSAL_PYTHON="$python_command"
      DOCKING_UNIVERSAL_PDBFIXER=required
      DOCKING_UNIVERSAL_PROTONATION=off
      DOCKING_UNIVERSAL_REDUCE2=off
      "$root/libexec/docking-universal-prepare" "$input")
  fi

  if [ -n "$interactive_input" ]; then
    if ! (cd "$case_dir" && "$python_command" "$root/tests/run_with_pty.py" "$interactive_input" "${command[@]}") > "$case_dir/terminal.log" 2>&1; then
      cat "$case_dir/terminal.log" >&2
      find "$case_dir" -name '*.log' -type f -exec sh -c 'echo "--- $1" >&2; cat "$1" >&2' _ {} \;
      fail "$route_case preparation command failed"
    fi
  else
    if ! (cd "$case_dir" && "${command[@]}") > "$case_dir/terminal.log" 2>&1; then
      if [ "$expected_outcome" = failure ]; then
        audit=$(find "$case_dir" -path '*/receptor/preparation_intervention.json' -type f -print | head -1)
        [ -s "$audit" ] || fail "$route_case did not retain a failure intervention"
        printf '%s\n' "$audit"
        return 0
      fi
      cat "$case_dir/terminal.log" >&2
      find "$case_dir" -name '*.log' -type f -exec sh -c 'echo "--- $1" >&2; cat "$1" >&2' _ {} \;
      fail "$route_case preparation command failed"
    fi
  fi
  [ "$expected_outcome" != failure ] || fail "$route_case unexpectedly prepared a receptor"

  audit=$(find "$case_dir" -path '*/receptor/ccd_modification_audit.json' -type f -print | head -1)
  if [ ! -s "$audit" ]; then
    cat "$case_dir/terminal.log" >&2
    fail "$route_case did not write a CCD/preparation-route audit"
  fi
  printf '%s\n' "$audit"
}

assert_route() {
  route_case="$1"
  expected="$2"
  interactive_input="${3:-}"
  audit=$(run_route "$route_case" "$interactive_input")
  "$python_command" - "$audit" "$expected" <<'PY'
import json
import sys
record = json.load(open(sys.argv[1]))
if record.get("preparation_route") != sys.argv[2]:
    raise SystemExit(f"expected route {sys.argv[2]!r}, got {record.get('preparation_route')!r}")
PY
}

assert_route strict strict_meeko
assert_route parameterize strict_meeko
assert_route protonation_mmcif strict_meeko
"$python_command" - "$tmp/protonation_mmcif/protonation_mmcif_receptor_prep/receptor/pdb2pqr_audit.json" <<'PY'
import json, sys
record = json.load(open(sys.argv[1]))
assert record['status'] == 'compatible', record
assert record['input_heavy_atom_count'] == 4, record
assert record['input'].endswith('_filtered.pdb'), record
PY
assert_route ligand strict_meeko
assert_route pdbfixer pdbfixer_then_strict_meeko
assert_route disulfide meeko_disulfide_templates
assert_route histidine guided_histidine_template $'1\n1\n'
assert_route adfr adfr_legacy_linked_component_fallback
assert_route adfr_primary adfr_primary
assert_route removal meeko_user_approved_component_removal $'y\n'

# Routing metadata must distinguish a skipped/unavailable fallback from an
# actual legacy backend attempt without hiding Meeko's original cobalt error.
assert_adfr_status() {
  local record="$1" expected="$2"
  "$python_command" - "$record" "$expected" <<'PY'
import json
import sys
from pathlib import Path
record = json.load(open(sys.argv[1]))
fallback = record.get("adfr_fallback", {})
assert fallback.get("status") == sys.argv[2], fallback
assert fallback.get("reason"), fallback
if sys.argv[2] in {"succeeded", "primary_backend", "validation_failed"}:
    assert Path(fallback["validation_log"]).is_file(), fallback
    validation = json.loads(Path(fallback["validation_audit"]).read_text())
    assert validation["status"] == ("rejected" if sys.argv[2] == "validation_failed" else "accepted"), validation
PY
}

assert_adfr_status "$tmp/strict/strict_receptor_prep/receptor/ccd_modification_audit.json" not_needed
assert_adfr_status "$(find "$tmp/adfr" -path '*/receptor/ccd_modification_audit.json' -type f -print | head -1)" succeeded
assert_adfr_status "$tmp/adfr_primary/adfr_primary_receptor_prep/receptor/ccd_modification_audit.json" primary_backend
[ ! -e "$tmp/adfr_primary/meeko.count" ] || fail "primary ADFR incorrectly invoked Meeko"
grep -q -- '-A none -U waters' "$tmp/adfr_primary/adfr.calls" || fail "primary ADFR repair flags changed"
grep -q -- '-A checkhydrogens' "$tmp/adfr/adfr.calls" || fail "fallback ADFR repair flags changed"

for scenario in unavailable nonexecutable disabled startup failed no_artifact atom_loss charge_warning; do
  case "$scenario" in
    nonexecutable) expected_status=unavailable ;;
    startup) expected_status=startup_failed ;;
    no_artifact) expected_status=failed ;;
    atom_loss|charge_warning) expected_status=validation_failed ;;
    *) expected_status="$scenario" ;;
  esac
  audit=$(run_route "adfr_$scenario" "" failure)
  assert_adfr_status "$audit" "$expected_status"
  grep -q 'Unsupported element in receptor preparation' "$audit" || fail "$scenario replaced the original diagnosis"
  grep -q 'Element Co' "${audit%/*}/receptor_failure_diagnosis.txt" || fail "$scenario hid the cobalt detail"
  grep -q "ADFRsuite fallback: $expected_status;" "${audit%/receptor/*}/run.log" || fail "$scenario omitted logged fallback status"
  case "$scenario" in
    unavailable|nonexecutable|disabled)
      [ ! -e "$tmp/adfr_$scenario/adfr.calls" ] || fail "$scenario invoked ADFR"
      [ ! -e "${audit%/*}/receptor_adfr_fallback.log" ] || fail "$scenario created misleading backend evidence" ;;
    startup)
      [ "$(wc -l < "$tmp/adfr_$scenario/adfr.calls" | tr -d ' ')" = 1 ] || fail "startup failure passed coordinates to ADFR"
      grep -q '^-h$' "$tmp/adfr_$scenario/adfr.calls" || fail "startup probe flags changed" ;;
    failed|no_artifact|atom_loss|charge_warning)
      grep -q -- '^-r ' "$tmp/adfr_$scenario/adfr.calls" || fail "$scenario never attempted the eligible backend" ;;
  esac
  if [ "$scenario" = charge_warning ]; then
    grep -q 'ADFR reported missing Gasteiger parameters' "$audit" || fail "charge rejection omitted its actual reason"
  fi
done
for scenario in atom_loss charge_warning; do
  audit=$(run_route "adfr_primary_$scenario" "" failure)
  assert_adfr_status "$audit" validation_failed
  grep -q 'Rejected ADFRsuite receptor output' "$audit" || fail "primary validation failure was misclassified"
  [ ! -e "$tmp/adfr_primary_$scenario/meeko.count" ] || fail "primary validation failure invoked Meeko"
  [ -s "${audit%/*}/adfr_output_audit.json" ] || fail "primary validation failure omitted its audit"
done
audit=$(run_route ineligible "" failure)
assert_adfr_status "$audit" ineligible
[ ! -e "$tmp/ineligible/adfr.calls" ] || fail "ineligible chemistry invoked ADFR"

# A reviewed derivative must stop after its one strict backend attempt. The
# generic mock rejects this case; ordinary automatic retries must not rescue it.
if (DOCKING_UNIVERSAL_REVIEWED_MODEL_ONLY=1 run_route reviewed) > "$tmp/reviewed-expected-failure.log" 2>&1; then
  fail "reviewed derivative unexpectedly passed the rejecting strict backend"
fi
[ "$(cat "$tmp/reviewed/meeko.count")" = 1 ] || fail "reviewed derivative ran an unapproved backend retry"
grep -q 'no additional repair' "$tmp/reviewed/reviewed_receptor_prep/run.log" || fail "reviewed strict-stop reason missing"
assert_adfr_status "$tmp/reviewed/reviewed_receptor_prep/receptor/preparation_intervention.json" reviewed_model_stop
[ ! -e "$tmp/reviewed/adfr.calls" ] || fail "reviewed model invoked ADFR"

parameterized_root="$tmp/parameterize/parameterize_receptor_prep"
[ -s "$parameterized_root/receptor/parameterize.pdbqt" ] || fail "parameterization-only receptor missing"
[ ! -e "$parameterized_root/cavity/parameterize_pocket1.conf" ] || fail "parameterization repeated pocket detection"
grep -q 'retained site review is unchanged' "$parameterized_root/run.log" || fail "parameterization-only completion missing"

# A successful strict route must leave the complete review and reuse surface,
# not merely a receptor PDBQT. This inventory protects the contract used by the
# CLI today and by a future GUI when it presents retained evidence.
strict_root=$(find "$tmp/strict" -maxdepth 2 -type d -name '*_receptor_prep' -print | head -1)
[ -n "$strict_root" ] || fail "strict route output directory was not created"
for required in \
  "$strict_root/run.log" \
  "$strict_root/chain_summary.tsv" \
  "$strict_root/receptor/strict.pdb" \
  "$strict_root/receptor/strict.pdbqt" \
  "$strict_root/receptor/ccd_modification_audit.json" \
  "$strict_root/cavity/pocket_diagnostics.tsv" \
  "$strict_root/cavity/pocket_selection_diagnostics.tsv" \
  "$strict_root/cavity/strict_README.txt" \
  "$strict_root/cavity/strict_pocket1_center.pdb" \
  "$strict_root/cavity/strict_pocket1_box.pdb" \
  "$strict_root/cavity/strict_pocket1.conf" \
  "$strict_root/cavity/strict_pocket1.pml"; do
  [ -s "$required" ] || fail "required preparation artifact missing or empty: $required"
done
grep -q '^center_x = ' "$strict_root/cavity/strict_pocket1.conf" || fail "Vina configuration is incomplete"
grep -q 'Pocket 1 | fpocket 0.50' "$strict_root/cavity/strict_pocket1.pml" || fail "PyMOL pocket identity is incomplete"
grep -q '^Docking Preparation Summary$' "$strict_root/cavity/strict_README.txt" || fail "preparation summary heading changed"

ligand_root=$(find "$tmp/ligand" -maxdepth 2 -type d -name '*_receptor_prep' -print | head -1)
ligand_conf=$(find "$ligand_root/cavity" -maxdepth 1 -name '*.conf' -print | head -1)
[ -s "$ligand_conf" ] || fail "ligand-guided route did not generate a docking configuration"
grep -q '^center_x = 14.500000$' "$ligand_conf" || fail "ligand-guided X center changed"
grep -q '^center_y = 2.000000$' "$ligand_conf" || fail "ligand-guided Y center changed"
grep -q '^center_z = 3.000000$' "$ligand_conf" || fail "ligand-guided Z center changed"

removal_manifest=$(find "$tmp/removal" -name user_approved_component_removal.tsv -type f -print | head -1)
removal_record=$(find "$tmp/removal" -name user_approved_component_removal.txt -type f -print | head -1)
[ -s "$removal_manifest" ] || fail "approved removal did not write a manifest"
[ -s "$removal_record" ] || fail "approved removal did not write an approval record"
grep -q $'A\t2\t\tGLY\t1' "$removal_manifest" || fail "approved removal manifest did not identify GLY A:2"
grep -q 'User approved component removal' "$removal_record" || fail "approved removal record changed"

printf 'PASS: receptor preparation route characterization checks\n'
