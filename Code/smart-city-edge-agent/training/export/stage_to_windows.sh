#!/usr/bin/env bash
# Copy an exported Genie bundle out of the WSL image onto C:, so Windows adb.exe can push it.
# adb.exe cannot read /home/... paths, and the \\wsl$ UNC route gets mangled by shell escaping,
# so a plain copy to /mnt/c is the reliable path.
#
#   bash stage_to_windows.sh <wsl_export_out_dir> <windows_stage_dir>
set -eu
SRC_ROOT=${1:?need export out dir}
DST=${2:-/mnt/c/Users/hp/Desktop/qidk/_stage_bundle}

B=$(find "$SRC_ROOT" -maxdepth 1 -mindepth 1 -type d | head -1)
[ -n "$B" ] || { echo "no bundle dir under $SRC_ROOT"; exit 1; }
echo "src: $B"

mkdir -p "$DST"
rm -f "$DST"/*.bin "$DST"/*.json 2>/dev/null || true

for f in "$B"/*.bin "$B"/genie_config.json "$B"/htp_backend_ext_config.json "$B"/tokenizer.json; do
  [ -f "$f" ] || continue
  echo "  copy $(basename "$f") ($(stat -c %s "$f") bytes)"
  cp -f "$f" "$DST/"
done

echo "--- staged on C: ---"
ls -la "$DST"
df -h /mnt/c | tail -1
