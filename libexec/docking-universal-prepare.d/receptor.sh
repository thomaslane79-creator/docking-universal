#!/usr/bin/env bash

# Receptor filtering, backend command boundaries, structural audits, and failure diagnosis.
# Sourced through docking-universal-prepare-support.sh; not executed directly.

# Build the receptor-only PDB consumed by the preparation backends.
#
# Scientific purpose: prevent crystallization waters and ordinary bound
# ligands from silently becoming receptor atoms while preserving structural
# chemistry that may be essential to the intended site. MODRES polymer
# residues and genuinely linked multi-atom components are retained; supported
# coordination metals are retained by PDB element identity.
#
# Inputs: deposited PDB path and destination filtered-PDB path.
# Output: a deterministic filtered PDB; the original file is never modified.
filter_receptor_input() {
  local input_pdb="$1"
  local output_pdb="$2"
  if [ -n "${REQUESTED_LIGAND:-}" ] && [ -n "${REQUESTED_LIGAND_CHAIN:-}" ] && [ -n "${REQUESTED_LIGAND_RESSEQ:-}" ]; then
    # GUI exact-reference selection owns this role. Preserve the full complex,
    # but keep even a metal-associated reference out of the scored receptor.
    "$PYTHON_COMMAND" - "$LIBEXEC_DIR" "$input_pdb" "$output_pdb" "$REQUESTED_LIGAND" \
      "$REQUESTED_LIGAND_CHAIN" "$REQUESTED_LIGAND_RESSEQ" "${REQUESTED_LIGAND_ICODE:-}" <<'PY'
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from docking_universal.receptor_filter import filter_receptor_pdb
reference = dict(zip(('resname', 'chain', 'number', 'insertion_code'), sys.argv[4:]))
record = filter_receptor_pdb(Path(sys.argv[2]), Path(sys.argv[3]), bound_reference=reference)
Path(sys.argv[3]).with_name('bound_reference_separation.json').write_text(json.dumps(record, indent=2) + '\n')
PY
    return $?
  fi
  awk '
    FNR == NR {
      if (/^MODRES/) {
        modified=substr($0,13,3); gsub(/ /,"",modified)
        if (modified != "") is_modified[modified]=1
      }
      if (/^LINK  /) {
        name1=substr($0,18,3); gsub(/ /,"",name1)
        chain1=substr($0,22,1); gsub(/ /,"",chain1)
        seq1=substr($0,23,4); gsub(/ /,"",seq1)
        icode1=substr($0,27,1); gsub(/ /,"",icode1)
        name2=substr($0,48,3); gsub(/ /,"",name2)
        chain2=substr($0,52,1); gsub(/ /,"",chain2)
        seq2=substr($0,53,4); gsub(/ /,"",seq2)
        icode2=substr($0,57,1); gsub(/ /,"",icode2)
        linked[name1 SUBSEP chain1 SUBSEP seq1 icode1]=1
        linked[name2 SUBSEP chain2 SUBSEP seq2 icode2]=1
      }
      if (/^HETATM/) {
        resname=substr($0,18,3); gsub(/ /,"",resname)
        chain=substr($0,22,1); gsub(/ /,"",chain)
        seq=substr($0,23,4); gsub(/ /,"",seq)
        icode=substr($0,27,1); gsub(/ /,"",icode)
        atom_count[resname SUBSEP chain SUBSEP seq icode]++
      }
      next
    }
    # Reduce2 boxes/translates models without crystal context. Preserve the
    # deposited frame so prepared pockets and original-coordinate evidence agree.
    /^(CRYST1|SCALE[123]|ORIGX[123])/ { print; next }
    /^ATOM  / { print; next }
    /^HETATM/ {
      resname=substr($0,18,3); gsub(/ /,"",resname)
      chain=substr($0,22,1); gsub(/ /,"",chain)
      seq=substr($0,23,4); gsub(/ /,"",seq)
      icode=substr($0,27,1); gsub(/ /,"",icode)
      if (resname in is_modified) {
        normalized=$0
        sub(/^HETATM/, "ATOM  ", normalized)
        print normalized
        next
      }
      key=resname SUBSEP chain SUBSEP seq icode
      if ((key in linked) && atom_count[key] > 1 && resname !~ /^(HOH|WAT|DOD)$/) {
        print
        next
      }
      element=toupper(substr($0,77,2))
      gsub(/[[:space:]]/, "", element)
      if (element == "ZN" || element == "MG" || element == "MN" ||
          element == "CA" || element == "FE" || element == "CU") print
    }
  ' "$input_pdb" "$input_pdb" > "$output_pdb"
}

# Report linked hetero components deliberately retained by the input filter.
# These identifiers are audit metadata and also gate the narrow ADFRsuite
# compatibility fallback after Meeko rejects linked chemistry.
# Inputs: original PDB and filtered PDB. Output: RESNAME:CHAIN:RESID values.
list_retained_linked_components() {
  local input_pdb="$1"
  local filtered_pdb="$2"
  awk '
    FNR == NR {
      if (/^LINK  /) {
        n1=substr($0,18,3); gsub(/ /,"",n1); c1=substr($0,22,1); gsub(/ /,"",c1); s1=substr($0,23,4); gsub(/ /,"",s1); i1=substr($0,27,1); gsub(/ /,"",i1)
        n2=substr($0,48,3); gsub(/ /,"",n2); c2=substr($0,52,1); gsub(/ /,"",c2); s2=substr($0,53,4); gsub(/ /,"",s2); i2=substr($0,57,1); gsub(/ /,"",i2)
        linked[n1 SUBSEP c1 SUBSEP s1 i1]=1; linked[n2 SUBSEP c2 SUBSEP s2 i2]=1
      }
      next
    }
    /^HETATM/ {
      n=substr($0,18,3); gsub(/ /,"",n); c=substr($0,22,1); gsub(/ /,"",c); s=substr($0,23,4); gsub(/ /,"",s); i=substr($0,27,1); gsub(/ /,"",i)
      key=n SUBSEP c SUBSEP s i
      if ((key in linked) && n !~ /^(HOH|WAT|DOD)$/ && !seen[key]++) print n ":" c ":" s i
    }
  ' "$input_pdb" "$filtered_pdb" | paste -sd, -
}

# Convert backend diagnostics plus deposited structural context into a stable,
# human-readable failure category. This explains why automation stopped; it
# never edits the receptor or chooses a chemical correction.
# Inputs: original PDB, filtered PDB, output path, then backend log paths.
# Output: category, scientific concern, recommended action, and detected detail.
write_receptor_failure_diagnosis() {
  local input_pdb="$1"
  local filtered_pdb="$2"
  local output_file="$3"
  shift 3
  local failure_logs=("$@")
  local category="Unclassified receptor-template failure"
  local why="The available preparation logs do not match a safely recognized failure category."
  local next="Inspect the retained backend logs and receptor chemistry before changing or deleting residues."
  local nucleic_detail nonstandard_detail

  nucleic_detail=$(awk '
    /^(ATOM  |HETATM)/ {
      name=substr($0,18,3); gsub(/ /,"",name)
      if (name !~ /^(A|C|G|U|I|DA|DC|DG|DT|DU|DI)$/) next
      chain=substr($0,22,1); gsub(/ /,"",chain)
      seq=substr($0,23,4); gsub(/ /,"",seq)
      key=chain ":" seq "=" name
      if (!seen[key]++) found[++n]=key
    }
    END { for (i=1; i<=n && i<=12; i++) printf "%s%s", (i>1 ? ", " : ""), found[i]; if (n>12) printf ", ... (%d total)", n }
  ' "$filtered_pdb")
  nonstandard_detail=$(awk '
    /^MODRES/ {
      name=substr($0,13,3); gsub(/ /,"",name)
      chain=substr($0,17,1); gsub(/ /,"",chain)
      seq=substr($0,19,4); gsub(/ /,"",seq)
      standard=substr($0,25,3); gsub(/ /,"",standard)
      key=chain ":" seq "=" name " (declared as " standard ")"
      if (!seen[key]++) found[++n]=key
    }
    END { for (i=1; i<=n && i<=12; i++) printf "%s%s", (i>1 ? ", " : ""), found[i]; if (n>12) printf ", ... (%d total)", n }
  ' "$input_pdb")

  if grep -qs "tied for fewest missing H: HIE HID" "${failure_logs[@]}"; then
    category="Ambiguous histidine protonation"
    why="More than one histidine tautomer fits the coordinates; the biologically appropriate state depends on the local environment."
    next="Review nearby hydrogen bonds or catalytic chemistry, then rerun interactively or provide an explicit MEEKO_SET_TEMPLATE assignment."
  elif grep -qs "doesn't have an implemented covalent radius\|Missing covalent radii for elements" "${failure_logs[@]}"; then
    category="Unsupported element in receptor preparation"
    why="The preparation backend lacks an element parameter needed for bond perception. This is a software-support gap, not evidence that the deposited metal or cofactor should be removed."
    next="Review metal/cofactor templates, atom typing and charge-model support. Retain site-relevant cofactors; do not replace the metal or assign placeholder parameters to bypass this failure."
  elif grep -qs 'ADFRsuite receptor-output validation: rejected' "${failure_logs[@]}"; then
    category="Rejected ADFRsuite receptor output"
    why="The legacy backend exited successfully but its output did not preserve the supplied heavy-atom model or provide supported atom types and charges."
    next="Inspect the retained ADFRsuite output audit and original coordinates; do not accept dropped components or missing charge parameters as successful preparation."
  elif grep -qs 'repair_geometry.py' "${failure_logs[@]}" && grep -qs 'could not convert string to float' "${failure_logs[@]}"; then
    category="Preparation coordinate-format handling error"
    why="An application geometry check could not read its coordinate input. This is a software format-handling failure, not evidence of incorrect deposited chemistry."
    next="Retain the input, attempted derivative and traceback for format-handler correction; no molecular change or permissive matching is justified by this error."
  elif grep -qs 'prody/.*ciffile.py' "${failure_logs[@]}" && grep -qs 'IndexError: boolean index did not match indexed array' "${failure_logs[@]}"; then
    category="Preparation backend mmCIF parsing error"
    why="The backend coordinate reader raised an internal indexing error before receptor-template matching. This does not establish a residue or chemistry defect."
    next="Retain the exact mmCIF and traceback for reader-compatibility review; do not delete atoms or change residue identities to bypass the parser."
  elif grep -qs 'automatic backbone completion is disabled' "${failure_logs[@]}"; then
    category="Incomplete deposited backbone requires review"
    why="An observed partial residue lacks backbone atoms. The conservative repair refused to construct them and did not create an accepted repaired model."
    next="Review the exact missing-atom inventory and original coordinates. Backbone construction or a deliberately edited input requires a separate explicit scientific decision."
  elif grep -qs 'PDBFixer generated sub-Angstrom heavy-atom overlaps' "${failure_logs[@]}"; then
    category="Rejected generated repair geometry"
    why="The generated repair introduced gross heavy-atom overlaps and was not accepted for parameterization. This is not proof that the deposited model itself has those overlaps."
    next="Review the retained repair audit and original coordinates; no alternative repair or residue removal has been chosen automatically."
  elif grep -qs 'Expected .* paddings.*but got' "${failure_logs[@]}"; then
    category="Preparation backend connectivity-construction error"
    why="The backend raised an internal error while constructing inter-residue connections. This does not by itself establish incorrect deposited chemistry."
    next="Retain the original and repaired models and the traceback for software/connectivity review; do not delete residues or relax matching to bypass this error."
  elif grep -qs 'AtomValenceException\|Explicit valence for atom' "${failure_logs[@]}"; then
    category="Preparation backend valence-validation error"
    why="The backend inferred a bond network that fails valence validation. The input coordinates, repair output and bond inference must be distinguished before changing chemistry."
    next="Inspect the retained original/repaired atom and bond inventories and traceback; do not force permissive valence or remove components to bypass the error."
  elif grep -qs "linking fragments\|modified backbones" "${failure_logs[@]}"; then
    category="Covalently linked nonstandard residues or glycans"
    why="The receptor contains linked fragments whose attachment chemistry cannot be inferred safely by the standard templates."
    next="Review the linkage and use validated custom templates, or deliberately remove the component only if it is irrelevant to the docking site."
  elif grep -qs "resname='HEM'\|'HEM'.*not in residue_templates" "${failure_logs[@]}"; then
    category="Unsupported heme or cofactor template"
    why="A specialized cofactor requires charge, bonding, and often metal-coordination treatment beyond generic protein repair."
    next="Use a validated cofactor-aware template or preparation method; do not silently delete a site-relevant cofactor."
  elif [ -n "$nucleic_detail" ] && grep -qs "Template matching failed\|Requested altlocs not found" "${failure_logs[@]}"; then
    category="DNA/RNA or mixed protein-nucleic-acid template conflict"
    why="DNA or RNA residues are present and do not match the preparation templates or alternate-location choices expected by this protein-focused workflow."
    next="Review whether nucleic acid is part of the intended receptor, select justified alternate locations, and use a nucleic-acid-capable preparation method or validated templates when it must be retained."
  elif grep -qs "Requested altlocs not found\|Residues with alternate location" "${failure_logs[@]}" && grep -qs "Template matching failed" "${failure_logs[@]}"; then
    category="Alternate-location and residue-template conflict"
    why="The structure contains competing coordinate variants together with residues that do not match the expected templates."
    next="Select biologically justified alternate locations and review the affected residue identities before preparation."
  elif grep -qs "Requested altlocs not found\|Residues with alternate location" "${failure_logs[@]}"; then
    category="Explicit alternate-location selection required"
    why="The backend requires a deposited coordinate variant for the named residues. No variant has been chosen by this diagnosis."
    next="Inspect each named residue and its deposited alternatives in the selected boxes, then explicitly review a choice; occupancy or distance alone does not prove correctness."
  elif [ -n "$nonstandard_detail" ] && grep -qs "not in residue_templates\|unknown residues\|Template matching failed" "${failure_logs[@]}"; then
    category="Unsupported non-standard amino acid"
    why="A polymer residue declared as a modified amino acid lacks a usable preparation template; automatic replacement could alter its chemistry or connectivity."
    next="Review the PDB MODRES mapping and choose a documented standard-amino-acid conversion, validated custom template, or deliberate exclusion."
  elif grep -qs "not in residue_templates\|unknown residues" "${failure_logs[@]}"; then
    category="Unsupported non-standard residue"
    why="One or more residue names lack a usable standard preparation template; automatic conversion could change their chemistry."
    next="Review each named residue and choose a documented standard-residue mapping, validated custom template, or deliberate exclusion."
  elif grep -qs "heavy_miss=\|Template matching failed" "${failure_logs[@]}"; then
    category="Incomplete or template-mismatched residue"
    why="Observed atoms or bonds do not match the expected residue template, even after conservative PDBFixer repair."
    next="Inspect missing atoms, connectivity, residue identity, and alternate locations near the intended docking site."
  fi

  {
    printf 'Receptor preparation failure category: %s\n' "$category"
    printf 'Why this matters: %s\n' "$why"
    printf 'Recommended next step: %s\n' "$next"
    [ -z "$nucleic_detail" ] || printf 'Detected DNA/RNA residues: %s\n' "$nucleic_detail"
    [ -z "$nonstandard_detail" ] || printf 'Detected modified amino acids: %s\n' "$nonstandard_detail"
    if grep -qs 'Bad CPU type\|Exec format error\|cannot execute' "${failure_logs[@]}"; then
      printf 'Backend compatibility warning: A configured preparation executable could not run on this machine; this is separate from the retained receptor-template failure.\n'
    fi
    grep -h -m1 "Input residues .*not in residue_templates\|Template generation failed for unknown residues\|Template matching failed for:\|Residues with alternate location:\|RuntimeError: Element .*doesn't have an implemented covalent radius\|RuntimeError: Missing covalent radii for elements" "${failure_logs[@]}" 2>/dev/null | head -1 | sed 's/^/Detected detail: /' || :
  } > "$output_file"
}

# Build, but do not execute, a Meeko receptor-preparation command.
#
# Scientific intent: keep model-changing options visible at the command
# boundary. Strict preparation contains neither --allow_bad_res nor an implicit
# alternate-location choice. Those flags appear only when the caller supplies
# an already recorded decision. Template assignments are likewise explicit.
# Inputs: executable, receptor PDB, output prefix, receptor PDBQT, allow-bad-res
# flag, alternate-location value, and template assignment value.
# Output: global PREPARATION_COMMAND array; no files are changed or executed.
# Protected by: tests/test_receptor_command_builders.sh.
build_meeko_receptor_command() {
  local executable="$1" receptor_pdb="$2" output_prefix="$3" receptor_pdbqt="$4"
  local allow_bad="$5" altloc="$6" templates="$7"
  local additional_templates="${8:-${MEEKO_ADD_TEMPLATES:-}}"
  local reader=--read_pdb
  case "$receptor_pdb" in *.cif|*.mmcif) reader=--read_with_prody ;; esac
  PREPARATION_COMMAND=("$executable" "$reader" "$receptor_pdb" -o "$output_prefix" -p "$receptor_pdbqt")
  [ "$allow_bad" = 1 ] && PREPARATION_COMMAND+=(--allow_bad_res)
  [ -z "$altloc" ] || PREPARATION_COMMAND+=(--default_altloc "$altloc")
  [ -z "$templates" ] || PREPARATION_COMMAND+=(--set_template "$templates")
  [ -z "$additional_templates" ] || PREPARATION_COMMAND+=(--add_templates "$additional_templates")
}

# Build, but do not execute, the legacy ADFRsuite preparation command used as
# the configured primary backend. Its water-removal behavior is explicit in the
# array so it can be audited independently from the fallback path.
# Inputs: executable, receptor PDB, receptor PDBQT.
# Output: global PREPARATION_COMMAND array; no command is executed.
# Protected by: tests/test_receptor_command_builders.sh.
build_adfr_receptor_command() {
  local executable="$1" receptor_pdb="$2" receptor_pdbqt="$3"
  PREPARATION_COMMAND=("$executable" -r "$receptor_pdb" -o "$receptor_pdbqt" -A none -U waters)
}

# Build the narrow ADFRsuite fallback command used only after Meeko rejects a
# retained linked component. `checkhydrogens` is intentionally distinct from
# the primary ADFR backend's `none` repair mode and is therefore separately
# named and tested rather than hidden behind a boolean flag.
# Inputs: executable, filtered receptor PDB, receptor PDBQT.
# Output: global PREPARATION_COMMAND array; no command is executed.
# Protected by: tests/test_receptor_command_builders.sh.
build_adfr_linked_fallback_command() {
  local executable="$1" receptor_pdb="$2" receptor_pdbqt="$3"
  # ADFR's default cleanup includes nonstdres, which can silently delete the
  # very deposited linked components that made this route eligible.
  PREPARATION_COMMAND=("$executable" -r "$receptor_pdb" -o "$receptor_pdbqt" -A checkhydrogens -U nphs_lps_waters)
}

# Translate depositor-annotated SSBOND records into Meeko CYX assignments.
#
# Scientific intent: preserve explicitly deposited disulfide connectivity when
# ordinary CYS templates cannot satisfy Meeko's padding requirements. Only
# CYS-CYS SSBOND pairs are accepted; proximity alone never creates a bond.
# Input: original deposited PDB. Output: comma-separated CHAIN:RESID=CYX values.
# This function reads annotations only and does not alter coordinates.
# Protected by: tests/test_receptor_structural_audits.sh.
disulfide_template_assignments() {
  local input_pdb="$1"
  awk '
    function trim(value) { gsub(/^[[:space:]]+|[[:space:]]+$/, "", value); return value }
    /^SSBOND/ {
      name1=trim(substr($0,12,3)); chain1=trim(substr($0,16,1)); seq1=trim(substr($0,18,4)); icode1=trim(substr($0,22,1))
      name2=trim(substr($0,26,3)); chain2=trim(substr($0,30,1)); seq2=trim(substr($0,32,4)); icode2=trim(substr($0,36,1))
      if (name1 == "CYS" && name2 == "CYS" && seq1 != "" && seq2 != "") {
        key1=(chain1 == "" ? ":" : chain1 ":") seq1 icode1
        key2=(chain2 == "" ? ":" : chain2 ":") seq2 icode2
        print key1 "=CYX"; print key2 "=CYX"
      }
    }
  ' "$input_pdb" | sort -u | paste -sd, -
}

# Compare the final PDBQT residue identities with the filtered receptor model
# after an explicitly approved --allow_bad_res attempt.
#
# Scientific intent: make every omitted residue/component visible, including
# complete standard amino acids whose removal is structurally consequential.
# This function audits a model change already approved by the user; it does not
# authorize removal or decide whether the resulting receptor is acceptable.
# Inputs: final PDBQT, pre-removal filtered PDB, destination TSV.
# Output: stable, sorted residue-level manifest with atom counts.
# Protected by: tests/test_receptor_structural_audits.sh and route tests.
write_removed_component_manifest() {
  local receptor_pdbqt="$1" filtered_pdb="$2" output_tsv="$3"
  awk '
    FNR == NR {
      if (/^(ATOM  |HETATM)/) {
        n=substr($0,18,3); gsub(/ /,"",n); c=substr($0,22,1); gsub(/ /,"",c); s=substr($0,23,4); gsub(/ /,"",s); i=substr($0,27,1); gsub(/ /,"",i)
        retained[n SUBSEP c SUBSEP s SUBSEP i]=1
      }
      next
    }
    /^(ATOM  |HETATM)/ {
      n=substr($0,18,3); gsub(/ /,"",n); c=substr($0,22,1); gsub(/ /,"",c); s=substr($0,23,4); gsub(/ /,"",s); i=substr($0,27,1); gsub(/ /,"",i)
      key=n SUBSEP c SUBSEP s SUBSEP i
      if (!(key in retained)) { count[key]++; name[key]=n; chain[key]=c; seq[key]=s; ins[key]=i }
    }
    END {
      print "chain\tresidue_number\tinsertion_code\tresidue_name\tatom_count"
      for (key in count) print chain[key] "\t" seq[key] "\t" ins[key] "\t" name[key] "\t" count[key]
    }
  ' "$receptor_pdbqt" "$filtered_pdb" | {
    IFS= read -r header
    printf '%s\n' "$header"
    sort -t $'\t' -k1,1 -k2,2n -k3,3 -k4,4
  } > "$output_tsv"
}

# Read the last histidine residue for which Meeko reports an HIE/HID tie.
# Scientific intent: identify the location requiring review without guessing a
# protonation state. Input: one or more Meeko logs in precedence order.
# Output: CHAIN:RESID or an empty string. Protected by structural-audit tests.
ambiguous_histidine_residue() {
  sed -n "s/.*for residue_key='\([^']*\)'.*tied for fewest missing H: HIE HID.*/\1/p" "$@" 2>/dev/null | tail -1
}

# List deposited histidines that do not already contain an explicit HD1 or HE2
# ring proton. Scientific intent: support an explicitly requested all-histidine
# assignment while respecting protonation evidence already present in the PDB.
# This function identifies candidates only; it never selects HIE, HID, or HIP.
# Input: receptor PDB. Output: sorted CHAIN:RESID values, one per line.
# Protected by: tests/test_receptor_structural_audits.sh.
histidines_without_explicit_ring_proton() {
  local receptor_pdb="$1"
  awk '
    /^(ATOM  |HETATM)/ {
      res=substr($0,18,3); gsub(/ /,"",res); if (res != "HIS") next
      chain=substr($0,22,1); gsub(/ /,"",chain); seq=substr($0,23,4); gsub(/ /,"",seq)
      key=chain ":" seq; atom=substr($0,13,4); gsub(/ /,"",atom); seen[key]=1
      if (atom == "HD1" || atom == "HE2") ring_h[key]=1
    }
    END { for (key in seen) if (!(key in ring_h)) print key }
  ' "$receptor_pdb" | sort
}

# Execute an already constructed external-tool command and retain its complete
# stdout/stderr log. Scientific route selection must occur before this call;
# this helper adds no flags, retries, or interpretation of tool output.
# Inputs: log path followed by the command and arguments. Output: tool status.
# Protected by: tests/test_receptor_attempt_runner.sh.
run_logged_preparation_command() {
  local log_file="$1"
  shift
  "$@" > "$log_file" 2>&1
}

# Execute a logged command and require its declared output artifact to be
# non-empty before reporting success. This prevents a zero exit status without
# a usable receptor file from advancing the scientific workflow.
# Inputs: log path, required artifact path, then command and arguments.
# Output: success only when both command status and artifact are valid.
# Protected by: tests/test_receptor_attempt_runner.sh.
run_logged_preparation_artifact() {
  local log_file="$1" required_artifact="$2"
  shift 2
  run_logged_preparation_command "$log_file" "$@" && [ -s "$required_artifact" ]
}

# Record availability separately from backend diagnostics. A skipped fallback
# must not create a backend log: downstream provenance uses that log as evidence
# that the legacy compatibility route was considered or attempted.
record_adfr_fallback_status() {
  ADFR_FALLBACK_STATUS="$1"
  ADFR_FALLBACK_REASON="$2"
  log "ADFRsuite fallback status: $ADFR_FALLBACK_STATUS; $ADFR_FALLBACK_REASON"
}

# Extend an existing success/failure audit instead of creating another manifest.
# This metadata explains routing only; it neither changes the primary diagnosis
# nor asserts that a legacy preparer supports the retained chemistry.
retain_adfr_fallback_status() {
  local audit_path="$1" audited_executable="${ADFR_FALLBACK_BIN:-}"
  [ "${PREP_BACKEND:-}" != adfr ] || audited_executable="${PREP_RECEPTOR_BIN:-}"
  [ -s "$audit_path" ] || return 0
  "$PYTHON_COMMAND" - "$audit_path" "${ADFR_FALLBACK_STATUS:-not_evaluated}" \
    "${ADFR_FALLBACK_REASON:-Receptor preparation stopped before fallback evaluation.}" \
    "$audited_executable" "${ADFR_OUTPUT_AUDIT:-}" "${ADFR_VALIDATION_LOG:-}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
record = json.loads(path.read_text())
record["adfr_fallback"] = {
    "status": sys.argv[2],
    "reason": sys.argv[3],
    "executable": sys.argv[4] or None,
}
for key, value in zip(("validation_audit", "validation_log"), sys.argv[5:]):
    if value and Path(value).is_file():
        record["adfr_fallback"][key] = str(Path(value).resolve())
path.write_text(json.dumps(record, indent=2) + "\n")
PY
}

# A successful legacy command is insufficient: retain the exact input/output
# comparison and reject missing atoms or unsupported charge assignment before
# publishing a PDBQT as prepared. This never changes a parameter or coordinate.
validate_adfr_preparation_output() {
  local source_pdb="$1" backend_log="$2"
  if "$PYTHON_COMMAND" - "$LIBEXEC_DIR" "$source_pdb" "$RECEPTOR_PDBQT" \
    "$backend_log" "$ADFR_OUTPUT_AUDIT" > "$ADFR_VALIDATION_LOG" 2>&1 <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from docking_universal.services.preparation_atom_inventory import audit_adfr_receptor_output

report = audit_adfr_receptor_output(*sys.argv[2:])
print("ADFRsuite receptor-output validation: " + report["status"])
for reason in report["reasons"]:
    print(reason)
raise SystemExit(0 if report["status"] == "accepted" else 1)
PY
  then
    ADFR_VALIDATION_DETAIL=""
    return 0
  fi
  ADFR_VALIDATION_DETAIL=$(sed -n '2,4p' "$ADFR_VALIDATION_LOG" | tr '\n' ' ')
  return 1
}

# Initialize receptor-preparation paths, immutable filtered input, and optional
# repair capability before any backend attempt is made.
#
# Scientific intent: every retry must start from a retained, auditable receptor
# model rather than an implicitly mutated intermediate. LINK-connected deposited
# components and depositor-annotated disulfides are inventoried here because
# they govern only narrowly justified later fallbacks.
# Required caller state: input/output/package paths and active Python command.
# Published caller state: all receptor artifact/log paths, retained-component
# evidence, PDBFixer availability, and PDBFIXER_USED=0.
# Protected by receptor input, structural-audit, and route tests.
initialize_receptor_preparation() {
  RECEPTOR_PDB="$RECEPTOR_DIR/${CANONICAL}.pdb"
  RECEPTOR_FILTERED_PDB="$RECEPTOR_DIR/${CANONICAL}_filtered.pdb"
  PDBFIXER_PDB="$RECEPTOR_DIR/${CANONICAL}_pdbfixer.pdb"
  RECEPTOR_PDBQT="$RECEPTOR_DIR/${CANONICAL}.pdbqt"
  RECEPTOR_BACKEND_LOG="$RECEPTOR_DIR/receptor_backend.log"
  PDBFIXER_LOG="$RECEPTOR_DIR/pdbfixer.log"
  PDBFIXER_AUDIT="$RECEPTOR_DIR/pdbfixer_audit.json"
  PDBFIXER_MEEKO_LOG="$RECEPTOR_DIR/receptor_after_pdbfixer.log"
  PROTONATION_PDB="$RECEPTOR_DIR/${CANONICAL}_protonated.pdb"
  PROTONATION_PQR="$RECEPTOR_DIR/${CANONICAL}.pqr"
  PROTONATION_LOG="$RECEPTOR_DIR/pdb2pqr.log"
  PROTONATION_AUDIT="$RECEPTOR_DIR/pdb2pqr_audit.json"
  REDUCE2_PDB="$RECEPTOR_DIR/${CANONICAL}_reduce2H.pdb"
  REDUCE2_LOG="$RECEPTOR_DIR/reduce2.log"
  REDUCE2_AUDIT="$RECEPTOR_DIR/reduce2_audit.json"
  RECEPTOR_RETRY_LOG="$RECEPTOR_DIR/receptor_retry.log"
  DISULFIDE_RETRY_LOG="$RECEPTOR_DIR/receptor_disulfide_retry.log"
  DISULFIDE_SELECTION_LOG="$RECEPTOR_DIR/disulfide_template_selection.tsv"
  ADFR_FALLBACK_LOG="$RECEPTOR_DIR/receptor_adfr_fallback.log"
  ADFR_OUTPUT_AUDIT="$RECEPTOR_DIR/adfr_output_audit.json"
  ADFR_VALIDATION_LOG="$RECEPTOR_DIR/adfr_output_validation.log"
  CCD_AUDIT_JSON="$RECEPTOR_DIR/ccd_modification_audit.json"
  CCD_AUDIT_TSV="$RECEPTOR_DIR/ccd_modification_audit.tsv"
  PDBFIXER_USED=0
  PROTONATION_USED=0
  REDUCE2_USED=0
  ADFR_FALLBACK_STATUS=not_evaluated
  ADFR_FALLBACK_REASON="Receptor preparation stopped before fallback evaluation."

  DISULFIDE_TEMPLATE_ASSIGNMENTS=$(disulfide_template_assignments "$INPUT_PDB")
  if [ -n "${DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT:-}" ]; then
    # Removing a reviewed residue also prunes its LINK records. Re-filtering
    # that full complex could then silently discard an orphaned component that
    # the user chose to retain. The host instead pins the original receptor
    # inventory with only the explicitly reviewed changes applied.
    [ "${DOCKING_UNIVERSAL_REVIEWED_MODEL_ONLY:-0}" = 1 ] || {
      echo "ERROR: A reviewed receptor inventory requires an explicit reviewed-model attempt" >&2
      return 1
    }
    "$PYTHON_COMMAND" - "$DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT" \
      "${DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT_SHA256:-}" "$RECEPTOR_FILTERED_PDB" <<'PY' || return 1
import hashlib
from pathlib import Path
import re
import sys

try:
    source, expected, destination = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    data = source.read_bytes()
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("the approved filtered receptor is missing its hash or has changed")
    destination.write_bytes(data)
except (OSError, ValueError) as exc:
    raise SystemExit("ERROR: Reviewed receptor inventory could not be verified: " + str(exc))
PY
  else
    filter_receptor_input "$INPUT_PDB" "$RECEPTOR_FILTERED_PDB" || return $?
  fi
  RETAINED_LINKED_COMPONENTS=$(list_retained_linked_components "$INPUT_PDB" "$RECEPTOR_FILTERED_PDB")

  PDBFIXER_MODE="${DOCKING_UNIVERSAL_PDBFIXER:-auto}"
  case "$PDBFIXER_MODE" in
    auto|required|off) ;;
    *) echo "ERROR: DOCKING_UNIVERSAL_PDBFIXER must be auto, required, or off" >&2; return 2 ;;
  esac
  PROTONATION_MODE="${DOCKING_UNIVERSAL_PROTONATION:-auto}"
  case "$PROTONATION_MODE" in
    auto|required|off) ;;
    *) echo "ERROR: DOCKING_UNIVERSAL_PROTONATION must be auto, required, or off" >&2; return 2 ;;
  esac
  REDUCE2_MODE="${DOCKING_UNIVERSAL_REDUCE2:-auto}"
  case "$REDUCE2_MODE" in
    auto|required|off) ;;
    *) echo "ERROR: DOCKING_UNIVERSAL_REDUCE2 must be auto, required, or off" >&2; return 2 ;;
  esac
  REDUCE2_HELPER="$LIBEXEC_DIR/docking-universal-reduce2-receptor.py"
  if [ ! -f "$REDUCE2_HELPER" ] && [ -f "$(dirname "$0")/docking-universal-reduce2-receptor.py" ]; then
    REDUCE2_HELPER="$(dirname "$0")/docking-universal-reduce2-receptor.py"
  fi
  REDUCE2_AVAILABLE=0
  if [ -f "$REDUCE2_HELPER" ] && "$PYTHON_COMMAND" -c 'import site, pathlib; raise SystemExit(0 if any((pathlib.Path(p)/"mmtbx/command_line/reduce2.py").is_file() for p in site.getsitepackages()) else 1)' >/dev/null 2>&1; then
    REDUCE2_AVAILABLE=1
  elif [ "$REDUCE2_MODE" = required ]; then
    echo "ERROR: CCTBX reduce2.py is unavailable in the active installation" >&2
    return 1
  fi
  PROTONATION_PH="${DOCKING_UNIVERSAL_RECEPTOR_PH:-7.4}"
  PROTONATION_HELPER="$LIBEXEC_DIR/docking-universal-protonate-receptor.py"
  if [ ! -f "$PROTONATION_HELPER" ] && [ -f "$(dirname "$0")/docking-universal-protonate-receptor.py" ]; then
    PROTONATION_HELPER="$(dirname "$0")/docking-universal-protonate-receptor.py"
  fi
  PROTONATION_AVAILABLE=0
  if [ -f "$PROTONATION_HELPER" ] && { command -v "${PDB2PQR_COMMAND:-pdb2pqr30}" >/dev/null 2>&1 || command -v pdb2pqr >/dev/null 2>&1; }; then
    PROTONATION_AVAILABLE=1
  elif [ "$PROTONATION_MODE" = required ]; then
    echo "ERROR: PDB2PQR/PROPKA or the Docking Universal protonation helper is unavailable" >&2
    return 1
  fi
  PDBFIXER_HELPER="$LIBEXEC_DIR/docking-universal-pdbfixer.py"
  if [ ! -f "$PDBFIXER_HELPER" ] && [ -f "$(dirname "$0")/docking-universal-pdbfixer.py" ]; then
    PDBFIXER_HELPER="$(dirname "$0")/docking-universal-pdbfixer.py"
  fi
  PDBFIXER_AVAILABLE=0
  if [ -f "$PDBFIXER_HELPER" ] && "$PYTHON_COMMAND" -c 'import pdbfixer, openmm' >/dev/null 2>&1; then
    PDBFIXER_AVAILABLE=1
  elif [ "$PDBFIXER_MODE" = required ]; then
    echo "ERROR: PDBFixer or its Docking Universal helper is unavailable in the active installation" >&2
    return 1
  fi
  cp "$RECEPTOR_FILTERED_PDB" "$RECEPTOR_PDB"
  NATIVE_RECEPTOR_INPUT="$RECEPTOR_FILTERED_PDB"
  if [ -n "${DOCKING_UNIVERSAL_SOURCE_MMCIF:-}" ]; then
    mkdir -p "$ROOT/source"
    cp "$DOCKING_UNIVERSAL_SOURCE_MMCIF" "$ROOT/source/structure.cif"
    if [ -n "${DOCKING_UNIVERSAL_STRUCTURE_METADATA:-}" ]; then
      cp "$DOCKING_UNIVERSAL_STRUCTURE_METADATA" "$ROOT/source/structure-input.json"
    fi
    NATIVE_RECEPTOR_INPUT="$RECEPTOR_DIR/${CANONICAL}_filtered.cif"
    "$PYTHON_COMMAND" "$LIBEXEC_DIR/docking-universal-native-receptor.py" \
      "$DOCKING_UNIVERSAL_SOURCE_MMCIF" "$RECEPTOR_FILTERED_PDB" "$NATIVE_RECEPTOR_INPUT" || return $?
    log "Retained mmCIF source and metadata; native receptor input uses the existing component filter and author identifiers"
  fi
}

# Validate and publish the successful receptor-preparation evidence.
#
# Scientific intent: the chosen preparation route must be bound to its exact
# diagnostic log and MODRES/CCD audit before cavity discovery begins. This is
# also the single boundary that asserts a nonempty receptor PDBQT exists.
# Required caller state: PREP_ROUTE and initialized receptor paths/logs.
# Published caller state: CCD audit files and CHAIN_SUMMARY.
# Protected by CCD, structural-audit, and receptor-route tests.
finalize_receptor_preparation_audit() {
  local ccd_helper ccd_evidence_log ccd_count chain residues atoms
  if feedback_verbose; then
    cat "$RECEPTOR_BACKEND_LOG"
  elif grep -q 'not in residue_templates' "$RECEPTOR_BACKEND_LOG"; then
    log "Meeko resolved one or more nonstandard residue templates automatically; review $RECEPTOR_BACKEND_LOG for chemical-template details"
  fi
  [ -s "$RECEPTOR_PDBQT" ] || { echo "ERROR: receptor backend did not create PDBQT: $RECEPTOR_PDBQT"; return 1; }
  log "Prepared receptor PDBQT written to $RECEPTOR_PDBQT"
  case "$PREP_ROUTE" in
    adfr_primary|adfr_legacy_linked_component_fallback)
      "$PYTHON_COMMAND" - "$LIBEXEC_DIR" "$RECEPTOR_DIR/adfr_startup_audit.json" "$RECEPTOR_PDBQT" "$PREP_ROUTE" "$RECEPTOR_DIR/receptor_backend_identity.json" <<'PY_BACKEND'
import sys
sys.path.insert(0, sys.argv[1])
from docking_universal.services.backend_provenance import bind_output
bind_output(*sys.argv[2:])
PY_BACKEND
      [ $? -eq 0 ] || return 1
      ;;
  esac

  RETAINED_MEEKO_TEMPLATE=""
  if [ -n "${MEEKO_ADD_TEMPLATES:-}" ] && [ -f "$MEEKO_ADD_TEMPLATES" ]; then
    RETAINED_MEEKO_TEMPLATE="$RECEPTOR_DIR/meeko_additional_templates.json"
    cp "$MEEKO_ADD_TEMPLATES" "$RETAINED_MEEKO_TEMPLATE"
    template_parent=$(dirname "$MEEKO_ADD_TEMPLATES")
    [ ! -f "$template_parent/meeko-ptm-template-audit.json" ] || \
      cp "$template_parent/meeko-ptm-template-audit.json" "$RECEPTOR_DIR/meeko_ptm_template_audit.json"
    [ ! -f "$template_parent/meeko-ptm-template-approval.json" ] || \
      cp "$template_parent/meeko-ptm-template-approval.json" "$RECEPTOR_DIR/meeko_ptm_template_approval.json"
    log "Retained the explicitly reviewed Meeko PTM template and provenance with the prepared receptor"
  fi

  ccd_helper="$LIBEXEC_DIR/docking-universal-ccd-audit.py"
  if [ ! -f "$ccd_helper" ] && [ -f "$(dirname "$0")/docking-universal-ccd-audit.py" ]; then
    ccd_helper="$(dirname "$0")/docking-universal-ccd-audit.py"
  fi
  if [ -f "$ccd_helper" ]; then
    case "$PREP_ROUTE" in
      guided_histidine_template) ccd_evidence_log="$HISTIDINE_RETRY_LOG" ;;
      meeko_user_approved_component_removal) ccd_evidence_log="$RECEPTOR_DIR/receptor_user_approved_removal.log" ;;
      meeko_disulfide_templates) ccd_evidence_log="$DISULFIDE_RETRY_LOG" ;;
      adfr_legacy_linked_component_fallback) ccd_evidence_log="$ADFR_FALLBACK_LOG" ;;
      pdbfixer_then_strict_meeko) ccd_evidence_log="$PDBFIXER_MEEKO_LOG" ;;
      *) ccd_evidence_log="$RECEPTOR_BACKEND_LOG" ;;
    esac
    CCD_AUDIT_ARGS=(
      "$INPUT_PDB" "$RECEPTOR_PDBQT" "$ccd_evidence_log"
      "$PREP_ROUTE" "$CCD_AUDIT_JSON" "$CCD_AUDIT_TSV"
    )
    [ -z "$RETAINED_MEEKO_TEMPLATE" ] || CCD_AUDIT_ARGS+=(--additional-templates "$RETAINED_MEEKO_TEMPLATE")
    "$PYTHON_COMMAND" "$ccd_helper" "${CCD_AUDIT_ARGS[@]}" >/dev/null
    retain_adfr_fallback_status "$CCD_AUDIT_JSON"
    ccd_count=$("$PYTHON_COMMAND" -c 'import json,sys; print(json.load(open(sys.argv[1]))["modified_polymer_residue_count"])' "$CCD_AUDIT_JSON")
    if [ "$ccd_count" -gt 0 ]; then
      log "CCD/MODRES audit recorded $ccd_count modified polymer residue(s): $CCD_AUDIT_TSV"
      awk -F '\t' 'NR > 1 { printf "  %s %s -> %s: %s\n", $1, $2, $3, $5 }' "$CCD_AUDIT_TSV"
    else
      log "CCD/MODRES audit: no MODRES-declared polymer modifications detected"
    fi
  fi

  CHAIN_SUMMARY="$ROOT/chain_summary.tsv"
  summarize_chains "$RECEPTOR_PDB" "$CHAIN_SUMMARY"
  log "Chain summary written to $CHAIN_SUMMARY"
  while IFS=$'\t' read -r chain residues atoms; do
    log "Chain ${chain}: ${residues} residues, ${atoms} atoms"
  done < "$CHAIN_SUMMARY"
}

# Run the ordered, non-destructive receptor-preparation attempt ladder.
# The initial backend is followed only by chemically bounded retries:
# conservative PDBFixer repair, depositor-annotated disulfide templates,
# explicit histidine review, and the narrow linked-component ADFRsuite path.
# No unmatched component is removed here; that remains a separate approval
# boundary in the entry workflow. Published state: PREP_SUCCESS/PREP_ROUTE.
# Protected by tests/test_receptor_preparation_routes.sh.
run_safe_receptor_preparation_attempts() {
  if [ "$PREP_BACKEND" = "meeko" ]; then
    MEEKO_ALLOW_BAD_RES="${MEEKO_ALLOW_BAD_RES:-0}"
    MEEKO_DEFAULT_ALTLOC="${MEEKO_DEFAULT_ALTLOC:-}"
    MEEKO_SET_TEMPLATE="${MEEKO_SET_TEMPLATE:-}"
    MEEKO_TEMPLATE_ARGS=()
    [ -z "$MEEKO_SET_TEMPLATE" ] || MEEKO_TEMPLATE_ARGS=(--set_template "$MEEKO_SET_TEMPLATE")
    local initial_input="$RECEPTOR_FILTERED_PDB"
    if [ -n "${DOCKING_UNIVERSAL_SOURCE_MMCIF:-}" ]; then
      if "$PYTHON_COMMAND" -c 'import prody' >/dev/null 2>&1; then
        initial_input="$NATIVE_RECEPTOR_INPUT"
      else
        log "ProDy unavailable: using the retained PDB compatibility input for Meeko"
      fi
    fi
    if [ "$REDUCE2_MODE" != off ] && [ "$REDUCE2_AVAILABLE" = "1" ]; then
      log "Running CCTBX reduce2 for receptor hydrogen placement and flip optimization; audit -> $REDUCE2_AUDIT"
      if run_logged_preparation_command "$REDUCE2_LOG" "$PYTHON_COMMAND" "$REDUCE2_HELPER" \
        "$initial_input" "$REDUCE2_PDB" "$REDUCE2_AUDIT" "$REDUCE2_LOG"; then
        REDUCE2_USED=1
        cp "$REDUCE2_PDB" "$RECEPTOR_PDB"
        initial_input="$RECEPTOR_PDB"
        log "CCTBX reduce2 produced the chemistry-checked hydrogen-optimized receptor; Meeko will consume it"
      elif [ "$REDUCE2_MODE" = required ]; then
        echo "ERROR: CCTBX reduce2 could not produce a chemistry-preserving receptor; inspect $REDUCE2_AUDIT" >&2
        return 1
      else
        log "CCTBX reduce2 did not produce an accepted receptor; inspect $REDUCE2_AUDIT and $REDUCE2_LOG for the process/output or validation reason"
      fi
    fi
    if [ "$REDUCE2_USED" = "0" ] && { [ "$REDUCE2_AVAILABLE" = "0" ] || [ "$PROTONATION_MODE" = required ]; } && [ "$PROTONATION_MODE" != off ] && [ "$PROTONATION_AVAILABLE" = "1" ]; then
      log "Running pH-aware PDB2PQR/PROPKA receptor assessment at pH $PROTONATION_PH; audit -> $PROTONATION_AUDIT"
      # PDB2PQR 3.6 requires descriptive categories absent from our filtered
      # native mmCIF. Its audit also reads PDB records. Use the already retained
      # compatibility projection of this exact receptor, without re-filtering
      # or inventing a new atom/model selection.
      if run_logged_preparation_command "$PROTONATION_LOG" "$PYTHON_COMMAND" "$PROTONATION_HELPER" \
        "$RECEPTOR_FILTERED_PDB" "$PROTONATION_PDB" "$PROTONATION_PQR" "$PROTONATION_AUDIT" "$PROTONATION_LOG" --ph "$PROTONATION_PH"; then
        protonation_status=$("$PYTHON_COMMAND" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status", "unknown"))' "$PROTONATION_AUDIT" 2>/dev/null || echo unknown)
        if [ "$protonation_status" = compatible ]; then
          PROTONATION_USED=1
          cp "$PROTONATION_PDB" "$RECEPTOR_PDB"
          initial_input="$RECEPTOR_PDB"
          log "PDB2PQR/PROPKA produced a chemistry-checked receptor; Meeko will consume the retained protonated model"
        elif [ "$PROTONATION_MODE" = required ]; then
          echo "ERROR: PDB2PQR/PROPKA requires review before use (status: $protonation_status); inspect $PROTONATION_AUDIT" >&2
          return 1
        else
          log "PDB2PQR/PROPKA requires review (status: $protonation_status); retaining the original filtered receptor"
        fi
      else
        protonation_status="unknown"
        [ ! -s "$PROTONATION_AUDIT" ] || protonation_status=$("$PYTHON_COMMAND" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status", "unknown"))' "$PROTONATION_AUDIT" 2>/dev/null || echo unknown)
        if [ "$protonation_status" = incompatible ] || [ "$PROTONATION_MODE" = required ]; then
          echo "ERROR: PDB2PQR/PROPKA could not produce a chemistry-preserving receptor (status: $protonation_status); inspect $PROTONATION_AUDIT" >&2
          return 1
        fi
        log "PDB2PQR/PROPKA was not adopted (status: $protonation_status); retaining the original filtered receptor and audit"
      fi
    elif [ "$REDUCE2_USED" = "0" ] && [ "$REDUCE2_AVAILABLE" = "1" ]; then
      log "No accepted CCTBX reduce2 model is available; retaining the original filtered receptor rather than substituting a second protonation engine (see $REDUCE2_AUDIT)"
    elif [ "$REDUCE2_USED" = "0" ] && [ "$PROTONATION_MODE" != off ]; then
      log "PDB2PQR/PROPKA unavailable; retaining the original filtered receptor (set DOCKING_UNIVERSAL_PROTONATION=required to stop)"
    fi
    build_meeko_receptor_command "$PREP_RECEPTOR_BIN" "$initial_input" \
      "$RECEPTOR_DIR/${CANONICAL}" "$RECEPTOR_PDBQT" "$MEEKO_ALLOW_BAD_RES" \
      "$MEEKO_DEFAULT_ALTLOC" "$MEEKO_SET_TEMPLATE"
    PREP_COMMAND=("${PREPARATION_COMMAND[@]}")
  else
    build_adfr_receptor_command "$PREP_RECEPTOR_BIN" "$RECEPTOR_PDB" "$RECEPTOR_PDBQT"
    PREP_COMMAND=("${PREPARATION_COMMAND[@]}")
  fi

  log "Preparing the selected audited receptor with $PREP_BACKEND (Reduce2 used: $REDUCE2_USED; PDB2PQR used: $PROTONATION_USED); detailed output -> $RECEPTOR_BACKEND_LOG"
  PREP_SUCCESS=0
  PREP_ROUTE=not_completed
  if [ "$PREP_BACKEND" = adfr ]; then
    if ! "$PYTHON_COMMAND" "$LIBEXEC_DIR/docking-universal-backend-startup.py" "$PREP_RECEPTOR_BIN" \
        "$RECEPTOR_DIR/adfr_startup_audit.json" --input "$RECEPTOR_PDB" > "$RECEPTOR_DIR/adfr_startup.log" 2>&1; then
      log "The ADFRsuite startup probe did not complete; retaining its diagnostics and the actual primary preparation outcome. A PDF still requires recorded software identity."
    fi
  fi
  if run_logged_preparation_command "$RECEPTOR_BACKEND_LOG" "${PREP_COMMAND[@]}"; then
    if [ "$PREP_BACKEND" = adfr ] && ! validate_adfr_preparation_output "$RECEPTOR_PDB" "$RECEPTOR_BACKEND_LOG"; then
      record_adfr_fallback_status validation_failed "The primary ADFRsuite output failed validation: $ADFR_VALIDATION_DETAIL Inspect $ADFR_OUTPUT_AUDIT and $ADFR_VALIDATION_LOG."
      return 0
    fi
    PREP_SUCCESS=1
    if [ "$PREP_BACKEND" = meeko ]; then
      PREP_ROUTE=strict_meeko
      record_adfr_fallback_status not_needed "Initial strict Meeko preparation succeeded."
    else
      PREP_ROUTE=adfr_primary
      record_adfr_fallback_status primary_backend "ADFRsuite was selected as the primary backend; no Meeko fallback was requested."
    fi
    log "Initial receptor preparation succeeded; PDBFixer was not needed"
  elif [ "${DOCKING_UNIVERSAL_REVIEWED_MODEL_ONLY:-0}" = 1 ]; then
    record_adfr_fallback_status reviewed_model_stop "The explicitly reviewed model permits one strict preparation attempt only."
    log "The explicitly reviewed receptor failed strict preparation; no additional repair, alternate-location choice, residue exclusion or legacy fallback was attempted."
    return 0
  elif [ "$PREP_BACKEND" = "meeko" ]; then
    log "Initial Meeko preparation failed; preserving its diagnostics before attempting quick repairs"
    if [ "$PDBFIXER_MODE" != "off" ] && [ "$PDBFIXER_AVAILABLE" = "1" ]; then
      log "Repairing receptor with PDBFixer; audit -> $PDBFIXER_AUDIT"
      if run_logged_preparation_command "$PDBFIXER_LOG" "$PYTHON_COMMAND" "$PDBFIXER_HELPER" \
        "${NATIVE_RECEPTOR_INPUT:-$RECEPTOR_FILTERED_PDB}" "$PDBFIXER_PDB" "$PDBFIXER_AUDIT"; then
        PDBFIXER_USED=1
        cp "$PDBFIXER_PDB" "$RECEPTOR_PDB"
        build_meeko_receptor_command "$PREP_RECEPTOR_BIN" "$RECEPTOR_PDB" \
          "$RECEPTOR_DIR/${CANONICAL}" "$RECEPTOR_PDBQT" 0 '' "$MEEKO_SET_TEMPLATE"
        PDBFIXER_COMMAND=("${PREPARATION_COMMAND[@]}")
        log "Retrying strict Meeko after PDBFixer; detailed output -> $PDBFIXER_MEEKO_LOG"
        if run_logged_preparation_command "$PDBFIXER_MEEKO_LOG" "${PDBFIXER_COMMAND[@]}"; then
          PREP_SUCCESS=1
          PREP_ROUTE=pdbfixer_then_strict_meeko
          log "PDBFixer repair followed by strict Meeko preparation succeeded"
        else
          log "Strict Meeko still rejected the PDBFixer output"
        fi
      else
        log "PDBFixer could not repair this receptor; continuing to applicable targeted retries"
      fi
    fi

    if [ "$PREP_SUCCESS" = "0" ] && [ -n "$DISULFIDE_TEMPLATE_ASSIGNMENTS" ]; then
      DISULFIDE_TEMPLATES="$DISULFIDE_TEMPLATE_ASSIGNMENTS"
      [ -z "$MEEKO_SET_TEMPLATE" ] || DISULFIDE_TEMPLATES="$MEEKO_SET_TEMPLATE,$DISULFIDE_TEMPLATES"
      log "Retrying Meeko with CYX templates for depositor-annotated disulfides; detailed output -> $DISULFIDE_RETRY_LOG"
      # Only the deposited disulfide assignment is automatic. Unmatched
      # components and unresolved alternate locations still require review.
      build_meeko_receptor_command "$PREP_RECEPTOR_BIN" "$RECEPTOR_FILTERED_PDB" \
        "$RECEPTOR_DIR/${CANONICAL}" "$RECEPTOR_PDBQT" 0 '' "$DISULFIDE_TEMPLATES"
      DISULFIDE_COMMAND=("${PREPARATION_COMMAND[@]}")
      if run_logged_preparation_command "$DISULFIDE_RETRY_LOG" "${DISULFIDE_COMMAND[@]}"; then
        PREP_SUCCESS=1
        PREP_ROUTE=meeko_disulfide_templates
        cp "$RECEPTOR_FILTERED_PDB" "$RECEPTOR_PDB"
        {
          printf 'residue\ttemplate\treason\n'
          printf '%s\n' "$DISULFIDE_TEMPLATE_ASSIGNMENTS" | tr ',' '\n' | while IFS= read -r assignment; do
            printf '%s\tCYX\tdepositor-annotated SSBOND pair retained after Meeko padding retry\n' "${assignment%=CYX}"
          done
        } > "$DISULFIDE_SELECTION_LOG"
        log "Meeko preserved depositor-annotated disulfide bridge(s); review $DISULFIDE_SELECTION_LOG"
      fi
    fi

    if [ "$PREP_SUCCESS" = "0" ] && [ -z "$MEEKO_SET_TEMPLATE" ]; then
      HISTIDINE_SOURCE="$RECEPTOR_FILTERED_PDB"
      [ "$PDBFIXER_USED" = "0" ] || HISTIDINE_SOURCE="$PDBFIXER_PDB"
      HISTIDINE_RETRY_LOG="$RECEPTOR_DIR/receptor_histidine_retry.log"
      HISTIDINE_SELECTION_LOG="$RECEPTOR_DIR/histidine_template_selection.tsv"
      HISTIDINE_DIAGNOSTIC_LOGS=("$PDBFIXER_MEEKO_LOG" "$RECEPTOR_RETRY_LOG" "$RECEPTOR_BACKEND_LOG")
      while [ "$PREP_SUCCESS" = "0" ]; do
        HISTIDINE_RESIDUE=$(ambiguous_histidine_residue "${HISTIDINE_DIAGNOSTIC_LOGS[@]}")
        [ -n "$HISTIDINE_RESIDUE" ] || break
        if [ -t 0 ]; then
          cat <<EOF

Meeko found an ambiguous histidine protonation state at $HISTIDINE_RESIDUE.
Choose the state justified by the local hydrogen-bonding and catalytic environment:
  1) HIE - neutral histidine, proton on NE2
  2) HID - neutral histidine, proton on ND1
  3) HIP - positively charged histidine, protons on both nitrogens
  4) Stop for structural review
EOF
          read -r -p "Select histidine state [4]: " HISTIDINE_CHOICE
          case "${HISTIDINE_CHOICE:-4}" in
            1) HISTIDINE_TEMPLATE=HIE ;;
            2) HISTIDINE_TEMPLATE=HID ;;
            3) HISTIDINE_TEMPLATE=HIP ;;
            *) HISTIDINE_TEMPLATE="" ;;
          esac
          [ -n "$HISTIDINE_TEMPLATE" ] || break
          read -r -p "Apply $HISTIDINE_TEMPLATE to 1) only $HISTIDINE_RESIDUE or 2) all histidines without an explicit HD1/HE2 proton? [1]: " HISTIDINE_SCOPE
          HISTIDINE_KEYS="$HISTIDINE_RESIDUE"
          if [ "${HISTIDINE_SCOPE:-1}" = "2" ]; then
            HISTIDINE_KEYS=$(histidines_without_explicit_ring_proton "$RECEPTOR_FILTERED_PDB")
          fi
          [ -s "$HISTIDINE_SELECTION_LOG" ] || printf 'residue\ttemplate\treason\n' > "$HISTIDINE_SELECTION_LOG"
          for HISTIDINE_KEY in $HISTIDINE_KEYS; do
            [ -z "$MEEKO_SET_TEMPLATE" ] || MEEKO_SET_TEMPLATE="$MEEKO_SET_TEMPLATE,"
            MEEKO_SET_TEMPLATE="$MEEKO_SET_TEMPLATE$HISTIDINE_KEY=$HISTIDINE_TEMPLATE"
            printf '%s\t%s\t%s\n' "$HISTIDINE_KEY" "$HISTIDINE_TEMPLATE" "user-selected after Meeko tautomer ambiguity" >> "$HISTIDINE_SELECTION_LOG"
          done
          log "Retrying Meeko with user-selected template assignment(s) $MEEKO_SET_TEMPLATE; detailed output -> $HISTIDINE_RETRY_LOG"
          build_meeko_receptor_command "$PREP_RECEPTOR_BIN" "$HISTIDINE_SOURCE" \
            "$RECEPTOR_DIR/${CANONICAL}" "$RECEPTOR_PDBQT" 0 '' "$MEEKO_SET_TEMPLATE"
          HISTIDINE_COMMAND=("${PREPARATION_COMMAND[@]}")
          if run_logged_preparation_command "$HISTIDINE_RETRY_LOG" "${HISTIDINE_COMMAND[@]}"; then
            PREP_SUCCESS=1
            PREP_ROUTE=guided_histidine_template
            cp "$HISTIDINE_SOURCE" "$RECEPTOR_PDB"
            log "Meeko preparation succeeded with user-selected histidine template assignment(s)"
          else
            HISTIDINE_DIAGNOSTIC_LOGS=("$HISTIDINE_RETRY_LOG")
          fi
        else
          echo "Meeko requires a histidine template for $HISTIDINE_RESIDUE. Review the local structure and rerun with MEEKO_SET_TEMPLATE=$HISTIDINE_RESIDUE=HIE, HID, or HIP." >&2
          break
        fi
      done
    fi

    # ADFRsuite is intentionally a narrow final fallback: Meeko has already
    # diagnosed an unsupported *linked* component, and the legacy preparer can
    # retain many such deposited adducts in a Vina-readable PDBQT. It is not a
    # generic rescue for glycans, nucleic acids, or metal/cofactor chemistry.
    if [ "$PREP_SUCCESS" = "1" ]; then
      record_adfr_fallback_status not_needed "A Meeko preparation or repair retry succeeded."
    elif [ "$ADFR_FALLBACK" != "1" ]; then
      record_adfr_fallback_status disabled "The configured ADFRsuite fallback is disabled."
    elif [ -z "$ADFR_FALLBACK_BIN" ]; then
      record_adfr_fallback_status unavailable "No ADFRsuite prepare_receptor executable was found; configure a compatible executable with DOCKING_UNIVERSAL_ADFR_FALLBACK_BIN for the eligible compatibility route."
    elif [ ! -x "$ADFR_FALLBACK_BIN" ]; then
      record_adfr_fallback_status unavailable "The configured ADFRsuite prepare_receptor is missing or not executable; check DOCKING_UNIVERSAL_ADFR_FALLBACK_BIN."
    elif [ -z "$RETAINED_LINKED_COMPONENTS" ] && ! grep -qs "linking fragments" "$RECEPTOR_BACKEND_LOG" "$PDBFIXER_MEEKO_LOG" "$RECEPTOR_RETRY_LOG" "$DISULFIDE_RETRY_LOG" 2>/dev/null; then
      record_adfr_fallback_status ineligible "No retained linked-component evidence or linked-fragment diagnosis permits the narrow compatibility route."
    else
      # Executable permission alone does not mean an old architecture-specific
      # wrapper can start. Probe help without passing coordinates or changing
      # preparation models. Failure must not replace the original diagnosis.
      if "$PYTHON_COMMAND" "$LIBEXEC_DIR/docking-universal-backend-startup.py" "$ADFR_FALLBACK_BIN" \
          "$RECEPTOR_DIR/adfr_startup_audit.json" --input "$RECEPTOR_FILTERED_PDB" > "$ADFR_FALLBACK_LOG" 2>&1; then
      log "Meeko rejected linked deposited chemistry; trying the legacy ADFRsuite receptor-preparation fallback; detailed output -> $ADFR_FALLBACK_LOG"
      build_adfr_linked_fallback_command "$ADFR_FALLBACK_BIN" "$RECEPTOR_FILTERED_PDB" "$RECEPTOR_PDBQT"
      ADFR_FALLBACK_COMMAND=("${PREPARATION_COMMAND[@]}")
      if run_logged_preparation_artifact "$ADFR_FALLBACK_LOG" "$RECEPTOR_PDBQT" "${ADFR_FALLBACK_COMMAND[@]}"; then
        if ! validate_adfr_preparation_output "$RECEPTOR_FILTERED_PDB" "$ADFR_FALLBACK_LOG"; then
          record_adfr_fallback_status validation_failed "The eligible ADFRsuite output failed validation: $ADFR_VALIDATION_DETAIL Inspect $ADFR_OUTPUT_AUDIT and $ADFR_VALIDATION_LOG."
          return 0
        fi
        PREP_SUCCESS=1
        PREP_ROUTE=adfr_legacy_linked_component_fallback
        cp "$RECEPTOR_FILTERED_PDB" "$RECEPTOR_PDB"
        record_adfr_fallback_status succeeded "The eligible legacy ADFRsuite command produced a receptor PDBQT."
        log "Legacy ADFRsuite preparation succeeded after Meeko's linked-component rejection; a target-matched control is required for the control-validated designation, while explicit user-reviewed exploratory approval remains available"
      else
        record_adfr_fallback_status failed "The eligible legacy ADFRsuite command did not produce a receptor PDBQT."
        log "Legacy ADFRsuite fallback did not produce a receptor PDBQT; retaining Meeko diagnostics for structural review"
      fi
      else
        record_adfr_fallback_status startup_failed "ADFRsuite failed its startup/compatibility probe; no receptor was passed to it. Inspect $RECEPTOR_DIR/adfr_startup_audit.json."
        log "Legacy ADFRsuite fallback unavailable: startup/compatibility check failed; no receptor was passed to it. See $RECEPTOR_DIR/adfr_startup_audit.json"
      fi
    fi
  else
    record_adfr_fallback_status primary_backend "ADFRsuite was selected as the primary backend and failed; there is no additional ADFRsuite fallback."
  fi
}

# Handle the explicit safety boundary after every non-destructive attempt fails.
# This is the only orchestration path allowed to omit unmatched components;
# it requires an interactive approval, records the exact removal manifest,
# escalates omitted standard residues, and otherwise preserves the failure.
# Protected by failure-diagnosis, removal-manifest, and route tests.
handle_receptor_failure_and_removal_approval() {
if [ "$PREP_SUCCESS" = "0" ]; then
  FAILURE_DIAGNOSIS="$RECEPTOR_DIR/receptor_failure_diagnosis.txt"
  PREPARATION_INTERVENTION="$RECEPTOR_DIR/preparation_intervention.json"
  FAILURE_LOGS=("$ADFR_VALIDATION_LOG" "$ADFR_FALLBACK_LOG" "$DISULFIDE_RETRY_LOG" "$RECEPTOR_RETRY_LOG" "$PDBFIXER_MEEKO_LOG" "$PDBFIXER_LOG" "$RECEPTOR_BACKEND_LOG")
  write_receptor_failure_diagnosis "$INPUT_PDB" "$RECEPTOR_FILTERED_PDB" "$FAILURE_DIAGNOSIS" "${FAILURE_LOGS[@]}"
  # Noninteractive GUI workers need a useful terminal error too. The complete
  # explanation stays in the retained diagnosis, without authorizing a repair.
  printf 'ERROR: %s\n' "$(head -n1 "$FAILURE_DIAGNOSIS")" >&2
  grep '^Detected detail:' "$FAILURE_DIAGNOSIS" >&2 || :
  printf 'ADFRsuite fallback: %s; %s\n' "$ADFR_FALLBACK_STATUS" "$ADFR_FALLBACK_REASON" >&2
  INTERVENTION_HELPER="$LIBEXEC_DIR/docking-universal-preparation-intervention.py"
  if [ -f "$INTERVENTION_HELPER" ]; then
    HISTIDINE_RESIDUE=$(ambiguous_histidine_residue "${FAILURE_LOGS[@]}")
    INTERVENTION_ARGS=(
      --diagnosis "$FAILURE_DIAGNOSIS"
      --filtered-receptor "$RECEPTOR_FILTERED_PDB"
      --output "$PREPARATION_INTERVENTION"
      --ambiguous-histidine "$HISTIDINE_RESIDUE"
    )
    for INTERVENTION_LOG in "${FAILURE_LOGS[@]}"; do
      [ ! -s "$INTERVENTION_LOG" ] || INTERVENTION_ARGS+=(--diagnostic-log "$INTERVENTION_LOG")
    done
    if [ -n "${DOCKING_UNIVERSAL_SOURCE_MMCIF:-}" ] && [ -f "$DOCKING_UNIVERSAL_SOURCE_MMCIF" ]; then
      INTERVENTION_ARGS+=(--source-mmcif "$DOCKING_UNIVERSAL_SOURCE_MMCIF")
    fi
    "$PYTHON_COMMAND" "$INTERVENTION_HELPER" "${INTERVENTION_ARGS[@]}" || {
      echo "WARNING: structured preparation intervention could not be written" >&2
    }
    retain_adfr_fallback_status "$PREPARATION_INTERVENTION"
  fi

  # Omitting unmatched components changes the receptor model. It is a final,
  # explicit user choice, never an automatic preparation retry.
  if [ "$PREP_BACKEND" = "meeko" ] && [ -t 0 ] && [ "${DOCKING_UNIVERSAL_REMOVAL_PROMPT:-1}" = "1" ]; then
    cat >&2 <<EOF

No further safe automatic receptor-preparation fallback succeeded.
Docking Universal can make one final, model-changing attempt by omitting
unmatched residues/components and selecting alternate location A. This can
remove complete standard protein/peptide residues, not only missing atoms or
optional hetero components. The current diagnosis is shown below. A successful
attempt still requires structural review and a bound-ligand control before screening.
EOF
    cat "$FAILURE_DIAGNOSIS" >&2
    printf 'Proceed with user-approved component removal? [y/N] ' >&2
    read -r USER_APPROVES_REMOVAL || USER_APPROVES_REMOVAL=""
    case "$USER_APPROVES_REMOVAL" in
      y|Y|yes|YES|Yes)
        USER_REMOVAL_LOG="$RECEPTOR_DIR/receptor_user_approved_removal.log"
        USER_REMOVAL_RECORD="$RECEPTOR_DIR/user_approved_component_removal.txt"
        USER_REMOVAL_MANIFEST="$RECEPTOR_DIR/user_approved_component_removal.tsv"
        build_meeko_receptor_command "$PREP_RECEPTOR_BIN" "$RECEPTOR_FILTERED_PDB" \
          "$RECEPTOR_DIR/${CANONICAL}" "$RECEPTOR_PDBQT" 1 A "$MEEKO_SET_TEMPLATE"
        USER_REMOVAL_COMMAND=("${PREPARATION_COMMAND[@]}")
        log "Running user-approved component-removal attempt."
        if run_logged_preparation_artifact "$USER_REMOVAL_LOG" "$RECEPTOR_PDBQT" "${USER_REMOVAL_COMMAND[@]}"; then
          PREP_SUCCESS=1
          PREP_ROUTE=meeko_user_approved_component_removal
          cp "$RECEPTOR_FILTERED_PDB" "$RECEPTOR_PDB"
          write_removed_component_manifest "$RECEPTOR_PDBQT" "$RECEPTOR_FILTERED_PDB" "$USER_REMOVAL_MANIFEST"
          REMOVED_COMPONENT_COUNT=$(awk 'NR > 1 { n++ } END { print n+0 }' "$USER_REMOVAL_MANIFEST")
          REMOVED_STANDARD_AMINO_COUNT=$(awk -F '\t' 'NR > 1 && $4 ~ /^(ALA|ARG|ASN|ASP|CYS|GLN|GLU|GLY|HIS|ILE|LEU|LYS|MET|PHE|PRO|SER|THR|TRP|TYR|VAL)$/ { n++ } END { print n+0 }' "$USER_REMOVAL_MANIFEST")
          REMOVED_COMPONENT_SUMMARY=$(awk -F '\t' 'NR > 1 { printf "%s%s:%s%s (%s)", (n++ ? ", " : ""), ($1 == "" ? "[blank]" : $1), $2, $3, $4 }' "$USER_REMOVAL_MANIFEST")
          {
            printf 'User approved component removal after safe preparation fallbacks failed.\n'
            printf 'Removed residue/component count: %s\n' "$REMOVED_COMPONENT_COUNT"
            printf 'Removed standard amino-acid residue count: %s\n' "$REMOVED_STANDARD_AMINO_COUNT"
            printf 'Removed residues/components: %s\n' "${REMOVED_COMPONENT_SUMMARY:-none detected by residue comparison}"
            if [ "$REMOVED_STANDARD_AMINO_COUNT" -gt 0 ]; then
              printf 'HIGH-SEVERITY STRUCTURAL WARNING: standard protein/peptide residues were omitted from the final receptor.\n'
            fi
            printf 'Removal manifest: %s\n' "$USER_REMOVAL_MANIFEST"
            printf 'Command: '
            printf '%q ' "${USER_REMOVAL_COMMAND[@]}"
            printf '\nLog: %s\n' "$USER_REMOVAL_LOG"
            printf 'Control redocking is required before prospective screening.\n'
          } > "$USER_REMOVAL_RECORD"
          cat "$USER_REMOVAL_RECORD" >&2
          log "User-approved component-removal attempt succeeded; control redocking is required before screening."
        else
          log "User-approved component-removal attempt did not succeed; retaining the original failure."
        fi
        ;;
      *) log "User declined component removal; receptor preparation remains stopped." ;;
    esac
  fi

  if [ "$PREP_SUCCESS" = "1" ]; then
    :
  else
  echo "ERROR: receptor preparation failed after all enabled quick attempts." >&2
  cat "$FAILURE_DIAGNOSIS" >&2
  echo "Failure explanation saved to: $FAILURE_DIAGNOSIS" >&2
  tail -40 "$ADFR_FALLBACK_LOG" 2>/dev/null || tail -40 "$DISULFIDE_RETRY_LOG" 2>/dev/null || tail -40 "$RECEPTOR_RETRY_LOG" 2>/dev/null || tail -40 "$PDBFIXER_MEEKO_LOG" 2>/dev/null || tail -40 "$RECEPTOR_BACKEND_LOG" >&2
  echo "Initial backend log: $RECEPTOR_BACKEND_LOG" >&2
  [ "$PDBFIXER_USED" = "0" ] || echo "Post-PDBFixer backend log: $PDBFIXER_MEEKO_LOG" >&2
  [ -s "$RECEPTOR_RETRY_LOG" ] && echo "Batch-retry backend log: $RECEPTOR_RETRY_LOG" >&2
  [ -s "$DISULFIDE_RETRY_LOG" ] && echo "Disulfide-template retry log: $DISULFIDE_RETRY_LOG" >&2
  [ -s "$ADFR_FALLBACK_LOG" ] && echo "Legacy ADFRsuite fallback log: $ADFR_FALLBACK_LOG" >&2
  exit 1
  fi
fi
}
