#!/usr/bin/env bash
# select.sh: checkpoint selection on the DEPLOYED form (V3_DESIGN.md §5.1; D6 lesson: never on HF loss). Every run/snap_XXXX
# not scored yet -> export.sh (merged Q4_0, shared imatrix) -> hosteval.py on the first 600 DEV600 rows (host GPU, GPU lock) ->
# post/snap_XXXX/dev_score.json. Then post/selection.json: scores by step, best, evals since best, stop (PATIENCE evals without
# a gain of MIN_GAIN). Q4_0 files of non-best snapshots are deleted after scoring (disk). Exit 0, or 2 on a failed export/eval.
source "$(dirname "$(readlink -f "$0")")/lib.sh"
EXPORT=${EXPORT_CMD:-bash $A/export.sh}
EVAL=${EVAL_CMD:-python3 $A/hosteval.py}
trap gpu_release EXIT
for d in $(ls -d "$R"/snap_* 2>/dev/null | sort); do
  t=$(basename "$d"); P=$POST/$t
  [ -s "$P/dev_score.json" ] && continue
  [ -e "$STOPF" ] && exit 0
  status "selection: exporting $t (merged Q4_0, shared imatrix)"
  $EXPORT "$d" "$t" shared || { status "export of $t failed (see $P/export.log)"; exit 2; }
  gpu_take || exit 0
  $EVAL --model "$P/agt3_${t}_q4_0.gguf" --rows "$DEV600" --limit 600 --out "$P/dev_samples.jsonl" > "$P/dev_eval.log" 2>&1
  e=$?; gpu_release
  [ $e = 0 ] || { status "dev eval of $t failed: $(tail -n 2 "$P/dev_eval.log" | tr '\n' ' ')"; exit 2; }
  python3 - "$P/dev_samples.jsonl" "$P/dev_score.json" "$A/kaggle" <<'P'
import json, sys
sys.path.insert(0, sys.argv[3]); import rows as RW
s = [json.loads(l) for l in open(sys.argv[1])]
agg = {k: round(sum(bool(x[k]) for x in s if x.get(k) is not None) / max(1, sum(x.get(k) is not None for x in s)), 4)
       for k in ("json", "status", "pattern", "cause", "dq")}
json.dump(dict(score=round(RW.gen_score(s), 5), n=len(s), **agg), open(sys.argv[2], "w"), indent=1)
P
  status "selection: $t dev score $(python3 -c "import json;d=json.load(open('$P/dev_score.json'));print(d['score'], {k: d[k] for k in ('status','pattern','dq','json')})")"
done
python3 - "$POST" "$PATIENCE" "${MIN_GAIN:-0.002}" <<'P'
import glob, json, os, sys
post, pat, mg = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
sc = {}
for f in glob.glob(post + "/snap_*/dev_score.json"):
    sc[int(os.path.basename(os.path.dirname(f))[5:])] = json.load(open(f))
best, bs, since = None, None, 0
for s in sorted(sc):
    v = sc[s]["score"]
    if best is None or v > best + mg:
        best, bs, since = v, s, 0
    else:
        since += 1
sel = {"scores": {str(k): sc[k] for k in sorted(sc)}, "best_step": bs, "best": best, "since_best": since, "stop": since >= pat,
       "best_gguf": post + "/snap_%04d/agt3_snap_%04d_q4_0.gguf" % (bs, bs) if bs is not None else None}
json.dump(sel, open(post + "/selection.json", "w"), indent=1)
for s in sc:                       # disk: keep only the best snapshot's Q4_0 (the others can be rebuilt from run/snap_*)
    if s != bs:
        for g in glob.glob(post + "/snap_%04d/*.gguf" % s):
            os.remove(g)
print(json.dumps({k: sel[k] for k in ("best_step", "best", "since_best", "stop")}))
P
