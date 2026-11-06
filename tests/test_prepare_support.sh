#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-prepare-support.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

# shellcheck source=../libexec/docking-universal-prepare-support.sh
. "$root/libexec/docking-universal-prepare-support.sh"

for helper in log choose_feedback_level summarize_chains count_total_pockets \
  count_reasonable_pockets write_fpocket_run_summary; do
  command -v "$helper" >/dev/null 2>&1 || fail "missing sourced helper: $helper"
done

cat > "$tmp/receptor.pdb" <<'EOF'
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00  0.00           C
ATOM      3  N   GLY B   2       0.000   1.000   0.000  1.00  0.00           N
EOF
summarize_chains "$tmp/receptor.pdb" "$tmp/chains.tsv"
grep -q $'^A\t1\t2$' "$tmp/chains.tsv" || fail "chain A summary changed"
grep -q $'^B\t1\t1$' "$tmp/chains.tsv" || fail "chain B summary changed"

mkdir -p "$tmp/fpocket/pockets"
cat > "$tmp/fpocket/pockets/pocket1_atm.pdb" <<'EOF'
HEADER  Pocket Score : 0.50
ATOM      1 APOL STP C   1       0.000   0.000   0.000  1.00  0.00           C
ATOM      2 APOL STP C   2       5.000   4.000   3.000  1.00  0.00           C
EOF
cat > "$tmp/fpocket/pockets/pocket2_atm.pdb" <<'EOF'
HEADER  Pocket Score : 0.05
ATOM      1 APOL STP C   1       0.000   0.000   0.000  1.00  0.00           C
EOF

SCORE_THRESHOLD=0.10
POCKET_WARN_ATOMS=500
POCKET_WARN_BBOX=40.0
[ "$(count_total_pockets "$tmp/fpocket")" = 2 ] || fail "total pocket count changed"
[ "$(count_reasonable_pockets "$tmp/fpocket")" = 1 ] || fail "reasonable pocket count changed"

write_fpocket_run_summary test "$tmp/fpocket" "$tmp/summary.tsv"
[ "$(wc -l < "$tmp/summary.tsv" | tr -d ' ')" = 3 ] || fail "fpocket summary row count changed"
grep -q $'^test\tpocket1_atm.pdb\t0.50\t2\t5.000\t4.000\t3.000\t5.000\tyes\tok$' \
  "$tmp/summary.tsv" || fail "reasonable pocket summary changed"
grep -q $'^test\tpocket2_atm.pdb\t0.05\t1\t0.000\t0.000\t0.000\t0.000\tno\tok$' \
  "$tmp/summary.tsv" || fail "below-threshold pocket summary changed"

FEEDBACK_LEVEL=verbose
choose_feedback_level </dev/null
[ "$FEEDBACK_LEVEL" = verbose ] || fail "preselected feedback level changed"

# ADFRsuite is installed outside Conda. Its discovered executable must work
# for primary selection as well as the conditional fallback, without PATH edits.
mkdir -p "$tmp/runtime-tools" "$tmp/external-adfr"
printf '#!/bin/sh\nexit 0\n' > "$tmp/external-adfr/prepare_receptor"
chmod +x "$tmp/external-adfr/prepare_receptor"
for backend in auto adfr; do
  (
    unset CONDA_PREFIX DOCKING_UNIVERSAL_PYTHON DOCKING_UNIVERSAL_PREP_RECEPTOR
    PATH="$tmp/runtime-tools"
    DOCKING_UNIVERSAL_PREP_BACKEND="$backend"
    DOCKING_UNIVERSAL_ADFR_FALLBACK_BIN="$tmp/external-adfr/prepare_receptor"
    DOCKING_UNIVERSAL_PARAMETERIZATION_ONLY=1
    REFERENCE_SITE_ONLY=0
    POCKET_ENGINE=none
    resolve_prepare_runtime_tools
    [ "$PREP_BACKEND" = adfr ] || fail "external ADFR backend not selected"
    [ "$PREP_RECEPTOR_BIN" = "$tmp/external-adfr/prepare_receptor" ] || fail "external ADFR primary path was lost"
  ) || fail "$backend did not discover the external ADFR primary executable"
done

printf '#!/bin/sh\nexit 0\n' > "$tmp/runtime-tools/mk_prepare_receptor.py"
chmod +x "$tmp/runtime-tools/mk_prepare_receptor.py"
(
  unset CONDA_PREFIX DOCKING_UNIVERSAL_PYTHON DOCKING_UNIVERSAL_PREP_RECEPTOR
  PATH="$tmp/runtime-tools"
  DOCKING_UNIVERSAL_PREP_BACKEND=auto
  DOCKING_UNIVERSAL_ADFR_FALLBACK_BIN="$tmp/external-adfr/prepare_receptor"
  DOCKING_UNIVERSAL_PARAMETERIZATION_ONLY=1
  REFERENCE_SITE_ONLY=0
  POCKET_ENGINE=none
  resolve_prepare_runtime_tools
  [ "$PREP_BACKEND" = meeko ] || fail "external ADFR replaced available primary Meeko"
) || fail "automatic discovery changed primary preference"
(
  unset CONDA_PREFIX DOCKING_UNIVERSAL_PYTHON
  PATH="$tmp/runtime-tools"
  DOCKING_UNIVERSAL_PREP_BACKEND=adfr
  DOCKING_UNIVERSAL_PREP_RECEPTOR="$tmp/missing-explicit-backend"
  DOCKING_UNIVERSAL_ADFR_FALLBACK_BIN="$tmp/external-adfr/prepare_receptor"
  DOCKING_UNIVERSAL_PARAMETERIZATION_ONLY=1
  REFERENCE_SITE_ONLY=0
  POCKET_ENGINE=none
  if resolve_prepare_runtime_tools > "$tmp/explicit-backend-error.log" 2>&1; then
    fail "an invalid explicit primary backend was replaced by discovery"
  fi
) || fail "explicit primary backend precedence changed"

# A reviewed exclusion can remove the LINK that normally retains another
# component. Keep the pinned approved receptor inventory exactly, rather than
# silently deleting that newly orphaned component during a second filter pass.
(
  ROOT="$tmp/reviewed-inventory"
  RECEPTOR_DIR="$ROOT/receptor"
  mkdir -p "$RECEPTOR_DIR"
  CANONICAL=reviewed
  INPUT_PDB="$tmp/receptor.pdb"
  PYTHON_COMMAND="${DOCKING_UNIVERSAL_PYTHON:-python3}"
  LIBEXEC_DIR="$root/libexec"
  unset DOCKING_UNIVERSAL_SOURCE_MMCIF
  DOCKING_UNIVERSAL_PDBFIXER=off
  DOCKING_UNIVERSAL_PROTONATION=off
  DOCKING_UNIVERSAL_REDUCE2=off
  DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT="$tmp/approved-receptor.pdb"
  cat "$INPUT_PDB" > "$DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT"
  printf '%s\n' 'HETATM    4  C1  MAN C   3       2.000   0.000   0.000  1.00 20.00           C' >> "$DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT"
  DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT_SHA256=$(
    "$PYTHON_COMMAND" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT")
  DOCKING_UNIVERSAL_REVIEWED_MODEL_ONLY=0
  if initialize_receptor_preparation > "$tmp/unreviewed-inventory.log" 2>&1; then
    fail "a receptor inventory was accepted outside an explicit reviewed attempt"
  fi
  DOCKING_UNIVERSAL_REVIEWED_MODEL_ONLY=1
  approved_digest="$DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT_SHA256"
  DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT_SHA256=invalid
  if initialize_receptor_preparation > "$tmp/changed-inventory.log" 2>&1; then
    fail "a reviewed receptor inventory was accepted without its pinned hash"
  fi
  DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT_SHA256="$approved_digest"
  initialize_receptor_preparation || fail "the pinned reviewed receptor inventory was rejected"
  cmp -s "$DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT" "$RECEPTOR_FILTERED_PDB" || fail "an approved orphaned component was silently removed"
) || fail "reviewed receptor inventory guard changed"

printf 'PASS: receptor preparation support-library checks\n'
