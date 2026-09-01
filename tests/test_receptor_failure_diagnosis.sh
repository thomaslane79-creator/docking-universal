#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-failure-diagnosis.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

base="$tmp/base.pdb"
printf 'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\n' > "$base"

check_case() {
  name="$1"; expected="$2"; input="$3"; filtered="$4"; message="$5"
  log="$tmp/$name.log"; out="$tmp/$name.txt"
  printf '%s\n' "$message" > "$log"
  write_receptor_failure_diagnosis "$input" "$filtered" "$out" "$log"
  grep -q "^Receptor preparation failure category: $expected$" "$out" || {
    cat "$out" >&2
    fail "$name classification changed"
  }
}

check_case heme 'Unsupported heme or cofactor template' "$base" "$base" "resname='HEM' not in residue_templates"

cp "$base" "$tmp/nucleic.pdb"
printf 'HETATM    2  P    DA B   7       1.000   0.000   0.000  1.00 20.00           P\n' >> "$tmp/nucleic.pdb"
check_case nucleic 'DNA/RNA or mixed protein-nucleic-acid template conflict' "$tmp/nucleic.pdb" "$tmp/nucleic.pdb" 'Template matching failed for: DA'
grep -q 'Detected DNA/RNA residues: B:7=DA' "$tmp/nucleic.txt" || fail "nucleic-acid detail changed"

check_case altloc 'Alternate-location and residue-template conflict' "$base" "$base" $'Requested altlocs not found\nTemplate matching failed for: ALA'

cp "$base" "$tmp/modified.pdb"
printf 'MODRES 1ABC CSO A   2   CYS  S-HYDROXYCYSTEINE\n' >> "$tmp/modified.pdb"
check_case modified 'Unsupported non-standard amino acid' "$tmp/modified.pdb" "$base" 'Template matching failed for: CSO'
grep -q 'Detected modified amino acids: A:2=CSO (declared as CYS)' "$tmp/modified.txt" || fail "MODRES detail changed"

check_case incomplete 'Incomplete or template-mismatched residue' "$base" "$base" 'heavy_miss=2'
check_case unclassified 'Unclassified receptor-template failure' "$base" "$base" 'unexpected backend failure'

printf 'PASS: receptor failure-diagnosis characterization checks\n'
