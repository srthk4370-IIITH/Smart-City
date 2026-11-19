#!/usr/bin/env bash
# Dry run of chat_r3_eval.py on CPU against mock_server.py (no GPU, no model): every 25th chat_test_r3 record (all fog
# states) with adaptive and empty think, and 30 chat dev v3 records re-rendered to the r3 prompt.  usage: bash t_chat_mock.sh <outdir>
P=/mnt/c/Users/hp/Desktop/qidk/proofs; H=$P/2026-11-06_4b_local; O=${1:?outdir}; PORT=18199; mkdir -p $O; rm -f $O/*.jsonl
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
awk 'NR % 25 == 1' $H/data/final/chat_test_r3.jsonl > $O/r3_sample.jsonl
nice -n 15 python3 $H/post/test/mock_server.py $PORT $O/r3_sample.jsonl $P/2026-10-29_rsn_v3/data/chat3_dev.jsonl & MS=$!
trap "kill $MS 2>/dev/null" EXIT
sleep 3
E="nice -n 15 $HOME/venvs/rsn/bin/python $H/post/chat_r3_eval.py --port $PORT"
$E --mode r3test --think 1 --records $O/r3_sample.jsonl --out $O/r3_think1.jsonl || echo "r3test think1 rc=$?"
$E --mode r3test --think 0 --records $O/r3_sample.jsonl --limit 10 --out $O/r3_think0.jsonl || echo "r3test think0 rc=$?"
$E --mode dev3 --think 1 --limit 30 --out $O/dev3.jsonl || echo "dev3 rc=$?"
python3 - $O <<'EOF'
import collections, json, sys, os
for f in ("r3_think1", "r3_think0", "dev3"):
    p = os.path.join(sys.argv[1], f + ".jsonl")
    rs = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    fog = collections.Counter((r["fog"], r["pass"]) for r in rs)
    why = collections.Counter(x.split(":")[0] for r in rs for x in r["reasons"])
    print("%-10s n=%d pass=%d  by fog/pass %s  fail reasons %s" % (f, len(rs), sum(r["pass"] for r in rs), dict(fog), dict(why)))
EOF
