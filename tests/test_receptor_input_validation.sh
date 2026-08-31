#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-receptor-input.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

mock_tool="$tmp/mock-tool"
printf '#!/usr/bin/env bash\nexit 0\n' > "$mock_tool"
chmod +x "$mock_tool"
printf 'this is not a PDB\nand contains no coordinate records\n' > "$tmp/garbage.pdb"

set +e
(cd "$tmp" && printf '\n' | env \
  DOCKING_UNIVERSAL_FPOCKET="$mock_tool" \
  DOCKING_UNIVERSAL_PREP_RECEPTOR="$mock_tool" \
  DOCKING_UNIVERSAL_PREP_BACKEND=meeko \
  "$root/libexec/docking-universal-prepare" "$tmp/garbage.pdb") \
  > "$tmp/stdout" 2> "$tmp/stderr"
status=$?
set -e

[ "$status" -ne 0 ] || fail "invalid receptor returned success"
combined=$(cat "$tmp/stdout" "$tmp/stderr")
case "$combined" in
  *"no valid protein ATOM records"*) ;;
  *) fail "invalid receptor did not produce a domain-level error" ;;
esac
case "$combined" in
  *"How much feedback"*) fail "feedback prompt appeared before input validation" ;;
esac
[ ! -e "$tmp/garbage_receptor_prep" ] || fail "invalid receptor created preparation artifacts"

printf 'PASS: receptor input validation checks\n'
