#!/usr/bin/env bash
# kaggle_shim.sh: offline stand-in for the kaggle CLI 2.2.4 (adapted from the 4B baton test shim). No network.
# State in $SHIM: ds/<slug>/, kernel/ (pushed code + working/), quota (h left), lag (download calls that still serve the previous
# version), calls.log. A pushed kernel "runs" (fake_session.sh = the REAL agt3_kernel.py on CPU) at the first `kernels status`.
set -u
S=${SHIM:?SHIM dir}; mkdir -p "$S/ds" "$S/kernel"
echo "$*" >> "$S/calls.log"
case "$1 ${2:-}" in
"config view") echo "- username: shimuser" ;;
"quota -v") echo "resource,used,remaining,total,refreshAt"; q=$(cat "$S/quota" 2>/dev/null || echo 30)
  echo "GPU,0h,${q}h,30.00h,$(date -u -d '+3 days' +%FT%T+00:00)" ;;
"datasets status") slug=${3#*/}; [ -d "$S/ds/$slug" ] && echo ready || { echo "404 Client Error: Not Found"; exit 1; } ;;
"datasets create"|"datasets version")
  shift 2; p=.; while [ $# -gt 0 ]; do case $1 in -p) p=$2; shift 2;; -u) echo "shim: PUBLIC refused"; exit 3;; -m) shift 2;; *) shift;; esac; done
  slug=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['id'].split('/')[1])" "$p/dataset-metadata.json")
  rm -rf "$S/prev_$slug"; [ -d "$S/ds/$slug" ] && cp -r "$S/ds/$slug" "$S/prev_$slug"
  cat "$S/lag" > "$S/lag_left_$slug" 2>/dev/null || echo 0 > "$S/lag_left_$slug"
  rm -rf "$S/ds/$slug"; mkdir -p "$S/ds/$slug"
  find "$p" -maxdepth 1 \( -type f -o -type l \) ! -name dataset-metadata.json -exec cp -L {} "$S/ds/$slug/" \;
  echo "$slug private $(du -sk "$S/ds/$slug" | cut -f1)KB $(date +%s)" >> "$S/uploads.log"
  echo "Dataset version is being created." ;;
"datasets download")
  slug=${3#*/}; shift 3; f=; p=.; while [ $# -gt 0 ]; do case $1 in -f) f=$2; shift 2;; -p) p=$2; shift 2;; *) shift;; esac; done
  src=$S/ds/$slug/$f; l=$(cat "$S/lag_left_$slug" 2>/dev/null || echo 0)
  if [ "$l" -gt 0 ]; then echo $((l - 1)) > "$S/lag_left_$slug"; src=$S/prev_$slug/$f; fi
  [ -f "$src" ] || { echo "404 Client Error: Not Found"; exit 1; }; cp "$src" "$p/$f" ;;
"kernels push")
  shift 2; p=.; while [ $# -gt 0 ]; do case $1 in -p) p=$2; shift 2;; *) shift;; esac; done
  python3 -c "import json,sys;m=json.load(open(sys.argv[1]));assert m['is_private'] is True" "$p/kernel-metadata.json" || { echo "shim: kernel not private"; exit 3; }
  rm -rf "$S/kernel"; mkdir -p "$S/kernel/working"; cp "$p"/* "$S/kernel/"
  v=$(( $(cat "$S/kver" 2>/dev/null || echo 0) + 1 )); echo $v > "$S/kver"; echo new > "$S/kernel/state"
  echo "Kernel version $v successfully pushed.  Please check progress at https://www.kaggle.com/code/shimuser/x" ;;
"kernels status")
  case $(cat "$S/kernel/state" 2>/dev/null || echo none) in
    new) bash "$(dirname "$0")/fake_session.sh" "$S" > "$S/kernel/session.out" 2>&1; echo done > "$S/kernel/state"
         echo "$3 has status \"KernelWorkerStatus.RUNNING\"" ;;
    done) echo "$3 has status \"KernelWorkerStatus.COMPLETE\"" ;;
    *) echo "404 Client Error: Not Found"; exit 1 ;;
  esac ;;
"kernels output")
  shift 3; p=.; while [ $# -gt 0 ]; do case $1 in -p) p=$2; shift 2;; *) shift;; esac; done
  cp -r "$S/kernel/working/." "$p/"; cp "$S/kernel/session.out" "$p/agt3-train.log" ;;
*) echo "shim: unsupported: $*"; exit 2 ;;
esac
