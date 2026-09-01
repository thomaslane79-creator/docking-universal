#!/usr/bin/env bash

# fpocket execution, cavity geometry, candidate classification, ranking, and adjacency.
# Sourced through docking-universal-prepare-support.sh; not executed directly.

count_total_pockets() {
  local outdir="$1"
  local count
  count=$(ls "$outdir"/pockets/pocket*_atm.pdb 2>/dev/null | wc -l | tr -d ' ')
  echo "${count:-0}"
}

count_reasonable_pockets() {
  local outdir="$1"
  local count=0
  local atm score atoms max_bbox

  for atm in "$outdir"/pockets/pocket*_atm.pdb; do
    [ -e "$atm" ] || continue
    score=$(awk -F':' '/Pocket Score/ {gsub(/ /,"",$2); print $2; exit}' "$atm")
    [ -n "$score" ] || continue
    awk -v s="$score" -v t="$SCORE_THRESHOLD" 'BEGIN{exit !(s>=t)}' || continue

    atoms=$(awk '/^(ATOM|HETATM)/ {n++} END{print n+0}' "$atm")
    max_bbox=$(awk '
      /^(ATOM|HETATM)/ {
        x=substr($0,31,8)+0; y=substr($0,39,8)+0; z=substr($0,47,8)+0
        if (n==0 || x<minx) minx=x; if (n==0 || x>maxx) maxx=x
        if (n==0 || y<miny) miny=y; if (n==0 || y>maxy) maxy=y
        if (n==0 || z<minz) minz=z; if (n==0 || z>maxz) maxz=z
        n++
      }
      END {
        if (n==0) { print 0; exit }
        bx=maxx-minx; by=maxy-miny; bz=maxz-minz; m=bx
        if (by>m) m=by; if (bz>m) m=bz
        printf "%.3f", m
      }
    ' "$atm")

    awk -v a="$atoms" -v lim="$POCKET_WARN_ATOMS" 'BEGIN{exit !(a<=lim)}' || continue
    awk -v b="$max_bbox" -v lim="$POCKET_WARN_BBOX" 'BEGIN{exit !(b<=lim)}' || continue
    count=$((count+1))
  done

  echo "$count"
}

# Resolve the cavity-search and box-center policy before fpocket is executed.
#
# Scientific intent: ligand-guided studies use the deposited ligand centroid
# and one search region. Ligand-free studies explicitly choose fpocket
# sensitivity, the number of hypotheses retained for review, and the protein
# centroid used only for ranking. These choices affect where docking searches;
# they do not modify receptor chemistry or fpocket's reported geometry.
#
# Required caller state: LIG_PRESENT, receptor/chain paths, feedback helpers,
# and the corresponding DOCKING_UNIVERSAL_* environment settings.
# Published caller state: MODE, MAX_POCKETS, UNATTENDED_CAVITY, CENTER_MODE,
# CENTROID_SEL, and ligand-free PROT_CX/PROT_CY/PROT_CZ.
# Protected by: tests/test_receptor_preparation_routes.sh.
resolve_pocket_search_policy() {
  local cavity_selection
  if [ "$LIG_PRESENT" -eq 1 ]; then
    log "Ligand detected -> using ligand-centered mode"
    MODE=1
    MAX_POCKETS=1
    UNATTENDED_CAVITY=1
    CENTER_MODE=centroid
    CENTROID_SEL=1
    log "Ligand mode -> using centroid center"
    return 0
  fi

  MODE="${DOCKING_UNIVERSAL_CAVITY_MODE:-}"
  MAX_POCKETS="${DOCKING_UNIVERSAL_MAX_POCKETS:-}"
  UNATTENDED_CAVITY=0
  if [ -n "$MODE" ]; then
    UNATTENDED_CAVITY=1
    [ -n "$MAX_POCKETS" ] || MAX_POCKETS=3
    log "Unattended cavity settings: mode $MODE; retaining $MAX_POCKETS cavities"
  elif feedback_at_least_guided; then
    echo "fpocket cavity mode guidance:"
    echo "1) Conservative/default fpocket"
    echo "   Use when you want fewer, higher-confidence pockets and less surface noise."
    echo "2) Expanded (-m 2.5)"
    echo "   Recommended first expansion when conservative misses shallow/partially open pockets."
    echo "3) Permissive (-m 2.0)"
    echo "   Most permissive; may merge broad clefts into giant high-score pockets. Use diagnostically."
  else
    echo "fpocket cavity mode: 1) Conservative  2) Expanded (-m 2.5)  3) Permissive (-m 2.0)"
  fi
  [ -n "$MODE" ] || read -r -p "Select cavity mode [1-3]: " MODE
  echo "Number of retained cavities controls how many site hypotheses proceed to review; it does not improve fpocket ranking."
  if [ "$UNATTENDED_CAVITY" -eq 0 ] && [ -z "${DOCKING_UNIVERSAL_MAX_POCKETS:-}" ]; then
    read -r -p "How many cavities to select? [3] " MAX_POCKETS
    MAX_POCKETS="${MAX_POCKETS:-3}"
  fi
  if ! [[ "$MAX_POCKETS" =~ ^[0-9]+$ ]] || [ "$MAX_POCKETS" -lt 3 ]; then
    echo "Exploratory pocket review retains at least three candidates; using 3."
    MAX_POCKETS=3
  fi

  CENTER_MODE="${DOCKING_UNIVERSAL_CENTER_MODE:-}"
  CENTROID_SEL="${DOCKING_UNIVERSAL_CENTROID_MODE:-}"
  if [ "$UNATTENDED_CAVITY" -eq 1 ] && [ -z "$CENTER_MODE" ]; then
    CENTER_MODE=centroid
    CENTROID_SEL=1
  fi
  if [ -n "$CENTER_MODE" ]; then
    [ "$CENTER_MODE" = deepest ] || [ "$CENTER_MODE" = centroid ] || {
      echo "ERROR: DOCKING_UNIVERSAL_CENTER_MODE must be deepest or centroid" >&2
      return 2
    }
    [ -n "$CENTROID_SEL" ] || CENTROID_SEL=1
    log "Unattended center settings: $CENTER_MODE; centroid scope $CENTROID_SEL"
  fi

  echo
  echo "Center mode:"
  if feedback_at_least_guided; then
    echo "1) deepest   (largest fpocket alpha sphere; often more entrance/surface biased)"
    echo "2) centroid  (interior, snapped to real pocket; often better for docking boxes)"
    echo "Scientific implication: the selected center changes the spatial region sampled by docking."
  else
    echo "1) deepest"
    echo "2) centroid"
  fi
  if [ "$UNATTENDED_CAVITY" -eq 0 ] && [ -z "${DOCKING_UNIVERSAL_CENTER_MODE:-}" ]; then
    read -r -p "Select center mode [1-2]: " cavity_selection
    [ "$cavity_selection" = 2 ] && CENTER_MODE=centroid || CENTER_MODE=deepest
  fi

  if feedback_at_least_guided; then
    print_chain_guidance "$CHAIN_SUMMARY"
    echo
    echo "Centroid mode:"
    echo "1) Whole protein"
    echo "   Best for single-chain receptors or compact monomers."
    echo "2) Per-chain (recommended for multi-chain structures)"
    echo "   Best when multiple chains are present; avoids using a global centroid between chains."
    echo "Scientific implication: centroid scope changes cavity-ranking geometry, especially in oligomers."
  else
    echo "Centroid mode: 1) Whole protein  2) Per-chain"
  fi
  if [ "$UNATTENDED_CAVITY" -eq 0 ] && [ -z "${DOCKING_UNIVERSAL_CENTROID_MODE:-}" ]; then
    read -r -p "Select centroid mode [1-2]: " CENTROID_SEL
  fi

  read -r PROT_CX PROT_CY PROT_CZ <<< "$(protein_ranking_centroid "$RECEPTOR_PDB" "$CENTROID_SEL")"
  if [ "$CENTROID_SEL" = 2 ]; then
    log "Using centroid of largest chain"
  else
    log "Using whole-protein centroid"
  fi
}

# Classify fpocket candidates and publish the retained site records.
# Ligand mode pins the numeric center to the deposited ligand while using
# overlapping spheres as visual cavity evidence. Ligand-free mode ranks
# eligible candidates and suppresses substantially overlapping boxes.
# Every exclusion and retained record remains available in diagnostic TSVs.
# Published state: SORTED and SELECTION_DIAG. Protected by candidate,
# ranked-selection, ligand-merge, and receptor-route tests.
classify_and_select_fpocket_sites() {
log "Entering Step 3: filtering pockets from $FP_OUT"
classify_fpocket_candidates "$FP_OUT" "$FROZEN_DIR" "$POCKET_DIAG" \
  "$SCORE_THRESHOLD" "$POCKET_WARN_ATOMS" "$POCKET_WARN_BBOX" "$STRICT_LOCAL_POCKETS"

log "Pocket diagnostics written to $POCKET_DIAG"
ELIGIBLE_COUNT=$(wc -l < "$FROZEN_DIR/eligible.list" | tr -d " ")
ALL_SCORE_PARSED_COUNT=$(wc -l < "$FROZEN_DIR/eligible_all.list" | tr -d " ")
log "Selectable pockets after score/geometry filters: ${ELIGIBLE_COUNT}; score-parsed pockets: ${ALL_SCORE_PARSED_COUNT}"
if feedback_at_least_guided; then
  echo
  echo "Fpocket pocket diagnostics:"
  awk -F '\t' 'NR==1 {next} {printf "  %s  score=%s  alpha_spheres=%s  bbox=%sx%sx%s A  eligible=%s  warning=%s\n", $1,$2,$3,$4,$5,$6,$8,$10}' "$POCKET_DIAG"
  echo
  echo "Guidance: a single fpocket pocket can still be very broad. If bbox or alpha_spheres are large,"
  echo "rendering it as a PyMOL surface may look like a whole-protein surface. Default visualization uses spheres."
fi

###############################################################################
# STEP 4: COMPUTE CENTERS
###############################################################################

if [ "$LIG_PRESENT" -eq 1 ]; then

  # use the merged pocket (all PQR alpha spheres near ligand centroid) if available
  MERGED="$FP_OUT/pockets/pocket_ligand_merged_atm.pdb"
  MERGED_COUNT=$(awk '/^ATOM|^HETATM/{n++} END{print n+0}' "$MERGED" 2>/dev/null || echo 0)

  if [ "$MERGED_COUNT" -gt 0 ]; then
    echo "Using merged pocket ($MERGED_COUNT alpha spheres) for cavity definition"
    BEST_GEOM="$MERGED"
    BEST_SCORE="merged"
    BEST_OVL="$MERGED_COUNT"
  else
    # fallback: overlap-based selection across individual pocket files
    echo "Merged pocket empty - falling back to overlap search across individual pockets"
    BEST_OVL=""
    BEST_GEOM=""
    BEST_SCORE=""

    while read -r GEOM; do
      SCORE=$(awk -F':' '/Pocket Score/ {gsub(/ /,"",$2); print $2}' "$GEOM")

      OVL=$(awk -v lx="$LIGX" -v ly="$LIGY" -v lz="$LIGZ" '
        /^ATOM/ {
          x=substr($0,31,8); y=substr($0,39,8); z=substr($0,47,8)
          d=sqrt((x-lx)^2+(y-ly)^2+(z-lz)^2)
          if (d <= 6.0) n++
        }
        END { print n+0 }
      ' "$GEOM")

      if [ -z "$BEST_OVL" ] || awk "BEGIN{exit !($OVL > $BEST_OVL)}"; then
        BEST_OVL="$OVL"
        BEST_GEOM="$GEOM"
        BEST_SCORE="$SCORE"
      fi
    done < "$FROZEN_DIR/eligible_all.list"

    echo "Best overlapping pocket: $(basename "$BEST_GEOM") (alpha atoms within 6A of ligand: $BEST_OVL)"
  fi

  # box and conf center pinned to ligand centroid
  SORTED=("0|$BEST_GEOM|$LIGX|$LIGY|$LIGZ|$BEST_SCORE")

else
  SELECTION_DIAG="$CAVITY_DIR/pocket_selection_diagnostics.tsv"
  SELECTED_RECORDS="$CAVITY_DIR/selected_pocket_records.txt"
  select_ranked_fpocket_candidates "$FROZEN_DIR/eligible.list" "$CENTER_MODE" \
    "$PROT_CX" "$PROT_CY" "$PROT_CZ" "$MAX_POCKETS" "$HALF_BOX" \
    "$MAX_OVERLAP_FRAC" "$SELECTED_RECORDS" "$SELECTION_DIAG"
  SORTED=()
  while IFS= read -r REC; do
    [ -n "$REC" ] && SORTED+=("$REC")
  done < "$SELECTED_RECORDS"

  log "Pocket selection diagnostics written to $SELECTION_DIAG"
  if feedback_at_least_guided; then
    echo
    echo "Pocket selection decisions:"
    awk -F '\t' 'NR==1 {next} {printf "  order=%s  %s  score=%s  rank=%s  decision=%s  reason=%s  max_overlap=%s\n", $1,$2,$3,$4,$8,$9,$10}' "$SELECTION_DIAG"
    echo
  fi

fi
}

# Execute the selected fpocket strategy and publish its authoritative output.
#
# Scientific intent: ligand-guided searches operate on a local receptor subset;
# ligand-free expanded/permissive searches may be compared with a conservative
# run so the workflow retains the run yielding more localized, reviewable
# hypotheses. The comparison is fully recorded and does not combine pockets
# across independently generated fpocket runs.
# Required caller state: resolved MODE/LIG_PRESENT policy and preparation paths.
# Published caller state: FP_INPUT, FP_OUT, PQR, and SELECTED_FP_RUN_LABEL.
# Protected by: tests/test_fpocket_runner.sh,
# tests/test_fpocket_selection.sh, and receptor route characterization tests.
execute_fpocket_strategy() {
  local fp_local local_atoms fp_local_out selected_probe selected_label
  local modified_out conservative_out modified_total conservative_total
  local modified_reasonable conservative_reasonable

  FP_INPUT="$CAVITY_DIR/fpocket_input.pdb"
  cp "$RECEPTOR_PDB" "$FP_INPUT"
  FP_OUT="${FP_INPUT%.pdb}_out"
  rm -rf "$FP_OUT"

  if [ "$LIG_PRESENT" -eq 1 ]; then
    fp_local="$CAVITY_DIR/fpocket_input_local.pdb"
    log "Extracting binding site residues (within 12A of ligand)..."
    write_ligand_local_fpocket_input "$INPUT_PDB" "$FP_INPUT" "$LIG" 12.0 "$fp_local"
    local_atoms=$(grep -c '^ATOM' "$fp_local" || echo 0)
    echo "Local binding site: $local_atoms atoms -> running fpocket (probe -m 2.5)..."
    fp_local_out="${fp_local%.pdb}_out"
    run_fpocket_to_directory "$FPOCKET_BIN" "$fp_local" 2.5 "$fp_local_out"
    log "fpocket complete"
    FP_OUT="$fp_local_out"
    SELECTED_FP_RUN_LABEL=ligand_local_m2_5
    PQR="$fp_local_out/$(basename "$fp_local" .pdb)_pockets.pqr"
    return 0
  fi

  if [ "$MODE" = 2 ] || [ "$MODE" = 3 ]; then
    if [ "$MODE" = 2 ]; then
      selected_probe=2.5
      selected_label=expanded_m2_5
    else
      selected_probe=2.0
      selected_label=permissive_m2_0
    fi

    if [ "$HYBRID_COMPARE_FP_MODE" = 1 ]; then
      log "Running fpocket (${selected_label}, -m ${selected_probe})..."
      modified_out="${FP_INPUT%.pdb}_${selected_label}_out"
      run_fpocket_to_directory "$FPOCKET_BIN" "$FP_INPUT" "$selected_probe" "$modified_out"
      log "fpocket ${selected_label} complete"
      log "Running fpocket (conservative comparison mode)..."
      conservative_out="${FP_INPUT%.pdb}_conservative_out"
      run_fpocket_to_directory "$FPOCKET_BIN" "$FP_INPUT" '' "$conservative_out"
      log "fpocket conservative comparison complete"

      printf 'run_label\tpocket_file\tscore\talpha_spheres\tbbox_x\tbbox_y\tbbox_z\tmax_bbox\treasonable\twarning\n' > "$FPOCKET_COMPARISON"
      write_fpocket_run_summary "$selected_label" "$modified_out" "$FPOCKET_COMPARISON"
      write_fpocket_run_summary conservative "$conservative_out" "$FPOCKET_COMPARISON"
      modified_total=$(count_total_pockets "$modified_out")
      conservative_total=$(count_total_pockets "$conservative_out")
      modified_reasonable=$(count_reasonable_pockets "$modified_out")
      conservative_reasonable=$(count_reasonable_pockets "$conservative_out")
      log "fpocket mode comparison written to $FPOCKET_COMPARISON"
      log "${selected_label}: $modified_total total pockets, $modified_reasonable reasonable pockets"
      log "Conservative mode: $conservative_total total pockets, $conservative_reasonable reasonable pockets"

      if feedback_at_least_guided; then
        echo
        echo "fpocket mode comparison:"
        awk -F '\t' 'NR==1 {next} {printf "  %s  %s  score=%s  alpha_spheres=%s  bbox=%sx%sx%s A  reasonable=%s  warning=%s\n", $1,$2,$3,$4,$5,$6,$7,$9,$10}' "$FPOCKET_COMPARISON"
        echo
        echo "Guidance: expanded/permissive fpocket modes are not guaranteed to produce more unique pockets."
        echo "They can merge a broad cleft/surface into one high-score pocket."
        echo "This script uses the run with more reasonable localized pockets."
        echo
      fi

      IFS=$'\t' read -r FP_OUT SELECTED_FP_RUN_LABEL < <(
        select_fpocket_comparison_run "$modified_out" "$conservative_out" "$selected_label"
      )
      if [ "$SELECTED_FP_RUN_LABEL" = conservative ]; then
        log "Using conservative fpocket output because it produced more reasonable localized pockets."
      else
        log "Using ${selected_label} fpocket output."
      fi
    else
      log "Running fpocket (${selected_label}, -m ${selected_probe})..."
      run_fpocket_to_directory "$FPOCKET_BIN" "$FP_INPUT" "$selected_probe" "$FP_OUT"
      SELECTED_FP_RUN_LABEL="$selected_label"
      log "fpocket complete"
    fi
  else
    log "Running fpocket (conservative mode)..."
    run_fpocket_to_directory "$FPOCKET_BIN" "$FP_INPUT" '' "$FP_OUT"
    SELECTED_FP_RUN_LABEL=conservative
    log "fpocket complete"
  fi
  PQR="$FP_OUT/$(basename "$FP_INPUT" .pdb)_pockets.pqr"
}

# Normalize fpocket outputs and derive the ligand-overlap pocket when needed.
#
# Scientific intent: older/different fpocket builds may provide alpha spheres
# only in the combined PQR. Reconstructing per-pocket files is a format bridge,
# not a new cavity calculation. In ligand mode, the merged file contains only
# spheres passing the recorded ligand VDW and centroid-distance criteria.
# Required caller state: FP_OUT/PQR plus ligand and overlap settings.
# Published state: ATM_COUNT and, for ligand mode, MERGED/MERGED_COUNT.
# Protected by fpocket-runner and ligand-pocket-merge tests.
normalize_fpocket_outputs() {
  local pqr_lines pqr_atoms
  echo "Checking PQR: $PQR"
  ATM_COUNT=$(ls "$FP_OUT"/pockets/pocket*_atm.pdb 2>/dev/null | wc -l)
  echo "Pocket atm files found: $ATM_COUNT"
  if [ "$ATM_COUNT" -eq 0 ] && [ -f "$PQR" ]; then
    pqr_lines=$(wc -l < "$PQR")
    echo "No pocket atm files found - extracting from PQR ($pqr_lines lines)..."
    mkdir -p "$FP_OUT/pockets"
    awk -v dir="$FP_OUT/pockets" '
      /^ATOM|^HETATM/ {
        pnum=$5
        fname = dir "/pocket" pnum "_atm.pdb"
        print >> fname
      }
    ' "$PQR"
    ATM_COUNT=$(ls "$FP_OUT"/pockets/pocket*_atm.pdb 2>/dev/null | wc -l)
    echo "Extracted $ATM_COUNT pockets from PQR"
  elif [ ! -f "$PQR" ]; then
    echo "WARNING: PQR file not found at $PQR"
  fi

  if [ "$LIG_PRESENT" -eq 1 ] && [ -f "$PQR" ]; then
    pqr_atoms=$(awk '/^ATOM|^HETATM/{n++} END{print n+0}' "$PQR")
    echo "PQR total alpha spheres (local binding site): $pqr_atoms"
    log "Selecting alpha spheres overlapping ligand VDW volume..."
    MERGED="$FP_OUT/pockets/pocket_ligand_merged_atm.pdb"
    merge_ligand_overlapping_spheres "$INPUT_PDB" "$LIG" "$PQR" \
      "$MERGED_MAX_CENTROID_DIST" "$LIGAND_OVERLAP_MARGIN" "$MERGED"
    MERGED_COUNT=$(awk '/^ATOM/{n++} END{print n+0}' "$MERGED")
    log "Direct VDW overlap: $MERGED_COUNT alpha spheres selected -> $MERGED"
  fi
}

write_fpocket_run_summary() {
  local label="$1"
  local outdir="$2"
  local outfile="$3"
  local atm base score atoms bbx bby bbz max_bbox warning reasonable

  if [ ! -s "$outfile" ]; then
    printf "run_label\tpocket_file\tscore\talpha_spheres\tbbox_x\tbbox_y\tbbox_z\tmax_bbox\treasonable\twarning\n" >> "$outfile"
  fi

  for atm in "$outdir"/pockets/pocket*_atm.pdb; do
    [ -e "$atm" ] || continue
    base="$(basename "$atm")"
    score=$(awk -F':' '/Pocket Score/ {gsub(/ /,"",$2); print $2; exit}' "$atm")
    [ -n "$score" ] || score="NA"
    atoms=$(awk '/^(ATOM|HETATM)/ {n++} END{print n+0}' "$atm")
    read bbx bby bbz max_bbox <<< $(awk '
      /^(ATOM|HETATM)/ {
        x=substr($0,31,8)+0; y=substr($0,39,8)+0; z=substr($0,47,8)+0
        if (n==0 || x<minx) minx=x; if (n==0 || x>maxx) maxx=x
        if (n==0 || y<miny) miny=y; if (n==0 || y>maxy) maxy=y
        if (n==0 || z<minz) minz=z; if (n==0 || z>maxz) maxz=z
        n++
      }
      END {
        if (n==0) { printf "0.000 0.000 0.000 0.000"; exit }
        bx=maxx-minx; by=maxy-miny; bz=maxz-minz; m=bx
        if (by>m) m=by; if (bz>m) m=bz
        printf "%.3f %.3f %.3f %.3f", bx, by, bz, m
      }
    ' "$atm")

    warning="ok"
    if awk -v a="$atoms" -v lim="$POCKET_WARN_ATOMS" 'BEGIN{exit !(a>lim)}'; then
      warning="large_alpha_sphere_count"
    fi
    if awk -v b="$max_bbox" -v lim="$POCKET_WARN_BBOX" 'BEGIN{exit !(b>lim)}'; then
      if [ "$warning" = "ok" ]; then warning="large_spatial_extent"; else warning="${warning};large_spatial_extent"; fi
    fi

    reasonable="no"
    if [ "$score" != "NA" ] && \
       awk -v s="$score" -v t="$SCORE_THRESHOLD" 'BEGIN{exit !(s>=t)}' && \
       awk -v a="$atoms" -v lim="$POCKET_WARN_ATOMS" 'BEGIN{exit !(a<=lim)}' && \
       awk -v b="$max_bbox" -v lim="$POCKET_WARN_BBOX" 'BEGIN{exit !(b<=lim)}'; then
      reasonable="yes"
    fi

    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
      "$label" "$base" "$score" "$atoms" "$bbx" "$bby" "$bbz" "$max_bbox" "$reasonable" "$warning" >> "$outfile"
  done
}

# Compare a requested expanded/permissive fpocket run with the conservative
# reference. Expanded settings can merge broad surface clefts, so conservative
# replaces the requested run only when it yields more score-eligible,
# geometrically localized candidates. A tie preserves the requested mode.
# Inputs: modified directory, conservative directory, modified provenance label.
# Output: selected directory and provenance label separated by one tab.
select_fpocket_comparison_run() {
  local modified_out="$1"
  local conservative_out="$2"
  local modified_label="$3"
  local modified_reasonable conservative_reasonable

  modified_reasonable=$(count_reasonable_pockets "$modified_out")
  conservative_reasonable=$(count_reasonable_pockets "$conservative_out")
  if awk -v c="$conservative_reasonable" -v m="$modified_reasonable" 'BEGIN{exit !(c>m)}'; then
    printf '%s\t%s\n' "$conservative_out" conservative
  else
    printf '%s\t%s\n' "$modified_out" "$modified_label"
  fi
}

# Construct the ligand-local cavity used for a ligand-guided docking box.
# Retain alpha spheres overlapping the selected ligand's van der Waals volume
# while excluding distant spheres that can create unrelated "ghost" cavity
# extensions. This defines cavity geometry; it does not score or dock a ligand.
# Inputs: PDB, ligand residue name, fpocket PQR, centroid limit (A or OFF),
# overlap margin (A), and destination PDB. A filter audit is written to stderr.
merge_ligand_overlapping_spheres() {
  local input_pdb="$1"
  local ligand_resname="$2"
  local pqr_file="$3"
  local max_centroid_dist="$4"
  local overlap_margin="$5"
  local output_pdb="$6"

  awk -v lig="$ligand_resname" -v max_centroid_dist="$max_centroid_dist" -v overlap_margin="$overlap_margin" '
    BEGIN { nl=0; na=0 }
    function vdw(name,    el) {
      el=substr(name,1,1)
      if (el == "C") return 1.70
      if (el == "N") return 1.55
      if (el == "O") return 1.52
      if (el == "S") return 1.80
      if (el == "P") return 1.80
      if (el == "F") return 1.47
      if (el == "H") return 1.20
      return 1.70
    }
    FNR == NR {
      if (/^HETATM/) {
        res=substr($0,18,3); gsub(/ /,"",res)
        if (res == lig) {
          lx[nl]=substr($0,31,8)+0; ly[nl]=substr($0,39,8)+0; lz[nl]=substr($0,47,8)+0
          aname=substr($0,13,4); gsub(/ /,"",aname); lr[nl]=vdw(aname); nl++
        }
      }
      next
    }
    /^ATOM|^HETATM/ { ax[na]=$6+0; ay[na]=$7+0; az[na]=$8+0; ar[na]=$10+0; na++ }
    END {
      if (nl == 0) {
        print "ERROR: no ligand atoms were collected for ligand " lig > "/dev/stderr"
        exit 2
      }
      cx=0; cy=0; cz=0
      for (j=0; j<nl; j++) { cx+=lx[j]; cy+=ly[j]; cz+=lz[j] }
      cx/=nl; cy/=nl; cz/=nl
      n=0; skipped_centroid=0
      for (i=0; i<na; i++) {
        dx0=ax[i]-cx; dy0=ay[i]-cy; dz0=az[i]-cz
        if (max_centroid_dist != "OFF" && sqrt(dx0*dx0+dy0*dy0+dz0*dz0) > max_centroid_dist) {
          skipped_centroid++; continue
        }
        for (j=0; j<nl; j++) {
          dx=ax[i]-lx[j]; dy=ay[i]-ly[j]; dz=az[i]-lz[j]
          d=sqrt(dx*dx+dy*dy+dz*dz)
          if (d < (ar[i] + lr[j] + overlap_margin)) {
            n++
            printf "%-6s%5d  %-3s %3s %1s%4d    %8.3f%8.3f%8.3f\n", "ATOM", n, "C", "STP", "A", 1, ax[i], ay[i], az[i]
            break
          }
        }
      }
      if (max_centroid_dist == "OFF")
        printf "%d alpha spheres overlapping ligand VDW volume (margin %.2f A; centroid filter OFF; skipped %d distant spheres)\n", n, overlap_margin, skipped_centroid > "/dev/stderr"
      else
        printf "%d alpha spheres overlapping ligand VDW volume (margin %.2f A; centroid filter %.2f A; skipped %d distant spheres)\n", n, overlap_margin, max_centroid_dist, skipped_centroid > "/dev/stderr"
    }
  ' "$input_pdb" "$pqr_file" > "$output_pdb"
}

# Freeze fpocket candidates and classify their eligibility for docking-box
# selection. Every candidate receives an explicit accept/reject reason so a
# user can audit whether score, missing metadata, or excessive geometry caused
# its exclusion. Broad-pocket rejection is controlled explicitly and never
# inferred from visualization alone.
# Inputs: fpocket output directory, frozen-candidate directory, diagnostics
# path, score threshold, atom-count warning limit, bbox warning limit, and
# strict-local-pockets flag (0/1). Outputs: eligible.list, eligible_all.list,
# copied score-bearing pocket files, and a tab-separated diagnostic record.
classify_fpocket_candidates() {
  local fp_out="$1"
  local frozen_dir="$2"
  local diagnostic_file="$3"
  local score_threshold="$4"
  local warn_atoms="$5"
  local warn_bbox="$6"
  local strict_local="$7"
  local atm base score atoms bbx bby bbz max_bbox warning

  mkdir -p "$frozen_dir"
  : > "$frozen_dir/eligible.list"
  : > "$frozen_dir/eligible_all.list"
  printf 'pocket_file\tscore\talpha_spheres\tbbox_x\tbbox_y\tbbox_z\tmax_bbox\teligible\tskip_reason\twarning\n' > "$diagnostic_file"

  for atm in "$fp_out"/pockets/pocket*_atm.pdb; do
    [ -e "$atm" ] || continue
    base=$(basename "$atm")
    score=$(awk -F':' '/Pocket Score/ {gsub(/ /,"",$2); print $2; exit}' "$atm")
    atoms=$(awk '/^(ATOM|HETATM)/ {n++} END{print n+0}' "$atm")
    read -r bbx bby bbz max_bbox <<< "$(awk '
      /^(ATOM|HETATM)/ {
        x=substr($0,31,8)+0; y=substr($0,39,8)+0; z=substr($0,47,8)+0
        if (n==0 || x<minx) minx=x; if (n==0 || x>maxx) maxx=x
        if (n==0 || y<miny) miny=y; if (n==0 || y>maxy) maxy=y
        if (n==0 || z<minz) minz=z; if (n==0 || z>maxz) maxz=z
        n++
      }
      END {
        if (n==0) { printf "0.000 0.000 0.000 0.000"; exit }
        bx=maxx-minx; by=maxy-miny; bz=maxz-minz; m=bx
        if (by>m) m=by; if (bz>m) m=bz
        printf "%.3f %.3f %.3f %.3f", bx, by, bz, m
      }
    ' "$atm")"

    warning=ok
    if awk -v a="$atoms" -v lim="$warn_atoms" 'BEGIN{exit !(a>lim)}'; then warning=large_alpha_sphere_count; fi
    if awk -v b="$max_bbox" -v lim="$warn_bbox" 'BEGIN{exit !(b>lim)}'; then
      if [ "$warning" = ok ]; then warning=large_spatial_extent; else warning="${warning};large_spatial_extent"; fi
    fi

    if [ -z "$score" ]; then
      printf '%s\tNA\t%s\t%s\t%s\t%s\t%s\tno\tmissing_pocket_score\t%s\n' \
        "$base" "$atoms" "$bbx" "$bby" "$bbz" "$max_bbox" "$warning" >> "$diagnostic_file"
      continue
    fi

    cp "$atm" "$frozen_dir/$base"
    printf '%s\n' "$frozen_dir/$base" >> "$frozen_dir/eligible_all.list"
    if awk -v s="$score" -v t="$score_threshold" 'BEGIN{exit !(s>=t)}'; then
      if [ "$strict_local" = 1 ] && [ "$warning" != ok ]; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\tno\tgeometry_too_large\t%s\n' \
          "$base" "$score" "$atoms" "$bbx" "$bby" "$bbz" "$max_bbox" "$warning" >> "$diagnostic_file"
      else
        printf '%s\n' "$frozen_dir/$base" >> "$frozen_dir/eligible.list"
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\tyes\tpasses_score_and_geometry_filters\t%s\n' \
          "$base" "$score" "$atoms" "$bbx" "$bby" "$bbz" "$max_bbox" "$warning" >> "$diagnostic_file"
      fi
    else
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\tno\tscore_below_threshold\t%s\n' \
        "$base" "$score" "$atoms" "$bbx" "$bby" "$bbz" "$max_bbox" "$warning" >> "$diagnostic_file"
    fi
  done
}

# Rank ligand-free pocket candidates and suppress redundant docking boxes.
# The scientific ranking combines fpocket score with an exponential distance
# penalty from the selected protein centroid. Box overlap is then used only to
# avoid retaining substantially duplicate search regions; it does not alter
# the underlying fpocket score. Every ranked candidate remains in the audit,
# including candidates skipped after the requested maximum is reached.
# Inputs: eligible-list path, center mode (centroid/deepest), protein centroid,
# maximum retained pockets, box half-width, maximum overlap fraction,
# selected-record output, and diagnostic TSV output.
# Output records use the workflow's stable 0|PDB|X|Y|Z|SCORE representation.
select_ranked_fpocket_candidates() {
  local eligible_list="$1" center_mode="$2" prot_x="$3" prot_y="$4" prot_z="$5"
  local max_pockets="$6" half_box="$7" max_overlap="$8" selected_file="$9" diagnostic_file="${10}"
  local work_records="${diagnostic_file}.records" geom score cx cy cz rank rec order selected_count skip skip_reason observed overlap line
  local selected_centers="${diagnostic_file}.centers"

  : > "$work_records"
  : > "$selected_file"
  : > "$selected_centers"
  while IFS= read -r geom; do
    [ -n "$geom" ] || continue
    score=$(awk -F':' '/Pocket Score/ {gsub(/ /,"",$2); print $2; exit}' "$geom")
    [ -n "$score" ] || continue
    if [ "$center_mode" = centroid ]; then
      read -r cx cy cz <<< "$(awk '
        /^ATOM/ { x+=substr($0,31,8); y+=substr($0,39,8); z+=substr($0,47,8); n++; px[n]=substr($0,31,8); py[n]=substr($0,39,8); pz[n]=substr($0,47,8) }
        END { cx=x/n; cy=y/n; cz=z/n; mind=1e9; for(i=1;i<=n;i++){ dx=px[i]-cx;dy=py[i]-cy;dz=pz[i]-cz;d=dx*dx+dy*dy+dz*dz;if(d<mind){mind=d;bx=px[i];by=py[i];bz=pz[i]}}; printf "%.6f %.6f %.6f",bx,by,bz }
      ' "$geom")"
    else
      read -r cx cy cz <<< "$(awk '/^ATOM/{x=substr($0,31,8);y=substr($0,39,8);z=substr($0,47,8);if(!seen || $11>m){seen=1;m=$11;bx=x;by=y;bz=z}} END{printf "%.6f %.6f %.6f",bx,by,bz}' "$geom")"
    fi
    rank=$(awk -v s="$score" -v x="$cx" -v y="$cy" -v z="$cz" -v px="$prot_x" -v py="$prot_y" -v pz="$prot_z" 'BEGIN{d=sqrt((x-px)^2+(y-py)^2+(z-pz)^2);printf "%.6f",s*exp(-d/10)}')
    printf '%s|%s|%s|%s|%s|%s\n' "$rank" "$geom" "$cx" "$cy" "$cz" "$score" >> "$work_records"
  done < "$eligible_list"

  printf 'rank_order\tpocket_file\tscore\trank_score\tcenter_x\tcenter_y\tcenter_z\tdecision\treason\tmax_overlap\n' > "$diagnostic_file"
  order=0; selected_count=0
  while IFS= read -r rec; do
    [ -n "$rec" ] || continue
    order=$((order+1)); IFS='|' read -r rank geom cx cy cz score <<< "$rec"
    if [ "$selected_count" -ge "$max_pockets" ]; then
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\tskipped\tnot_retained_after_max_pockets\tNA\n' "$order" "$(basename "$geom")" "$score" "$rank" "$cx" "$cy" "$cz" >> "$diagnostic_file"
      continue
    fi
    skip=0; skip_reason=selected; observed=0
    while IFS='|' read -r _ sx sy sz; do
      [ -n "${sx:-}" ] || continue
      overlap=$(awk -v x1="$cx" -v y1="$cy" -v z1="$cz" -v x2="$sx" -v y2="$sy" -v z2="$sz" -v h="$half_box" 'BEGIN{ox=h*2-(x1>x2?x1-x2:x2-x1);oy=h*2-(y1>y2?y1-y2:y2-y1);oz=h*2-(z1>z2?z1-z2:z2-z1);if(ox<=0||oy<=0||oz<=0){print 0;exit};print (ox*oy*oz)/((h*2)^3)}')
      if awk -v o="$overlap" -v m="$observed" 'BEGIN{exit !(o>m)}'; then observed="$overlap"; fi
      if awk -v o="$overlap" -v m="$max_overlap" 'BEGIN{exit !(o>m)}'; then skip=1; skip_reason=box_overlap_exceeds_MAX_OVERLAP_FRAC; break; fi
    done < "$selected_centers"
    if [ "$skip" -eq 0 ]; then
      printf '0|%s|%s|%s|%s|%s\n' "$geom" "$cx" "$cy" "$cz" "$score" >> "$selected_file"
      printf '%s|%s|%s|%s\n' "$selected_count" "$cx" "$cy" "$cz" >> "$selected_centers"
      selected_count=$((selected_count+1))
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\tselected\tselected\t%s\n' "$order" "$(basename "$geom")" "$score" "$rank" "$cx" "$cy" "$cz" "$observed" >> "$diagnostic_file"
    else
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\tskipped\t%s\t%s\n' "$order" "$(basename "$geom")" "$score" "$rank" "$cx" "$cy" "$cz" "$skip_reason" "$observed" >> "$diagnostic_file"
    fi
  done < <(sort -t '|' -k1,1rn "$work_records")
  rm -f "$work_records" "$selected_centers"
}

# Materialize one selected search region as interoperable docking artifacts.
#
# Scientific intent: make the exact physical volume searched by the docking
# engine explicit and independently inspectable. The center marker identifies
# the chosen site, the eight connected box corners make its boundaries visible
# in molecular viewers, and the configuration file gives Vina the identical
# center and dimensions. This function does not modify receptor chemistry.
#
# Inputs: center-PDB path, box-PDB path, configuration path, timestamp, source
# PDB identifier/path, center XYZ, full cubic edge length, and half-edge length.
# Outputs: the three deterministic derived files described above.
# Audit invariant: coordinates and dimensions must agree across all files.
# Protected by: tests/test_docking_box_artifacts.sh.

# Assemble the optional cavity extension surrounding a selected core pocket.
#
# Scientific intent: expose nearby fpocket hypotheses for visual review without
# allowing them to influence the selected center, score, or docking box. A
# candidate is adjacent when at least one of its alpha spheres lies within the
# fixed touching distance of a core sphere. The extension is diagnostic only
# and is hidden unless the user explicitly enables adjacent-cavity rendering.
#
# Inputs: selected core-pocket PDB, directory containing frozen pocket PDBs,
# destination PDB, and touching distance in angstroms.
# Output: concatenated atoms from touching non-core pockets, possibly empty.
# Protected by: tests/test_adjacent_pocket_extension.sh.
build_adjacent_pocket_extension() {
  local core_geom="$1" frozen_dir="$2" output_pdb="$3" touch_distance="$4"
  local other touches
  : > "$output_pdb"
  for other in "$frozen_dir"/pocket*_atm.pdb; do
    [ -e "$other" ] || continue
    [ "$other" = "$core_geom" ] && continue
    touches=$(awk -v cutoff="$touch_distance" '
      FNR == NR {
        if (/^ATOM/) { cx[nc]=substr($0,31,8)+0; cy[nc]=substr($0,39,8)+0; cz[nc]=substr($0,47,8)+0; nc++ }
        next
      }
      /^ATOM/ {
        x=substr($0,31,8)+0; y=substr($0,39,8)+0; z=substr($0,47,8)+0
        for (i=0; i<nc; i++) {
          dx=x-cx[i]; dy=y-cy[i]; dz=z-cz[i]
          if (sqrt(dx*dx+dy*dy+dz*dz) < cutoff) { print "yes"; exit }
        }
      }
    ' "$core_geom" "$other")
    if [ "$touches" = yes ]; then
      awk '/^(ATOM|HETATM)/ {print}' "$other" >> "$output_pdb"
    fi
  done
}

# Write the PyMOL review scene for one already selected docking region.

# Build the receptor subset supplied to fpocket for ligand-guided site review.
#
# Scientific intent: focus cavity detection on protein atoms within a declared
# radius of the selected deposited ligand while retaining supported metal atoms
# as structural context. The ligand itself is not copied into the fpocket input
# and the prepared full receptor remains unchanged.
# Inputs: deposited PDB, prepared receptor PDB, ligand residue name, cutoff in
# angstroms, and destination PDB. Output: local receptor/metal subset.
# Protected by: tests/test_ligand_detection_helpers.sh.
write_ligand_local_fpocket_input() {
  local deposited_pdb="$1" receptor_pdb="$2" ligand="$3" cutoff="$4" output_pdb="$5"
  awk -v wanted="$ligand" -v radius="$cutoff" '
    BEGIN { nl=0 }
    FNR == NR {
      if (/^HETATM/) { r=substr($0,18,3);gsub(/ /,"",r);if(r==wanted){lx[nl]=substr($0,31,8)+0;ly[nl]=substr($0,39,8)+0;lz[nl]=substr($0,47,8)+0;nl++} }
      next
    }
    /^ATOM/ {
      x=substr($0,31,8)+0;y=substr($0,39,8)+0;z=substr($0,47,8)+0
      for(j=0;j<nl;j++){dx=x-lx[j];dy=y-ly[j];dz=z-lz[j];if(sqrt(dx*dx+dy*dy+dz*dz)<=radius){print;break}}
    }
    /^HETATM/ { r=substr($0,18,3);gsub(/ /,"",r);if(r~/^(ZN|MG|MN|CA|FE|CU)$/)print }
  ' "$deposited_pdb" "$receptor_pdb" > "$output_pdb"
}

# Run fpocket once and normalize its generated directory to an explicit path.
#
# Scientific intent: make the probe-radius mode and resulting artifact location
# explicit while leaving comparison/selection to separate tested functions.
# An empty probe value invokes fpocket's conservative default; any supplied
# value is passed through `-m` verbatim and is therefore visible to auditing.
# Inputs: fpocket executable, input PDB, probe value or empty, destination dir.
# Output: fpocket directory at the requested destination; tool status retained.
# Protected by: tests/test_fpocket_runner.sh.
run_fpocket_to_directory() {
  local executable="$1" input_pdb="$2" probe="$3" destination="$4"
  local natural="${input_pdb%.pdb}_out"
  rm -rf "$natural" "$destination"
  if [ -n "$probe" ]; then
    "$executable" -f "$input_pdb" -m "$probe" >/dev/null
  else
    "$executable" -f "$input_pdb" >/dev/null
  fi
  [ -d "$natural" ] || return 1
  if [ "$natural" != "$destination" ]; then mv "$natural" "$destination"; fi
}
