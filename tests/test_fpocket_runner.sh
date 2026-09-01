#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-fpocket-runner.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

printf 'ATOM\n' > "$tmp/input.pdb"
cat > "$tmp/fpocket" <<'EOF'
#!/usr/bin/env bash
set -eu
input=''; printf '%s\n' "$@" > "${FPOCKET_ARGS:?}"
while [ "$#" -gt 0 ]; do case "$1" in -f) input="$2";shift 2;;*)shift;;esac;done
mkdir -p "${input%.pdb}_out/pockets"
printf 'result\n' > "${input%.pdb}_out/pockets/pocket1_atm.pdb"
EOF
chmod +x "$tmp/fpocket"

FPOCKET_ARGS="$tmp/default.args" run_fpocket_to_directory "$tmp/fpocket" "$tmp/input.pdb" '' "$tmp/conservative"
[ -s "$tmp/conservative/pockets/pocket1_atm.pdb" ] || fail "conservative fpocket output was not normalized"
! grep -q '^-m$' "$tmp/default.args" || fail "conservative run unexpectedly supplied a probe override"

FPOCKET_ARGS="$tmp/expanded.args" run_fpocket_to_directory "$tmp/fpocket" "$tmp/input.pdb" 2.5 "$tmp/expanded"
[ -s "$tmp/expanded/pockets/pocket1_atm.pdb" ] || fail "expanded fpocket output was not normalized"
grep -A1 '^-m$' "$tmp/expanded.args" | grep -q '2.5' || fail "expanded probe value changed"

printf 'PASS: fpocket runner checks\n'
