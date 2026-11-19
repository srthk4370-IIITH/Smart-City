#!/usr/bin/env bash
# make_data.sh: rsn_v3 training data on the laptop (CPU, stdlib python3) -> kaggle/build/$RUN_ID/data/
#   1. chat3: pipeline/run_all.sh (tools_v4.json, chat3_{train,dev}.jsonl, verifier self-test)  [SKIP_CHAT=1 to keep the
#      current files, e.g. while another agent owns them]; then the verify_chat self-test must PASS; md5 of every chat source
#   2. incidents: gen_incidents_v3.py (round-1 generator, new seed, weak families x3, verify.py pass only, ~12k rows)
#   3. re-verify the final incident file with round-1 verify.py (all rows must pass); manifest.json + MD5SUMS
# usage: RUN_ID=d1 [SEED=31 POOL=26000 TARGET=12000 SKIP_CHAT=0 SELFTEST_N=0] bash detach.sh mkdata_d1 .../local/make_data.sh
SCRIPT=make_data; source "$(dirname "$0")/guard.sh"
set -o pipefail
check_run_id
OUT=$KG/build/$RUN_ID/data
need_ram 1536
need_disk /mnt/c 3000
new_dir "$OUT"
status "start (seed ${SEED:-31}, pool ${POOL:-44000}, target ${TARGET:-20000}, skip_chat ${SKIP_CHAT:-0})"
cd "$V3/pipeline" || die "no pipeline dir"
if [ "${SKIP_CHAT:-0}" != 1 ]; then
  bash run_all.sh > "$OUT/chat3_run_all.log" 2>&1 || die "pipeline/run_all.sh failed (see $OUT/chat3_run_all.log)"
  status "chat3 regenerated: $(tail -n 1 "$OUT/chat3_run_all.log")"
fi
need_ram 1536
python3 -B verify_chat.py --selftest --n "${SELFTEST_N:-0}" --out "$OUT/chat3_selftest.json" > "$OUT/chat3_selftest.log" 2>&1
grep -q "SELFTEST PASS" "$OUT/chat3_selftest.log" || die "verify_chat self-test did not pass (see $OUT/chat3_selftest.log)"
# the chat tool store is whatever tools_v3_impl.STORE points at (round-1 store or the v3 store made by run_all.sh)
STORE_REL=$(python3 -B -c "import os,sys;sys.path.insert(0,'$V3/pipeline');import tools_v3_impl as T;print(os.path.relpath(T.STORE,'$V3'))") \
  || die "cannot import tools_v3_impl"
echo "$STORE_REL" > "$OUT/store_path.txt"
(cd "$V3" && md5sum data/chat3_train.jsonl data/chat3_dev.jsonl data/chat3_manifest.json pipeline/tools_v4.json pipeline/verify_chat.py \
  pipeline/tools_v3_impl.py "$STORE_REL") > "$OUT/chat3_sources.md5" || die "chat3 sources missing"
status "chat3 ok: train $(wc -l < "$V3/data/chat3_train.jsonl") dev $(wc -l < "$V3/data/chat3_dev.jsonl") rows, self-test PASS"

need_ram 1536
python3 -B "$KG/gen_incidents_v3.py" --out "$OUT" --seed "${SEED:-31}" --pool "${POOL:-44000}" --target "${TARGET:-20000}" --rwh2 "${RWH2:-150}" \
  > "$OUT/incidents3_gen.log" 2>&1 || die "gen_incidents_v3.py failed (see $OUT/incidents3_gen.log)"
status "incidents: $(tail -n 1 "$OUT/incidents3_gen.log")"
status "RWH-2 (held out, never bundled): $(cat "$OUT/../heldout/rwh2_report.json" | tr -d '\n ' | cut -c1-200)"
# compact gold: mean target tokens before/after on the sampled rows (Qwen tokenizer, rsn venv)
HF_HUB_OFFLINE=1 ~/venvs/rsn/bin/python - "$OUT/compact_samples.json" "$OUT/compact_tokens.json" <<'EOF' > "$OUT/compact_tokens.log" 2>&1 || status "WARN: compact token measurement failed"
import json, os, sys
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained(os.path.expanduser("~/models/qwen3.5-4b"))
s = json.load(open(sys.argv[1]))
b = [len(tok(x, add_special_tokens=False)["input_ids"]) for x, _ in s]
a = [len(tok(y, add_special_tokens=False)["input_ids"]) for _, y in s]
r = {"n": len(s), "mean_tokens_before": round(sum(b) / max(1, len(b)), 1), "mean_tokens_after": round(sum(a) / max(1, len(a)), 1)}
r["cut_pct_on_compacted_rows"] = round(100 * (1 - sum(a) / max(1, sum(b))), 1)
json.dump(r, open(sys.argv[2], "w")); print(json.dumps(r))
EOF
status "compact targets: $(tail -n 1 "$OUT/compact_tokens.log"); $(python3 -c "import json;print(json.load(open('$OUT/incidents3_report.json'))['compact'])")"
cp "$OUT/incidents3_train.jsonl" "$OUT/check.jsonl"
python3 -B "$R1/pipeline/verify.py" "$OUT/check.jsonl" > "$OUT/incidents3_verify.txt" 2>&1 || die "verify.py crashed"
a=$(md5sum < "$OUT/check.jsonl"); b=$(md5sum < "$OUT/check.ok.jsonl")
rm -f "$OUT/check.jsonl" "$OUT/check.ok.jsonl"
[ "$a" = "$b" ] || die "re-verify: not every incident row passes ($(cat "$OUT/incidents3_verify.txt"))"
status "re-verify: $(cat "$OUT/incidents3_verify.txt")"

python3 - "$OUT" "$V3" <<'EOF' || die "manifest failed"
import hashlib, json, os, sys, collections
out, v3 = sys.argv[1:3]
def rows(p): return sum(1 for _ in open(p, encoding="utf-8"))
m = {"run": os.path.basename(os.path.dirname(out)), "files": {}, "chat3": {}}
for n in sorted(os.listdir(out)):
    p = os.path.join(out, n)
    if os.path.isfile(p):
        m["files"][n] = {"bytes": os.path.getsize(p), "md5": hashlib.md5(open(p, "rb").read()).hexdigest(),
                         "rows": rows(p) if n.endswith(".jsonl") else None}
for n in ("chat3_train.jsonl", "chat3_dev.jsonl"):
    rs = [json.loads(l) for l in open(os.path.join(v3, "data", n), encoding="utf-8")]
    m["chat3"][n] = {"rows": len(rs), "hard": sum(1 for r in rs if r.get("hard")), "kinds": len({r["kind"] for r in rs})}
rep = json.load(open(os.path.join(out, "incidents3_report.json")))
m["incidents3"] = {k: rep[k] for k in ("rows", "pool_verified", "leak_vs_dev_rwh", "border_rows", "real_pool_rows_used_by_round1")}
json.dump(m, open(os.path.join(out, "manifest.json"), "w"), indent=1)
print(json.dumps({"incidents3": m["incidents3"], "chat3": m["chat3"]}))
EOF
md5_manifest "$OUT"
status "DONE data -> $OUT ($(du -sh "$OUT" | cut -f1))"
