#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-pocket-classification.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

write_pocket() {
  path="$1"; score="$2"; extent="$3"; extra="${4:-0}"
  mkdir -p "$(dirname "$path")"
  [ "$score" = NA ] || printf 'HEADER  Pocket Score : %s\n' "$score" > "$path"
  [ "$score" != NA ] || : > "$path"
  printf 'ATOM      1 APOL STP C   1       0.000   0.000   0.000  1.00  0.00           C\n' >> "$path"
  printf 'ATOM      2 APOL STP C   2       %7.3f   0.000   0.000  1.00  0.00           C\n' "$extent" >> "$path"
  if [ "$extra" -eq 1 ]; then
    printf 'ATOM      3 APOL STP C   3       1.000   1.000   0.000  1.00  0.00           C\n' >> "$path"
  fi
}

fp="$tmp/fpocket"
write_pocket "$fp/pockets/pocket1_atm.pdb" 0.70 5
write_pocket "$fp/pockets/pocket2_atm.pdb" 0.05 4
write_pocket "$fp/pockets/pocket3_atm.pdb" 0.80 35
write_pocket "$fp/pockets/pocket4_atm.pdb" NA 3
write_pocket "$fp/pockets/pocket5_atm.pdb" 0.60 2 1

classify_fpocket_candidates "$fp" "$tmp/strict" "$tmp/strict.tsv" 0.10 2 20.0 1
[ "$(wc -l < "$tmp/strict/eligible.list" | tr -d ' ')" -eq 1 ] || fail "strict eligible count changed"
[ "$(wc -l < "$tmp/strict/eligible_all.list" | tr -d ' ')" -eq 4 ] || fail "score-bearing candidate inventory changed"
grep -q $'pocket1_atm.pdb\t0.70\t.*\tyes\tpasses_score_and_geometry_filters\tok' "$tmp/strict.tsv" || fail "eligible reason changed"
grep -q $'pocket2_atm.pdb\t0.05\t.*\tno\tscore_below_threshold\tok' "$tmp/strict.tsv" || fail "score rejection changed"
grep -q $'pocket3_atm.pdb\t0.80\t.*\tno\tgeometry_too_large\tlarge_spatial_extent' "$tmp/strict.tsv" || fail "bbox safeguard changed"
grep -q $'pocket4_atm.pdb\tNA\t.*\tno\tmissing_pocket_score\tok' "$tmp/strict.tsv" || fail "missing-score diagnosis changed"
grep -q $'pocket5_atm.pdb\t0.60\t.*\tno\tgeometry_too_large\tlarge_alpha_sphere_count' "$tmp/strict.tsv" || fail "sphere-count safeguard changed"

classify_fpocket_candidates "$fp" "$tmp/review" "$tmp/review.tsv" 0.10 2 20.0 0
[ "$(wc -l < "$tmp/review/eligible.list" | tr -d ' ')" -eq 3 ] || fail "review-mode broad-pocket retention changed"

printf 'PASS: fpocket candidate-classification checks\n'
