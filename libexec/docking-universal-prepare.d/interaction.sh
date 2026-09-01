#!/usr/bin/env bash

# Guided feedback, settings explanations, logging, and chain summaries.
# Sourced through docking-universal-prepare-support.sh; not executed directly.

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

print_parameter_guidance() {
  cat <<EOF

Parameter guidance for ligand-centered pocket merge:
  MERGED_MAX_CENTROID_DIST=$MERGED_MAX_CENTROID_DIST A
    Meaning: rejects fpocket alpha spheres farther than this from the ligand centroid.
    Use 8-10 A for small/compact ligands when ghost pockets appear.
    Use 12-15 A for elongated ligands, macrocycles, extended inhibitors, or known broad pockets.
    Use OFF to disable this centroid-distance filter.

  LIGAND_OVERLAP_MARGIN=$LIGAND_OVERLAP_MARGIN A
    Meaning: keeps alpha spheres when distance < alpha_radius + ligand_vdw_radius + margin.
    -0.5 A = stricter; good when cavity surfaces look bloated or include ghost pocket volume.
     0.0 A = neutral VDW contact; good default if the strict setting removes too much cavity.
    +0.5 to +1.0 A = permissive; useful when fpocket under-samples peripheral ligand regions.

  BOX_SIZE=$BOX_SIZE A
    Meaning: cubic Vina docking box edge length.
    22-26 A is typical for compact ligand-centered redocking.
    28-34 A may be needed for large ligands or induced-fit exploration, but increases search space.
EOF
}

print_settings_summary() {
  cat <<EOF

Settings:
  BOX_SIZE=$BOX_SIZE A
  MERGED_MAX_CENTROID_DIST=$MERGED_MAX_CENTROID_DIST A
  LIGAND_OVERLAP_MARGIN=$LIGAND_OVERLAP_MARGIN A
  SCORE_THRESHOLD=$SCORE_THRESHOLD
  SHOW_POCKET_SURFACE=$SHOW_POCKET_SURFACE
  POCKET_WARN_ATOMS=$POCKET_WARN_ATOMS
  POCKET_WARN_BBOX=$POCKET_WARN_BBOX A
  STRICT_LOCAL_POCKETS=$STRICT_LOCAL_POCKETS
  HYBRID_COMPARE_FP_MODE=$HYBRID_COMPARE_FP_MODE

EOF
}

choose_feedback_level() {
  # FEEDBACK_LEVEL can still be set by environment for unattended runs, but
  # default behavior is interactive because this script is used as a guided tool.
  case "${FEEDBACK_LEVEL:-ASK}" in
    concise|guided|verbose)
      return 0
      ;;
  esac

  echo
  echo "How much feedback do you want during this run?"
  echo "  1) Concise - minimal status and required prompts"
  echo "  2) Guided  - recommendations at decision points (recommended)"
  echo "  3) Verbose - full parameter guidance and diagnostics"
  read -r -p "Select feedback level [2]: " feedback_choice

  case "${feedback_choice:-2}" in
    1) FEEDBACK_LEVEL="concise" ;;
    2) FEEDBACK_LEVEL="guided" ;;
    3) FEEDBACK_LEVEL="verbose" ;;
    *)
      echo "Unrecognized choice; using guided feedback."
      FEEDBACK_LEVEL="guided"
      ;;
  esac
}

feedback_at_least_guided() {
  [ "$FEEDBACK_LEVEL" = "guided" ] || [ "$FEEDBACK_LEVEL" = "verbose" ]
}

feedback_verbose() {
  [ "$FEEDBACK_LEVEL" = "verbose" ]
}

summarize_chains() {
  local pdb="$1"
  local out="$2"
  awk '
    /^ATOM/ {
      ch=substr($0,22,1); if (ch==" ") ch="_"
      resseq=substr($0,23,4); gsub(/ /,"",resseq)
      icode=substr($0,27,1); gsub(/ /,"",icode)
      resname=substr($0,18,3); gsub(/ /,"",resname)
      key=ch":"resseq":"icode":"resname
      if (!(key in seen)) { seen[key]=1; residues[ch]++ }
      atoms[ch]++
    }
    END {
      for (ch in atoms) {
        printf "%s\t%d\t%d\n", ch, residues[ch]+0, atoms[ch]+0
      }
    }
  ' "$pdb" | sort > "$out"
}

print_chain_guidance() {
  local summary="$1"
  local n_chains
  n_chains=$(awk 'END{print NR+0}' "$summary")
  echo
  echo "Protein chain summary from prepared receptor:"
  awk -F '	' '{printf "  Chain %s: %d residues, %d atoms\n", $1, $2, $3}' "$summary"
  echo
  if [ "$n_chains" -gt 1 ]; then
    echo "Guidance: multiple chains detected. Per-chain centroid is usually safer for cavity ranking,"
    echo "especially for oligomers or asymmetric complexes, because whole-protein centroid can point"
    echo "between chains and over-penalize real pockets on one chain."
    echo "Recommended centroid mode: 2) Per-chain."
  else
    echo "Guidance: one protein chain detected. Whole-protein centroid is usually fine."
    echo "Recommended centroid mode: 1) Whole protein."
  fi
}


