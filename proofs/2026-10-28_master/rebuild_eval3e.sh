#!/usr/bin/env bash
# Standalone rebuild of the lost 1,148-row test set (eval3e = host400 + eval_weak + realworld_eval), deleted with
# ~/smartcity_runs/agents_v2_topup3e on 2026-10-27. Regenerates with the original generator/args into the original
# path (eval_test's symlink target), verifies ids + gold vs the old mixA50 samples, and keeps a copy in proofs/.
# CPU only, nice 10; waits for >= 3 GB free Windows RAM. Log: rebuild_eval3e.log
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; T=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
R=~/smartcity_runs/agents_v2_topup3e; PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
exec >> $M/rebuild_eval3e.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
ram(){ $PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -dc 0-9; }
source ~/venvs/train/bin/activate
log "=== rebuild start (waits for P3b: the generator needs ~2.5 GB and must not starve the queue's RAM guard)"
until [ -s /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/QUEUE_DONE_P3B.json ]; do sleep 120; done
while f=$(ram); [ -n "$f" ] && [ "$f" -lt 4096 ]; do log "RAM $f MB: wait"; sleep 60; done
mkdir -p $R/data $R/eval; cd $T
nice -n 10 python gen_3e.py --out $R/data --eval-scale 1.5 --only eval || { log "gen eval failed"; exit 1; }
nice -n 10 python gen_3e.py --out $R/data --eval-scale 1.5 --only eval --rw || { log "gen rw failed"; exit 1; }
nice -n 10 python host_eval3e.py build --out $R/eval || { log "build failed"; exit 1; }
python3 - $R/eval/eval3e.jsonl ~/smartcity_runs/agents_v2_topup3f/eval_test/eval/mixA50/samples.jsonl <<'P' | tee $M/rebuild_eval3e_verify.txt
import json, sys
new = {json.loads(l)["id"]: json.loads(l) for l in open(sys.argv[1], encoding="utf-8")}
old = {json.loads(l)["id"]: json.loads(l) for l in open(sys.argv[2], encoding="utf-8")}
common = set(new) & set(old)
def gold(r):
    try: g = json.loads(r["completion"].replace("<|eot_id|>", ""))   # common_v2.gold_of
    except Exception: g = {}
    return g.get("pattern"), g.get("status")
same = sum(1 for i in common if gold(new[i]) == (old[i]["gold_pattern"], old[i]["gold_status"]))
print(f"new {len(new)} old {len(old)} common ids {len(common)} same gold {same}")
print("missing:", sorted(set(old) - set(new))[:10]); print("extra:", sorted(set(new) - set(old))[:10])
print("VERIFY", "OK" if len(common) == len(old) == len(new) and same == len(old) else "MISMATCH")
P
mkdir -p $M/eval3e_testset && cp $R/eval/eval3e.jsonl $R/eval/eval3e_manifest.json $R/data/eval_weak.jsonl $R/data/realworld_eval.jsonl $M/eval3e_testset/ 2>/dev/null
md5sum $M/eval3e_testset/* > $M/eval3e_testset/MD5SUMS; log "=== rebuild done"
