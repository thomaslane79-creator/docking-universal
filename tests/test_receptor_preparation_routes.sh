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
  strict|ligand) succeed=1 ;;
  pdbfixer) [ "$count" -ge 2 ] && succeed=1 ;;
  disulfide) case "$args" in *CYX*) succeed=1 ;; esac ;;
  histidine)
    case "$args" in
      *"--set_template A:1=HIE"*) succeed=1 ;;
      *) printf "for residue_key='A:1' tied for fewest missing H: HIE HID\n" >&2 ;;
    esac
    ;;
  adfr) printf 'linking fragments cannot be parameterized\n' >&2 ;;
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
out=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf 'ATOM      1  N   ALA A   1       0.000   0.000   0.000  0.00  0.00      N\n' > "$out"
EOF
  chmod +x "$1"
}

run_route() {
  route_case="$1"
  interactive_input="${2:-}"
  case_dir="$tmp/$route_case"
  mkdir -p "$case_dir/tools"
  input="$case_dir/${route_case}.pdb"
  write_base_pdb "$input"

  case "$route_case" in
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
    adfr)
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

  site_mode=pockets
  requested_ligand=""
  if [ "$route_case" = ligand ]; then
    site_mode=ligand
    requested_ligand=LIG
  fi

  command=(env
    PREP_ROUTE_CASE="$route_case"
    PREP_MOCK_STATE="$case_dir/meeko.count"
    FEEDBACK_LEVEL=concise
    DOCKING_UNIVERSAL_LOG_MODE=file
    DOCKING_UNIVERSAL_SITE_MODE="$site_mode"
    DOCKING_UNIVERSAL_LIGAND_RESNAME="$requested_ligand"
    DOCKING_UNIVERSAL_CAVITY_MODE=1
    DOCKING_UNIVERSAL_MAX_POCKETS=3
    DOCKING_UNIVERSAL_CENTER_MODE=deepest
    DOCKING_UNIVERSAL_CENTROID_MODE=1
    DOCKING_UNIVERSAL_FPOCKET="$case_dir/tools/fpocket"
    DOCKING_UNIVERSAL_PREP_BACKEND=meeko
    DOCKING_UNIVERSAL_PREP_RECEPTOR="$case_dir/tools/mk_prepare_receptor.py"
    DOCKING_UNIVERSAL_ADFR_FALLBACK_BIN="$case_dir/tools/prepare_receptor"
    DOCKING_UNIVERSAL_ADFR_FALLBACK=1
    DOCKING_UNIVERSAL_PYTHON="$python_command"
    DOCKING_UNIVERSAL_PDBFIXER=off
    "$root/libexec/docking-universal-prepare" "$input")

  if [ "$route_case" = pdbfixer ]; then
    command=(env "${command[@]:1}")
    # Replace the final off setting without relying on duplicate-variable order.
    command=(env PREP_ROUTE_CASE="$route_case" PREP_MOCK_STATE="$case_dir/meeko.count" FEEDBACK_LEVEL=concise
      DOCKING_UNIVERSAL_LOG_MODE=file DOCKING_UNIVERSAL_SITE_MODE=pockets
      DOCKING_UNIVERSAL_CAVITY_MODE=1 DOCKING_UNIVERSAL_MAX_POCKETS=3
      DOCKING_UNIVERSAL_CENTER_MODE=deepest DOCKING_UNIVERSAL_CENTROID_MODE=1
      DOCKING_UNIVERSAL_FPOCKET="$case_dir/tools/fpocket"
      DOCKING_UNIVERSAL_PREP_BACKEND=meeko
      DOCKING_UNIVERSAL_PREP_RECEPTOR="$case_dir/tools/mk_prepare_receptor.py"
      DOCKING_UNIVERSAL_ADFR_FALLBACK_BIN="$case_dir/tools/prepare_receptor"
      DOCKING_UNIVERSAL_ADFR_FALLBACK=1 DOCKING_UNIVERSAL_PYTHON="$python_command"
      DOCKING_UNIVERSAL_PDBFIXER=required
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
      cat "$case_dir/terminal.log" >&2
      find "$case_dir" -name '*.log' -type f -exec sh -c 'echo "--- $1" >&2; cat "$1" >&2' _ {} \;
      fail "$route_case preparation command failed"
    fi
  fi

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
assert_route ligand strict_meeko
assert_route pdbfixer pdbfixer_then_strict_meeko
assert_route disulfide meeko_disulfide_templates
assert_route histidine guided_histidine_template $'1\n1\n'
assert_route adfr adfr_legacy_linked_component_fallback
assert_route removal meeko_user_approved_component_removal $'y\n'

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
