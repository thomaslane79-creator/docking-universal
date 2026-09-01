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

printf 'PASS: receptor preparation support-library checks\n'
