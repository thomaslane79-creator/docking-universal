#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-fpocket-selection.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

SCORE_THRESHOLD=0.10
POCKET_WARN_ATOMS=4
POCKET_WARN_BBOX=20.0

write_pocket() {
  path="$1"; score="$2"; extent="$3"
  mkdir -p "$(dirname "$path")"
  cat > "$path" <<EOF
HEADER  Pocket Score : $score
ATOM      1 APOL STP C   1       0.000   0.000   0.000  1.00  0.00           C
ATOM      2 APOL STP C   2       $extent   0.000   0.000  1.00  0.00           C
EOF
}

modified="$tmp/modified"
conservative="$tmp/conservative"

# The modified run has one acceptable pocket and one high-scoring but
# spatially broad pocket. Conservative has two acceptable localized pockets.
write_pocket "$modified/pockets/pocket1_atm.pdb" 0.80 5.000
write_pocket "$modified/pockets/pocket2_atm.pdb" 0.90 45.000
write_pocket "$conservative/pockets/pocket1_atm.pdb" 0.60 4.000
write_pocket "$conservative/pockets/pocket2_atm.pdb" 0.50 8.000

IFS=$'\t' read -r selected label < <(select_fpocket_comparison_run "$modified" "$conservative" expanded_m2_5)
[ "$selected" = "$conservative" ] || fail "conservative run no longer wins when it has more reasonable pockets"
[ "$label" = conservative ] || fail "conservative provenance label changed"

# On a tie, retain the user-selected modified mode rather than silently
# replacing it with the conservative comparison.
rm -f "$conservative/pockets/pocket2_atm.pdb"
IFS=$'\t' read -r selected label < <(select_fpocket_comparison_run "$modified" "$conservative" expanded_m2_5)
[ "$selected" = "$modified" ] || fail "modified run no longer wins a reasonable-pocket tie"
[ "$label" = expanded_m2_5 ] || fail "modified provenance label changed"

printf 'PASS: fpocket comparison-selection characterization checks\n'
