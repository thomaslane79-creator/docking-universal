#!/usr/bin/env bash

# Deposited-ligand candidate detection, retained references, and centroid calculations.
# Sourced through docking-universal-prepare-support.sh; not executed directly.

# Identify deposited hetero residues that are plausible bound ligands.
#
# Scientific intent: offer substantial small-molecule components for optional
# site definition while excluding crystallization solvents, common buffer
# species, simple ions, and MODRES-declared polymer chemistry. The atom-count
# floor is a pragmatic candidate filter, not proof of biological relevance.
# Input: deposited PDB and minimum atom count. Output: sorted residue names.
# Protected by: tests/test_ligand_detection_helpers.sh.
detect_bound_ligand_resnames() {
  local input_pdb="$1" minimum_atoms="$2"
  awk -v minimum="$minimum_atoms" '
    FNR == NR { if (/^MODRES/) { modified=substr($0,13,3); gsub(/ /,"",modified); if(modified!="") is_modified[modified]=1 } next }
    /^HETATM/ {
      r=substr($0,18,3); gsub(/ /,"",r)
      if (r in is_modified) next
      if (r ~ /^(HOH|WAT|EDO|GOL|PEG|MPD|DMS|IPA|EOH|ACT|ACE|SO4|PO4)$/) next
      if (r ~ /^(ZN|MG|MN|CA|FE|CU|NA|K|CL)$/) next
      count[r]++
    }
    END { for (r in count) if (count[r] >= minimum) print r }
  ' "$input_pdb" "$input_pdb" | sort
}

# Retain every detected ligand candidate as an independent reference PDB and
# record its atom count and path. Scientific intent: preserve visual evidence
# even when the user chooses an unrelated fpocket site. Extraction does not
# select a ligand or affect pocket ranking.
# Inputs: deposited PDB, output directory, manifest path, then residue names.
# Outputs: one PDB per residue name and a deterministic TSV manifest.
# Protected by: tests/test_ligand_detection_helpers.sh.
write_detected_ligand_files() {
  local input_pdb="$1" ligand_dir="$2" manifest="$3"
  shift 3
  local ligand ligand_file atoms
  mkdir -p "$ligand_dir"
  printf 'ligand_resname\tatom_count\tfile\n' > "$manifest"
  for ligand in "$@"; do
    ligand_file="$ligand_dir/${ligand}.pdb"
    awk -v wanted="$ligand" '/^HETATM/{r=substr($0,18,3);gsub(/ /,"",r);if(r==wanted)print}' "$input_pdb" > "$ligand_file"
    atoms=$(awk '/^HETATM/{n++} END{print n+0}' "$ligand_file")
    printf '%s\t%s\t%s\n' "$ligand" "$atoms" "$ligand_file" >> "$manifest"
  done
}

# Calculate the deposited coordinate centroid for one selected ligand residue.
# Scientific intent: reproduce the observed site center without fitting,
# scoring, or changing the ligand. Output is X Y Z to six decimal places.
# Protected by: tests/test_ligand_detection_helpers.sh.
ligand_coordinate_centroid() {
  local input_pdb="$1" ligand="$2"
  awk -v wanted="$ligand" '
    /^HETATM/ { r=substr($0,18,3);gsub(/ /,"",r);if(r==wanted){x+=substr($0,31,8);y+=substr($0,39,8);z+=substr($0,47,8);n++} }
    END { if(n==0) exit 2; printf "%.6f %.6f %.6f",x/n,y/n,z/n }
  ' "$input_pdb"
}

# Calculate the reference centroid used only by ligand-free pocket ranking.
# Scope `1` uses all protein atoms; scope `2` uses the atom-richest chain to
# avoid placing the reference point between oligomeric chains. This centroid
# influences ranking but never changes fpocket geometry or receptor atoms.
# Inputs: prepared receptor PDB and scope 1/2. Output: X Y Z.
# Protected by: tests/test_ligand_detection_helpers.sh.
protein_ranking_centroid() {
  local receptor_pdb="$1" scope="$2"
  if [ "$scope" = 2 ]; then
    awk '/^ATOM/{c=substr($0,22,1);x[c]+=substr($0,31,8);y[c]+=substr($0,39,8);z[c]+=substr($0,47,8);n[c]++} END{best="";bn=0;for(c in n)if(n[c]>bn){bn=n[c];best=c};if(bn==0)exit 2;printf "%.6f %.6f %.6f",x[best]/n[best],y[best]/n[best],z[best]/n[best]}' "$receptor_pdb"
  else
    awk '/^ATOM/{x+=substr($0,31,8);y+=substr($0,39,8);z+=substr($0,47,8);n++} END{if(n==0)exit 2;printf "%.6f %.6f %.6f",x/n,y/n,z/n}' "$receptor_pdb"
  fi
}

# Resolve whether receptor-site discovery is ligand-guided or pocket-guided.
#
# Scientific intent: deposited ligands are evidence about possible binding
# sites, but their presence must not silently force the study to use that site.
# Every eligible ligand is therefore retained as a review artifact before the
# configured or interactive site decision is applied. In ligand mode, the
# selected residue name and coordinate centroid become the authoritative box
# anchor; in pocket mode, the same ligand files remain disabled references for
# later visual comparison.
#
# Required caller state: INPUT_PDB, ROOT, SITE_MODE, REQUESTED_LIGAND, and log().
# Published caller state: LIGANDS, LIGAND_DIR, LIGAND_MANIFEST, LIG_PRESENT,
# LIG, and (when ligand-guided) LIGX/LIGY/LIGZ.
# Protected by: tests/test_ligand_detection_helpers.sh and the ligand route in
# tests/test_receptor_preparation_routes.sh.
resolve_site_ligand_strategy() {
  LIGANDS=()
  local candidate i answer selected_index ligand_atoms ligand_file

  while IFS= read -r candidate; do
    [ -n "$candidate" ] && LIGANDS+=("$candidate")
  done < <(detect_bound_ligand_resnames "$INPUT_PDB" 10)

  LIG_PRESENT=0
  LIG=""
  LIGX=""
  LIGY=""
  LIGZ=""
  LIGAND_DIR="$ROOT/ligand"
  LIGAND_MANIFEST="$LIGAND_DIR/detected_ligands.tsv"
  mkdir -p "$LIGAND_DIR"

  if [ "${#LIGANDS[@]}" -gt 0 ]; then
    echo "Ligands detected:"
    i=1
    for candidate in "${LIGANDS[@]}"; do
      echo "  $i) $candidate"
      i=$((i+1))
    done

    write_detected_ligand_files "$INPUT_PDB" "$LIGAND_DIR" "$LIGAND_MANIFEST" "${LIGANDS[@]}"
    while IFS=$'\t' read -r candidate ligand_atoms ligand_file; do
      [ "$candidate" = ligand_resname ] && continue
      log "Detected ligand written for reference: $candidate ($ligand_atoms atoms) -> $ligand_file"
    done < "$LIGAND_MANIFEST"
    log "Detected ligand manifest written to $LIGAND_MANIFEST"

    if [ "$SITE_MODE" = pockets ]; then
      log "Configured ligand-free pocket mode; detected ligands are retained only as disabled references"
    elif [ "$SITE_MODE" = ligand ]; then
      if [ -n "$REQUESTED_LIGAND" ]; then
        for candidate in "${LIGANDS[@]}"; do
          if [ "$candidate" = "$REQUESTED_LIGAND" ]; then
            LIG="$candidate"
            break
          fi
        done
        [ -n "$LIG" ] || { echo "ERROR: requested bound ligand '$REQUESTED_LIGAND' was not detected" >&2; return 1; }
      elif [ "${#LIGANDS[@]}" -eq 1 ]; then
        LIG="${LIGANDS[0]}"
      else
        echo "ERROR: multiple bound ligands were detected; set DOCKING_UNIVERSAL_LIGAND_RESNAME" >&2
        return 1
      fi
      LIG_PRESENT=1
      log "Configured ligand-centered mode using $LIG"
    else
      read -r -p "Use ligand-centered docking? (y/n): " answer
      if [[ "$answer" =~ ^[Yy]$ ]]; then
        if [ "${#LIGANDS[@]}" -eq 1 ]; then
          LIG="${LIGANDS[0]}"
        else
          read -r -p "Select ligand number: " selected_index
          LIG="${LIGANDS[$((selected_index-1))]}"
        fi
        LIG_PRESENT=1
      fi
    fi
  elif [ "$SITE_MODE" = ligand ]; then
    echo "ERROR: ligand-centered mode was requested, but no eligible bound ligand was detected" >&2
    return 1
  fi

  if [ "$LIG_PRESENT" -eq 1 ]; then
    read -r LIGX LIGY LIGZ <<< "$(ligand_coordinate_centroid "$INPUT_PDB" "$LIG")"
  fi
}
