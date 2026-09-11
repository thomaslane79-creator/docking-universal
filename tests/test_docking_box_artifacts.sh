#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/docking-universal-box-artifacts.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
. "$root/libexec/docking-universal-prepare-support.sh"
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

write_docking_box_artifacts "$tmp/center.pdb" "$tmp/box.pdb" "$tmp/box.conf" \
  '2026-08-31 12:00:00' '/data/example.pdb' 10.0 -2.0 5.5 26.0 13.0

[ "$(grep -c '^HETATM' "$tmp/center.pdb")" -eq 1 ] || fail "center marker inventory changed"
awk '/^HETATM/{x=substr($0,31,8)+0;y=substr($0,39,8)+0;z=substr($0,47,8)+0;exit !(x==10&&y==-2&&z==5.5)}' "$tmp/center.pdb" || fail "center marker coordinates changed"
[ "$(grep -c '^ATOM' "$tmp/box.pdb")" -eq 8 ] || fail "box corner inventory changed"
[ "$(grep -c '^CONECT' "$tmp/box.pdb")" -eq 8 ] || fail "box connectivity inventory changed"

awk '
  /^ATOM/ {
    x=substr($0,31,8)+0;y=substr($0,39,8)+0;z=substr($0,47,8)+0
    if(n==0||x<minx)minx=x;if(n==0||x>maxx)maxx=x
    if(n==0||y<miny)miny=y;if(n==0||y>maxy)maxy=y
    if(n==0||z<minz)minz=z;if(n==0||z>maxz)maxz=z;n++
  }
  END { exit !(minx==-3&&maxx==23&&miny==-15&&maxy==11&&minz==-7.5&&maxz==18.5) }
' "$tmp/box.pdb" || fail "box boundaries no longer match center plus/minus half-width"

grep -q '^center_x = 10.0$' "$tmp/box.conf" || fail "configuration X center changed"
grep -q '^center_y = -2.0$' "$tmp/box.conf" || fail "configuration Y center changed"
grep -q '^center_z = 5.5$' "$tmp/box.conf" || fail "configuration Z center changed"
[ "$(grep -c '^size_[xyz] = 26.0$' "$tmp/box.conf")" -eq 3 ] || fail "configuration dimensions changed"
grep -q '^# Input: /data/example.pdb$' "$tmp/box.conf" || fail "configuration provenance changed"

printf 'PASS: docking-box artifact equivalence checks\n'
