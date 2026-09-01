#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$root/libexec/docking-universal-prepare-support.sh"
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

assert_array() {
  expected="$1"; shift
  actual=$(printf '%s\n' "${PREPARATION_COMMAND[@]}")
  [ "$actual" = "$expected" ] || { printf 'Expected:\n%s\nActual:\n%s\n' "$expected" "$actual" >&2; fail "$*"; }
}

build_meeko_receptor_command meeko receptor.pdb prefix receptor.pdbqt 0 '' ''
assert_array $'meeko\n--read_pdb\nreceptor.pdb\n-o\nprefix\n-p\nreceptor.pdbqt' "strict Meeko command changed"

build_meeko_receptor_command meeko receptor.pdb prefix receptor.pdbqt 1 A 'A:1=HIE,B:2=CYX'
assert_array $'meeko\n--read_pdb\nreceptor.pdb\n-o\nprefix\n-p\nreceptor.pdbqt\n--allow_bad_res\n--default_altloc\nA\n--set_template\nA:1=HIE,B:2=CYX' "explicit Meeko options changed"

build_adfr_receptor_command adfr receptor.pdb receptor.pdbqt
assert_array $'adfr\n-r\nreceptor.pdb\n-o\nreceptor.pdbqt\n-A\nnone\n-U\nwaters' "ADFR primary command changed"

build_adfr_linked_fallback_command adfr receptor.pdb receptor.pdbqt
assert_array $'adfr\n-r\nreceptor.pdb\n-o\nreceptor.pdbqt\n-A\ncheckhydrogens' "ADFR linked-component fallback changed"

printf 'PASS: receptor command-builder checks\n'
