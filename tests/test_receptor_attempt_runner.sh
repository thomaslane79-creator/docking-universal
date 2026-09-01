#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-attempt-runner.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

run_logged_preparation_command "$tmp/success.log" sh -c 'printf "diagnostic output\n"; exit 0'
grep -q 'diagnostic output' "$tmp/success.log" || fail "successful command log was not retained"
if run_logged_preparation_command "$tmp/failure.log" sh -c 'printf "failure detail\n" >&2; exit 7'; then
  fail "failed command was reported as successful"
fi
grep -q 'failure detail' "$tmp/failure.log" || fail "failed command diagnostics were not retained"

run_logged_preparation_artifact "$tmp/artifact.log" "$tmp/receptor.pdbqt" sh -c 'printf "ATOM\n" > "$1"' _ "$tmp/receptor.pdbqt" || fail "valid artifact attempt failed"
if run_logged_preparation_artifact "$tmp/empty.log" "$tmp/empty.pdbqt" sh -c ': > "$1"' _ "$tmp/empty.pdbqt"; then
  fail "empty required artifact was accepted"
fi

printf 'PASS: receptor attempt-runner checks\n'
