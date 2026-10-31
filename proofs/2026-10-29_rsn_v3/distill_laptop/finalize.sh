#!/bin/bash
# finalize.sh <outdir>: select_distill (copied from kaggle/) on the raw samples -> chat3_distilled.jsonl (+ md5) and
# per-kind reports for train and dev. Unsampled train questions (time-limited run) get the templated reference row.
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/distill_laptop; V=$D/..; OUT=$1
source ~/venvs/rsn/bin/activate; cd $D
python select_distill.py --records $V/data/chat3_train.jsonl --raw $OUT/raw_train.jsonl --out $OUT/chat3_distilled.jsonl \
  --report $OUT/select_report_train.json --fallback-unsampled
[ -s $OUT/raw_dev.jsonl ] && python select_distill.py --records $V/data/chat3_dev.jsonl --raw $OUT/raw_dev.jsonl \
  --out $OUT/chat3_dev_distilled.jsonl --report $OUT/select_report_dev.json
(cd $OUT && md5sum chat3_distilled.jsonl > chat3_distilled.jsonl.md5)
python - $OUT <<'PY'
import json, sys, os
o = sys.argv[1]
L = ["# Per-kind distillation report", ""]
for s in ("train", "dev"):
    p = os.path.join(o, "select_report_%s.json" % s)
    if not os.path.exists(p):
        continue
    r = json.load(open(p))
    L += ["## %s: %d records, %d sampled, %d rows %s" % (s, r["records"], r["sampled"], r["rows_out"], r["by_source"]),
          "sample pass %.3f, question pass %.3f, long kept %d / dropped %d, fallback %d, unsampled %d; hard think tokens kept %s" % (
          r["sample_pass_rate"], r["question_pass_rate"], r["long_kept"], r["long_dropped"], r["fallback"], r["unsampled"], r["hard_think_tokens_kept"]),
          "", "| kind | hard | records | samples | pass | sample pass | question pass | kept | long_kept | fallback |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, st in r["per_kind"].items():
        L.append("| %s | %d | %d | %d | %d | %.3f | %.3f | %d | %d | %d |" % (k, st["hard"], st["records"], st.get("samples", 0), st.get("pass", 0),
                 st["sample_pass_rate"], st["question_pass_rate"], st.get("kept", 0), st.get("long_kept", 0), st.get("fallback", 0)))
    L += ["", "fail reasons: %s" % r["fail_reasons"], ""]
open(os.path.join(o, "REPORT.md"), "w").write("\n".join(L) + "\n")
print("\n".join(L[:6]))
PY
echo FINALIZE_DONE
