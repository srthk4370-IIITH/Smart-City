#!/usr/bin/env bash
# kaggle_shim.sh: offline stand-in for the `kaggle` CLI (kaggle 2.2.4 output formats) for test/run_tests.sh. No network.
# State in $SHIM: ds/<slug>/ (dataset files), kernel/ (pushed code + working/), quota (hours left), push (ok|quota|error),
# session (ok|killed|stale), lag (download calls that still see the previous version), zipdl, quota_after_push (quota once a push succeeded), calls.log. A pushed kernel "runs" at the first `kernels status` call (test/fake_session.sh).
set -u
S=${SHIM:?SHIM dir}; mkdir -p "$S/ds" "$S/kernel"
echo "$*" >> "$S/calls.log"
case "$1 ${2:-}" in
"config view") echo "- username: shimuser"; echo "- path: None" ;;
"quota -v") echo "resource,used,remaining,total,refreshAt"; q=$(cat "$S/quota" 2>/dev/null || echo 30)
  echo "GPU,$(awk -v q="$q" 'BEGIN{printf "%.2f", 30-q}')h,${q}h,30.00h,$(date -u -d '+3 days' +%FT%T+00:00)" ;;
"datasets status") slug=${3#*/}; [ -d "$S/ds/$slug" ] && echo ready || { echo "404 Client Error: Not Found"; exit 1; } ;;
"datasets create"|"datasets version")
  shift 2; p=.; priv=private
  while [ $# -gt 0 ]; do case $1 in -p) p=$2; shift 2;; -u) priv=PUBLIC; shift;; -m) shift 2;; *) shift;; esac; done
  slug=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['id'].split('/')[1])" "$p/dataset-metadata.json")
  [ -f "$S/ds/$slug/baton_cfg.json" ] && cp "$S/ds/$slug/baton_cfg.json" "$S/prev_cfg_$slug.json"   # what Kaggle still serves while processing
  cat "$S/lag" > "$S/lag_left_$slug" 2>/dev/null || echo 0 > "$S/lag_left_$slug"
  rm -rf "$S/ds/$slug"; mkdir -p "$S/ds/$slug"
  find "$p" -maxdepth 1 -type f ! -name dataset-metadata.json -exec cp {} "$S/ds/$slug/" \;   # -r skip: files only
  echo "$slug $priv $(date +%s)" >> "$S/uploads.log"
  echo "Dataset version is being created. Please check progress at https://www.kaggle.com/datasets/shimuser/$slug" ;;
"datasets download")       # -f FILE -p DIR: serves the previous version's file for $S/lag calls after a new version; $S/zipdl -> .zip
  slug=${3#*/}; shift 3; f=; p=.
  while [ $# -gt 0 ]; do case $1 in -f) f=$2; shift 2;; -p) p=$2; shift 2;; *) shift;; esac; done
  src=$S/ds/$slug/$f; l=$(cat "$S/lag_left_$slug" 2>/dev/null || echo 0)
  if [ "$l" -gt 0 ]; then echo $((l - 1)) > "$S/lag_left_$slug"; src=$S/prev_cfg_$slug.json; fi
  [ -f "$src" ] || { echo "404 Client Error: Not Found"; exit 1; }
  if [ -e "$S/zipdl" ]; then python3 -c "import zipfile,sys;z=zipfile.ZipFile(sys.argv[2],'w');z.write(sys.argv[1],sys.argv[3]);z.close()" "$src" "$p/$f.zip" "$f"
  else cp "$src" "$p/$f"; fi ;;
"kernels push")
  shift 2; p=.
  while [ $# -gt 0 ]; do case $1 in -p) p=$2; shift 2;; *) shift;; esac; done
  case "$(cat "$S/push" 2>/dev/null || echo ok)" in
    quota) echo "Kernel push error: Maximum weekly GPU quota of 30 hours exceeded"; exit 0 ;;
    error) echo "Kernel push error: Internal server error"; exit 0 ;;
  esac
  rm -rf "$S/kernel"; mkdir -p "$S/kernel/working"; cp "$p"/* "$S/kernel/"
  [ -s "$S/quota_after_push" ] && mv "$S/quota_after_push" "$S/quota"     # quota used up by this session
  v=$(( $(cat "$S/kver" 2>/dev/null || echo 0) + 1 )); echo $v > "$S/kver"; echo new > "$S/kernel/state"
  echo "Kernel version $v successfully pushed.  Please check progress at https://www.kaggle.com/code/shimuser/x" ;;
"kernels status")
  st=$(cat "$S/kernel/state" 2>/dev/null || echo none)
  case $st in
    new) bash "$(dirname "$0")/fake_session.sh" "$S" > "$S/kernel/session.out" 2>&1; echo done > "$S/kernel/state"
         echo "$3 has status \"KernelWorkerStatus.RUNNING\"" ;;
    done) echo "$3 has status \"KernelWorkerStatus.COMPLETE\"" ;;
    *) echo "404 Client Error: Not Found"; exit 1 ;;
  esac ;;
"kernels output")
  shift 3; p=.
  while [ $# -gt 0 ]; do case $1 in -p) p=$2; shift 2;; *) shift;; esac; done
  cp -r "$S/kernel/working/." "$p/"; cp "$S/kernel/session.out" "$p/rsn3-r3-baton-train.log"
  echo "Output file downloaded to $p" ;;
*) echo "shim: unsupported: $*"; exit 2 ;;
esac
