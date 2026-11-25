#!/bin/sh
# Rebuild dist: home page + copies of both viewers. Run from anywhere.
set -e
D=$(cd "$(dirname "$0")" && pwd); R="$D/../Code/smart-city-edge-agent"
[ -f "$R/fleet-viewer/dist/config.js" ] || sh "$R/fleet-viewer/make_config.sh"
rm -rf "$D/dist"; mkdir -p "$D/dist/report" "$D/dist/fleet"
cp -r "$D/src/." "$D/dist/"
cp -r "$R/report-viewer/dist/." "$D/dist/report/"
cp -r "$R/fleet-viewer/dist/." "$D/dist/fleet/"
printf '/report /report/ 301\n/fleet /fleet/ 301\n' > "$D/dist/_redirects"
echo built "$D/dist"
