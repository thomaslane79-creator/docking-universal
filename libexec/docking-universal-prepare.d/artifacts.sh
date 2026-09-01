#!/usr/bin/env bash

# Docking-box, PyMOL review, and preparation-summary artifact rendering.
# Sourced through docking-universal-prepare-support.sh; not executed directly.

write_docking_box_artifacts() {
  local center_file="$1" box_file="$2" config_file="$3" timestamp="$4" input_pdb="$5"
  local cx="$6" cy="$7" cz="$8" box_size="$9" half_box="${10}"
  local n=1 dx dy dz x y z

  printf '%-6s%5d %-4s %-3s %1s%4d    %8.3f%8.3f%8.3f\n' \
    HETATM 1 CTR CTR A 1 "$cx" "$cy" "$cz" > "$center_file"

  printf 'REMARK BOX\n' > "$box_file"
  for dx in -1 1; do
    for dy in -1 1; do
      for dz in -1 1; do
        x=$(awk -v c="$cx" -v d="$dx" -v h="$half_box" 'BEGIN{printf "%.3f",c+d*h}')
        y=$(awk -v c="$cy" -v d="$dy" -v h="$half_box" 'BEGIN{printf "%.3f",c+d*h}')
        z=$(awk -v c="$cz" -v d="$dz" -v h="$half_box" 'BEGIN{printf "%.3f",c+d*h}')
        printf '%-6s%5d %-4s %-3s %1s%4d    %8.3f%8.3f%8.3f\n' ATOM "$n" X BOX A 1 "$x" "$y" "$z" >> "$box_file"
        n=$((n+1))
      done
    done
  done
  cat >> "$box_file" <<'EOF'
CONECT    1    2    3    5
CONECT    2    1    4    6
CONECT    3    1    4    7
CONECT    4    2    3    8
CONECT    5    1    6    7
CONECT    6    2    5    8
CONECT    7    3    5    8
CONECT    8    4    6    7
END
EOF

  cat > "$config_file" <<EOF
# Generated: $timestamp
# Input: $input_pdb
center_x = $cx
center_y = $cy
center_z = $cz
size_x = $box_size
size_y = $box_size
size_z = $box_size
EOF
}


#
# Scientific intent: let a user visually verify the receptor, selected cavity,
# center, and docking-box boundaries without changing any selection result.
# Selected pocket identity and fpocket score are labeled explicitly. Detected
# ligands are optional, disabled reference objects in pocket mode; they never
# influence ranking. Optional cavity extensions and ligand volume are displayed
# only when their independently recorded switches are enabled.
#
# Inputs: output/provenance paths, stable pocket identity, precomputed cavity
# files, visualization switches, selected ligand, score, then zero or more
# reference-ligand residue names. Output: a plain-text PML command file.
# This function performs presentation only and does not modify molecular data.
# Protected by: tests/test_pymol_review_scene.sh.
write_pymol_review_scene() {
  local pml="$1" timestamp="$2" input_pdb="$3" cavity_dir="$4" receptor_pdb="$5"
  local canonical="$6" index="$7" center_file="$8" box_file="$9" ligand_present="${10}"
  local geom="${11}" adjacent_pdb="${12}" show_surface="${13}" show_adjacent="${14}"
  local ligand_dir="${15}" selected_ligand="${16}" show_ligand_volume="${17}"
  local show_references="${18}" score="${19}" merged_pocket="${20}"
  shift 20
  local reference_ligands=("$@") ref_lig ref_obj
  local abs_cavity abs_receptor abs_center abs_box
  abs_cavity=$(cd "$cavity_dir" && pwd)
  abs_receptor=$(cd "$(dirname "$receptor_pdb")" && pwd)/$(basename "$receptor_pdb")
  abs_center=$(cd "$(dirname "$center_file")" && pwd)/$(basename "$center_file")
  abs_box=$(cd "$(dirname "$box_file")" && pwd)/$(basename "$box_file")

  {
    echo "# Generated: $timestamp"
    echo "# Input: $input_pdb"
    echo "cd $abs_cavity"
    echo "load $abs_receptor, $canonical"
    echo "set transparency_mode, 1"
    echo "hide everything, all"
    echo "hide everything, $canonical"
    echo "show cartoon, $canonical"
    echo "load $abs_center, ${canonical}_center${index}"

    if [ "$ligand_present" -eq 1 ]; then
      echo "load $merged_pocket, cavity_pocket${index}"
      echo "hide everything, cavity_pocket${index}"
      if [ "$show_surface" = 1 ]; then
        echo "show surface, cavity_pocket${index}"
        echo "set transparency, 0.45, cavity_pocket${index}"
      else
        echo "show spheres, cavity_pocket${index}"
        echo "set sphere_scale, 0.25, cavity_pocket${index}"
      fi
      echo "color cyan, cavity_pocket${index}"
      if [ "$show_ligand_volume" = 1 ]; then
        echo "load $(cd "$ligand_dir" && pwd)/${selected_ligand}.pdb, cavity_ligand${index}"
        echo "hide everything, cavity_ligand${index}"
        echo "show surface, cavity_ligand${index}"
        echo "set transparency, 0.1, cavity_ligand${index}"
        echo "color teal, cavity_ligand${index}"
      fi
    else
      echo "load $(cd "$(dirname "$geom")" && pwd)/$(basename "$geom"), cavity_core${index}"
      echo "hide everything, cavity_core${index}"
      if [ "$show_surface" = 1 ]; then
        echo "show surface, cavity_core${index}"
        echo "set transparency, 0.45, cavity_core${index}"
      else
        echo "show spheres, cavity_core${index}"
        echo "set sphere_scale, 0.25, cavity_core${index}"
      fi
      echo "color teal, cavity_core${index}"
      if [ "$show_adjacent" = 1 ] && [ -s "$adjacent_pdb" ]; then
        echo "load $(cd "$(dirname "$adjacent_pdb")" && pwd)/$(basename "$adjacent_pdb"), cavity_ext${index}"
        echo "hide everything, cavity_ext${index}"
        echo "show spheres, cavity_ext${index}"
        echo "set sphere_scale, 0.25, cavity_ext${index}"
        echo "set transparency, 0.3, cavity_ext${index}"
        echo "color cyan, cavity_ext${index}"
      fi
    fi

    echo "show spheres, ${canonical}_center${index}"
    echo "color yellow, ${canonical}_center${index}"
    echo "set sphere_scale, 0.7, ${canonical}_center${index}"
    echo "label ${canonical}_center${index}, \"Pocket ${index} | fpocket ${score}\""
    echo "set label_size, 18, ${canonical}_center${index}"
    echo "set label_color, white, ${canonical}_center${index}"
    echo "set label_outline_color, black, ${canonical}_center${index}"
    echo "set label_position, [0.0, 0.0, 2.5], ${canonical}_center${index}"
    echo "load $abs_box, ${canonical}_box${index}"
    echo "show sticks, ${canonical}_box${index}"
    echo "set stick_radius, 0.18, ${canonical}_box${index}"
    echo "color gray70, ${canonical}_box${index}"

    if [ "$show_references" = 1 ] && [ "${#reference_ligands[@]}" -gt 0 ]; then
      for ref_lig in "${reference_ligands[@]}"; do
        [ -n "$ref_lig" ] || continue
        ref_obj="${canonical}_${ref_lig}_reference"
        echo "load $(cd "$ligand_dir" && pwd)/${ref_lig}.pdb, $ref_obj"
        echo "hide everything, $ref_obj"
        echo "show sticks, $ref_obj"
        echo "util.cbag $ref_obj"
        echo "disable $ref_obj"
      done
    fi
    echo "zoom $canonical"
    echo "orient $canonical"
  } > "$pml"
}

# Render the human-readable preparation summary from completed workflow state.
#
# Scientific intent: expose the assumptions, thresholds, selected geometry,
# preparation route, warnings, and retained evidence needed to review or
# reproduce receptor preparation. This function is deliberately a renderer:
# it consumes decisions already made by tested workflow functions and must not
# select pockets, change coordinates, or modify receptor chemistry.
#
# Input: destination summary path plus the named workflow variables documented
# in the generated report. Output: plain-text audit guide and artifact index.
# Protected by the artifact inventory assertions in
# tests/test_receptor_preparation_routes.sh.
write_preparation_summary() {
  local output_file="$1"
  cat > "$output_file" <<EOF
###############################################################################
Docking Preparation Summary
Generated: $TIMESTAMP
Script version: $SCRIPT_VERSION
Feedback level: $FEEDBACK_LEVEL
Run log: $RUN_LOG
###############################################################################

Input structure:
$INPUT_PDB

Canonical name:
$CANONICAL

###############################################################################
Receptor Preparation
###############################################################################

Receptor PDB:
$RECEPTOR_PDB

Receptor PDBQT:
$RECEPTOR_PDBQT

Protein centroid (A):
$PROT_CX  $PROT_CY  $PROT_CZ

Centroid computed from:
$([ "$CENTROID_SEL" = "2" ] && echo "Largest chain" || echo "Whole protein")

Ligand directory:
$LIGAND_DIR

Detected ligands are written here before the ligand-centered docking prompt.
If you choose non-ligand pocket discovery, these ligand PDBs are still loaded
as hidden atom-colored reference stick objects in PyMOL when SHOW_REFERENCE_LIGANDS=1. They do not affect
pocket ranking or docking-box generation unless ligand-centered mode is chosen.

Detected ligand manifest:
$LIGAND_DIR/detected_ligands.tsv

$([ "$LIG_PRESENT" -eq 1 ] && echo "Ligand used for docking center:
$LIG

Ligand centroid (A):
$LIGX  $LIGY  $LIGZ

Best overlapping fpocket pocket:
$(basename "$BEST_GEOM") (alpha sphere atoms within 6A of ligand centroid: $BEST_OVL)")

###############################################################################
Ligand-Mode Merge Settings
###############################################################################

Merged alpha-sphere centroid distance filter (A):
$MERGED_MAX_CENTROID_DIST

Ligand/alpha-sphere overlap margin (A):
$LIGAND_OVERLAP_MARGIN

Interpretation:
- Alpha spheres farther than MERGED_MAX_CENTROID_DIST from the ligand centroid are excluded.
- Overlap uses: distance < alpha_radius + ligand_vdw_radius + LIGAND_OVERLAP_MARGIN.
- The default negative margin tightens the cavity to alpha spheres that more directly overlap ligand VDW volume.

###############################################################################
Pocket Detection (fpocket)
###############################################################################

Mode:
$MODE

Score threshold:
$SCORE_THRESHOLD

All pockets passing threshold stored in:
$FROZEN_DIR

###############################################################################
Cavity Selection
###############################################################################

Number of cavities selected:
$MAX_POCKETS

Selection ordering:
Combined rank = fpocket score * exp(-distance_to_protein_centroid / 10)
Higher scores and more interior locations are favored; overlapping boxes are suppressed.

###############################################################################
Center Definition
###############################################################################

Selected mode:
$CENTER_MODE

deepest:
  - Uses fpocket alpha sphere with largest radius
  - Represents most open / accessible region
  - Often near pocket entrance or surface

centroid:
  - Uses geometric centroid of pocket alpha spheres
  - Snapped to nearest valid pocket coordinate
  - Represents interior binding region

###############################################################################
Box Definition
###############################################################################

Box size (A):
$BOX_SIZE

Half box size (A):
$HALF_BOX

Each pocket has:
  - *_center.pdb  -> center point
  - *_box.pdb     -> docking grid box
  - *.conf        -> Vina config file
  - *.pml         -> PyMOL visualization

###############################################################################
PyMOL Visualization
###############################################################################

Each PML file loads:
  - prepared receptor
  - specific pocket
  - corresponding docking box
  - center marker

View is oriented to full protein (not pocket center)

###############################################################################
Chain Summary / Centroid Guidance
###############################################################################

Chain summary file:
$CHAIN_SUMMARY

$(if [ -f "$CHAIN_SUMMARY" ]; then awk -F '	' '{printf "Chain %s: %d residues, %d atoms\n", $1, $2, $3}' "$CHAIN_SUMMARY"; fi)

Guidance:
- Use whole-protein centroid for single-chain compact receptors.
- Use per-chain centroid for multi-chain receptors or oligomers.
- If the selected cavity appears penalized because the protein centroid lies between chains,
  rerun with per-chain centroid mode.

###############################################################################
Parameter Guidance
###############################################################################

MERGED_MAX_CENTROID_DIST:
  Current value: $MERGED_MAX_CENTROID_DIST A
  8-10 A: stricter; useful for compact ligands and ghost-pocket suppression.
  12-15 A: looser; useful for elongated ligands or broad pockets.
  OFF: disables centroid-distance filtering.

SHOW_LIGAND_VOLUME:
  Current value: $SHOW_LIGAND_VOLUME
  0 = do not render a separate ligand molecular surface layer.
  1 = render ligand surface as an optional coverage check.

SHOW_REFERENCE_LIGANDS:
  Current value: $SHOW_REFERENCE_LIGANDS
  1 = load all detected ligands as hidden atom-colored stick objects in every PyMOL scene for optional visual checking.
  0 = do not load detected reference ligands unless ligand-centered mode explicitly uses one.

SHOW_ADJACENT_CAVITY:
  Current value: $SHOW_ADJACENT_CAVITY
  0 = do not render adjacent fpocket cavity extension by default.
  1 = render adjacent cavity extension as small cyan spheres for diagnostics.

LIGAND_OVERLAP_MARGIN:
  Current value: $LIGAND_OVERLAP_MARGIN A
  -0.5 A: stricter direct-overlap criterion.
   0.0 A: neutral VDW contact criterion.
  +0.5 to +1.0 A: more permissive for under-sampled ligand peripheries.

BOX_SIZE:
  Current value: $BOX_SIZE A
  22-26 A: compact ligand-centered redocking.
  28-34 A: larger ligands or exploratory/induced-fit search, at higher computational cost.


###############################################################################
Pocket Diagnostics
###############################################################################

Pocket diagnostics file:
$POCKET_DIAG

Pocket selection diagnostics file:
${SELECTION_DIAG:-not_applicable_in_ligand_mode}

SHOW_POCKET_SURFACE:
  Current value: $SHOW_POCKET_SURFACE
  0 = render fpocket alpha spheres as small spheres by default.
  1 = render fpocket alpha spheres as PyMOL surfaces. Use only after inspecting pocket diagnostics.

POCKET_WARN_ATOMS:
  Current value: $POCKET_WARN_ATOMS
  Pockets above this alpha-sphere count are flagged as broad/large.

POCKET_WARN_BBOX:
  Current value: $POCKET_WARN_BBOX A
  Pockets with any bounding-box dimension above this are flagged as spatially broad.

STRICT_LOCAL_POCKETS:
  Current value: $STRICT_LOCAL_POCKETS
  1 = exclude giant/spatially broad pockets from normal cavity selection.
  0 = allow them but keep warning labels in diagnostics.
  Recommended: 1 for normal docking-box generation; use 0 only for diagnostic review.

###############################################################################
Notes
###############################################################################

- Coordinates extracted using fixed-width PDB parsing (columns 31-54)
- Centroid mode avoids empty-space centers by snapping to real pocket atoms
- Box coordinates are written in strict PDB format to ensure correct rendering
- File naming preserves pocket ranking (pocket1, pocket2, ...)
- v1.34_patch and later integrate Copilot surgical fixes for ligand-mode cavity merge:
  ligand centroid filter, tighter VDW overlap, and PyMOL ghost-rendering cleanup.

###############################################################################
EOF
}

# Materialize the selected site records as matched Vina and PyMOL artifacts.
#
# Scientific intent: a selected geometric hypothesis is not complete until its
# numeric search volume and its visual review scene are generated from the same
# center. Ligand-guided studies publish exactly one site; pocket-guided studies
# publish no more than the user-requested maximum. Adjacent pockets remain
# visual context and never alter the chosen center or configuration.
#
# Required caller state: SORTED and LIGANDS arrays plus the preparation paths,
# rendering options, ligand state, box dimensions, and timestamps initialized
# by docking-universal-prepare. Output: one matched center PDB, box PDB, Vina
# configuration, and PyMOL scene per retained site.
# Protected by: tests/test_docking_box_artifacts.sh,
# tests/test_pymol_review_scene.sh, and tests/test_receptor_preparation_routes.sh.
materialize_selected_site_artifacts() {
  local index=1 record distance geometry center_x center_y center_z score
  local center_file box_file config_file scene_file adjacent_file merged_scene_pocket

  for record in "${SORTED[@]}"; do
    if [ "$LIG_PRESENT" -eq 1 ] && [ "$index" -gt 1 ]; then
      break
    fi
    if [ "$LIG_PRESENT" -eq 0 ] && [ "$index" -gt "$MAX_POCKETS" ]; then
      break
    fi

    IFS='|' read -r distance geometry center_x center_y center_z score <<< "$record"
    center_file="$CAVITY_DIR/${CANONICAL}_pocket${index}_center.pdb"
    box_file="$CAVITY_DIR/${CANONICAL}_pocket${index}_box.pdb"
    config_file="$CAVITY_DIR/${CANONICAL}_pocket${index}.conf"
    scene_file="$CAVITY_DIR/${CANONICAL}_pocket${index}.pml"

    write_docking_box_artifacts "$center_file" "$box_file" "$config_file" "$TIMESTAMP" \
      "$INPUT_PDB" "$center_x" "$center_y" "$center_z" "$BOX_SIZE" "$HALF_BOX"

    adjacent_file=""
    if [ "$LIG_PRESENT" -eq 0 ]; then
      adjacent_file="$FROZEN_DIR/adjacent_pocket${index}.pdb"
      build_adjacent_pocket_extension "$geometry" "$FROZEN_DIR" "$adjacent_file" 8.0
    fi
    merged_scene_pocket="$(cd "$CAVITY_DIR" && pwd)/fpocket_input_local_out/pockets/pocket_ligand_merged_atm.pdb"
    write_pymol_review_scene "$scene_file" "$TIMESTAMP" "$INPUT_PDB" "$CAVITY_DIR" \
      "$RECEPTOR_PDB" "$CANONICAL" "$index" "$center_file" "$box_file" "$LIG_PRESENT" \
      "$geometry" "$adjacent_file" "$SHOW_POCKET_SURFACE" "$SHOW_ADJACENT_CAVITY" \
      "$LIGAND_DIR" "${LIG:-}" "$SHOW_LIGAND_VOLUME" "$SHOW_REFERENCE_LIGANDS" \
      "$score" "$merged_scene_pocket" "${LIGANDS[@]}"

    echo "Selected cavity $index"
    index=$((index+1))
  done
}

# Emit the terminal audit index for a completed preparation run. This summary
# points to retained evidence and distinguishes an intentional zero-selection
# result from a failure before pocket analysis.
# Required caller state: selected fpocket label, diagnostic paths, ligand mode,
# and SORTED records. Protected by receptor-route characterization tests.
report_preparation_completion() {
  echo
  log "Diagnostics summary:"
  log "  Selected fpocket run: ${SELECTED_FP_RUN_LABEL}"
  if [ -f "$FPOCKET_COMPARISON" ]; then
    log "  fpocket mode comparison: $FPOCKET_COMPARISON"
  else
    log "  fpocket mode comparison: not generated (single fpocket run or ligand-local mode)"
  fi
  if [ -f "$POCKET_DIAG" ]; then
    log "  pocket diagnostics: $POCKET_DIAG"
  else
    log "  pocket diagnostics: not generated - script did not reach Step 3"
  fi
  if [ -f "$SELECTION_DIAG" ]; then
    log "  pocket selection diagnostics: $SELECTION_DIAG"
  elif [ "$LIG_PRESENT" -eq 1 ]; then
    log "  pocket selection diagnostics: not generated in ligand-centered mode; center is pinned to ligand centroid"
  else
    log "  pocket selection diagnostics: not generated - no non-ligand pocket selection was completed"
  fi
  if [ "${#SORTED[@]}" -eq 0 ] 2>/dev/null; then
    log "  selected cavities: 0"
    log "  WARNING: no cavities were selected. Inspect diagnostics and consider lower SCORE_THRESHOLD, ligand-centered mode, or different fpocket mode."
  else
    log "  selected cavities: ${#SORTED[@]}"
  fi
  log "Receptor and pocket preparation complete"
  log "No docking has been run by this command"
}

