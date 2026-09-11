#!/usr/bin/env bash

# Compatibility loader for the receptor-preparation function library.
#
# Scientific and presentation responsibilities live in separate, purpose-named
# modules under docking-universal-prepare.d. Keeping this stable entry point
# preserves source-tree and installed-copy behavior while preventing another
# monolithic support script from replacing the original workflow monolith.

PREPARE_LIBRARY_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/docking-universal-prepare.d"
for prepare_module in interaction runtime receptor ligands pockets artifacts; do
  prepare_module_path="$PREPARE_LIBRARY_DIR/${prepare_module}.sh"
  [ -r "$prepare_module_path" ] || {
    printf 'ERROR: receptor preparation module is missing: %s\n' "$prepare_module_path" >&2
    return 2 2>/dev/null || exit 2
  }
  . "$prepare_module_path"
done
unset prepare_module prepare_module_path
