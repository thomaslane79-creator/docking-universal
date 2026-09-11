#!/usr/bin/env bash

# Runtime configuration, dependency resolution, and run-layout initialization.
# Sourced through docking-universal-prepare-support.sh; not executed directly.

# Load and validate the user-adjustable scientific and rendering defaults.
# These values are published as globals because subsequent workflow services
# share one recorded configuration. No files or molecular models are changed.
load_prepare_runtime_defaults() {
  BOX_SIZE="${BOX_SIZE:-26.0}"
  HALF_BOX="${HALF_BOX:-13.0}"
  SCORE_THRESHOLD="${SCORE_THRESHOLD:-0.10}"
  MAX_OVERLAP_FRAC="${MAX_OVERLAP_FRAC:-0.60}"
  MERGED_MAX_CENTROID_DIST="${MERGED_MAX_CENTROID_DIST:-10.0}"
  LIGAND_OVERLAP_MARGIN="${LIGAND_OVERLAP_MARGIN:--0.5}"
  SHOW_LIGAND_VOLUME="${SHOW_LIGAND_VOLUME:-0}"
  SHOW_REFERENCE_LIGANDS="${SHOW_REFERENCE_LIGANDS:-1}"
  SHOW_ADJACENT_CAVITY="${SHOW_ADJACENT_CAVITY:-0}"
  SHOW_POCKET_SURFACE="${SHOW_POCKET_SURFACE:-1}"
  POCKET_WARN_ATOMS="${POCKET_WARN_ATOMS:-500}"
  POCKET_WARN_BBOX="${POCKET_WARN_BBOX:-40.0}"
  STRICT_LOCAL_POCKETS="${STRICT_LOCAL_POCKETS:-1}"
  HYBRID_COMPARE_FP_MODE="${HYBRID_COMPARE_FP_MODE:-1}"
  SITE_MODE="${DOCKING_UNIVERSAL_SITE_MODE:-ask}"
  REQUESTED_LIGAND="${DOCKING_UNIVERSAL_LIGAND_RESNAME:-}"
  case "$SITE_MODE" in
    ask|ligand|pockets) ;;
    *) echo "ERROR: DOCKING_UNIVERSAL_SITE_MODE must be ask, ligand, or pockets" >&2; return 2 ;;
  esac
}

# Resolve the executable backends once and publish the selected preparation
# route. Explicit environment paths remain authoritative; automatic discovery
# only fills missing values. This checks availability, not scientific fitness.
resolve_prepare_runtime_tools() {
  FPOCKET_BIN="${DOCKING_UNIVERSAL_FPOCKET:-$(command -v fpocket 2>/dev/null || true)}"
  PREP_BACKEND="${DOCKING_UNIVERSAL_PREP_BACKEND:-auto}"
  PREP_RECEPTOR_BIN="${DOCKING_UNIVERSAL_PREP_RECEPTOR:-}"
  ADFR_FALLBACK_BIN="${DOCKING_UNIVERSAL_ADFR_FALLBACK_BIN:-$(command -v prepare_receptor 2>/dev/null || true)}"
  if [ -z "$ADFR_FALLBACK_BIN" ] && [ -x "$HOME/ADFRsuite-1.0/bin/prepare_receptor" ]; then
    ADFR_FALLBACK_BIN="$HOME/ADFRsuite-1.0/bin/prepare_receptor"
  fi
  ADFR_FALLBACK="${DOCKING_UNIVERSAL_ADFR_FALLBACK:-1}"

  case "$PREP_BACKEND" in
    auto)
      if [ -n "$PREP_RECEPTOR_BIN" ]; then
        case "$(basename "$PREP_RECEPTOR_BIN")" in
          mk_prepare_receptor.py) PREP_BACKEND=meeko ;;
          *) PREP_BACKEND=adfr ;;
        esac
      elif command -v mk_prepare_receptor.py >/dev/null 2>&1; then
        PREP_BACKEND=meeko
        PREP_RECEPTOR_BIN=$(command -v mk_prepare_receptor.py)
      else
        PREP_BACKEND=adfr
        PREP_RECEPTOR_BIN=$(command -v prepare_receptor 2>/dev/null || true)
      fi
      ;;
    meeko) [ -n "$PREP_RECEPTOR_BIN" ] || PREP_RECEPTOR_BIN=$(command -v mk_prepare_receptor.py 2>/dev/null || true) ;;
    adfr) [ -n "$PREP_RECEPTOR_BIN" ] || PREP_RECEPTOR_BIN=$(command -v prepare_receptor 2>/dev/null || true) ;;
    *) echo "ERROR: DOCKING_UNIVERSAL_PREP_BACKEND must be auto, meeko, or adfr" >&2; return 2 ;;
  esac
  [ -n "$FPOCKET_BIN" ] && [ -x "$FPOCKET_BIN" ] || { echo "ERROR: fpocket not found (run 'docking-universal doctor')" >&2; return 1; }
  [ -n "$PREP_RECEPTOR_BIN" ] && [ -x "$PREP_RECEPTOR_BIN" ] || { echo "ERROR: receptor preparation backend not found (install Meeko or configure ADFRsuite)" >&2; return 1; }
  case "$ADFR_FALLBACK" in
    0|1) ;;
    *) echo "ERROR: DOCKING_UNIVERSAL_ADFR_FALLBACK must be 0 or 1" >&2; return 2 ;;
  esac
}

# Create the deterministic run layout and begin timestamped logging. The
# canonical name is derived only from the input filename; scientific identity
# remains recorded separately in downstream manifests and reports.
initialize_prepare_run_layout() {
  local raw base pdb_id
  TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
  raw="$(basename "$INPUT_PDB" .pdb)"
  base="$(echo "$raw" | sed 's/([^)]*)//g; s/[^A-Za-z0-9]/_/g; s/_\+/_/g')"
  pdb_id="$(echo "$raw" | sed -n 's/.*(\([A-Za-z0-9]\{4\}\)).*/\1/p')"
  CANONICAL="${base}${pdb_id:+_$pdb_id}"
  ROOT="${CANONICAL}_receptor_prep"
  RECEPTOR_DIR="$ROOT/receptor"
  CAVITY_DIR="$ROOT/cavity"
  FROZEN_DIR="$CAVITY_DIR/frozen_pockets"
  mkdir -p "$RECEPTOR_DIR" "$CAVITY_DIR" "$FROZEN_DIR"
  RUN_LOG="$ROOT/run.log"
  FPOCKET_COMPARISON="$CAVITY_DIR/fpocket_mode_comparison.tsv"
  POCKET_DIAG="$CAVITY_DIR/pocket_diagnostics.tsv"
  SELECTION_DIAG="$CAVITY_DIR/pocket_selection_diagnostics.tsv"
  SELECTED_FP_RUN_LABEL=not_set
  : > "$RUN_LOG"
  case "${DOCKING_UNIVERSAL_LOG_MODE:-tee}" in
    tee) exec > >(tee -a "$RUN_LOG") 2>&1 ;;
    file) exec >> "$RUN_LOG" 2>&1 ;;
    *) echo "ERROR: DOCKING_UNIVERSAL_LOG_MODE must be tee or file" >&2; return 2 ;;
  esac
}
