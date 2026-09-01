#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-ranked-pockets.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

write_pocket() {
  path="$1"; score="$2"; x="$3"
  cat > "$path" <<EOF
HEADER  Pocket Score : $score
ATOM      1 APOL STP C   1       $(printf '%7.3f' "$x")   0.000   0.000  1.00  2.00           C
ATOM      2 APOL STP C   2       $(awk -v x="$x" 'BEGIN{printf "%7.3f",x+1}')   0.000   0.000  1.00  1.00           C
EOF
}

mkdir -p "$tmp/pockets"
write_pocket "$tmp/pockets/p1.pdb" 0.90 0
write_pocket "$tmp/pockets/p2.pdb" 0.85 2
write_pocket "$tmp/pockets/p3.pdb" 0.80 30
write_pocket "$tmp/pockets/p4.pdb" 0.70 -30
printf '%s\n' "$tmp/pockets/p1.pdb" "$tmp/pockets/p2.pdb" "$tmp/pockets/p3.pdb" "$tmp/pockets/p4.pdb" > "$tmp/eligible.list"

select_ranked_fpocket_candidates "$tmp/eligible.list" centroid 0 0 0 2 13 0.60 "$tmp/selected" "$tmp/diagnostic.tsv"
[ "$(wc -l < "$tmp/selected" | tr -d ' ')" -eq 2 ] || fail "retained pocket count changed"
grep -q '|p1.pdb|' <(sed "s|$tmp/pockets/||" "$tmp/selected") || fail "highest weighted-rank pocket was not selected"
grep -q $'p2.pdb\t.*\tskipped\tbox_overlap_exceeds_MAX_OVERLAP_FRAC' "$tmp/diagnostic.tsv" || fail "overlap suppression changed"
grep -q $'p4.pdb\t.*\tskipped\tnot_retained_after_max_pockets\tNA' "$tmp/diagnostic.tsv" || fail "post-maximum audit changed"
[ "$(awk 'END{print NR}' "$tmp/diagnostic.tsv")" -eq 5 ] || fail "complete ranked audit changed"

# fpocket can emit a valid pocket whose depth values are all zero. Deepest-site
# selection must still use a real atom rather than silently defaulting to the
# coordinate origin.
cat > "$tmp/pockets/zero_depth.pdb" <<'EOF'
HEADER  Pocket Score : 0.95
ATOM      1 APOL STP C   1      17.000   0.000   0.000  0.00  0.00           C 0
ATOM      2 APOL STP C   2      18.000   0.000   0.000  0.00  0.00           C 0
EOF
printf '%s\n' "$tmp/pockets/zero_depth.pdb" > "$tmp/zero-depth.list"
select_ranked_fpocket_candidates "$tmp/zero-depth.list" deepest 0 0 0 1 13 0.60 \
  "$tmp/zero-depth.selected" "$tmp/zero-depth.tsv"
IFS='|' read -r _ _ zero_x zero_y zero_z _ < "$tmp/zero-depth.selected"
[ "$zero_x" = "17.000000" ] || fail "all-zero depth pocket defaulted away from its first atom"
[ "$zero_y" = "0.000000" ] && [ "$zero_z" = "0.000000" ] || fail "all-zero depth pocket coordinates changed"

printf 'PASS: fpocket ranked-selection characterization checks\n'
