#!/usr/bin/env bash
# run_tests.sh: offline tests of the baton (no GPU, no network, no token). Uses a COPY of a real laptop lineage
# (~/smartcity_runs/rsn3_2b_r2: AdamW8bit, bf16, schedule.json, best-K) in /tmp/baton_test, the fake `kaggle` CLI
# (kaggle_shim.sh + fake_session.sh running the real baton_util.py kunpack/kpack) and fake_ctl.sh for ctl_4b.sh.
# The real r3 data is md5-verified and staged exactly as for an upload (it goes to the shim only).
# usage: wsl bash .../baton/test/run_tests.sh   -> results also in baton/test/results.log
set -u
B=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/baton; Q=/mnt/c/Users/hp/Desktop/qidk/proofs
T=/tmp/baton_test; SRC=$HOME/smartcity_runs/rsn3_2b_r2; PY=$HOME/venvs/rsn/bin/python
LOGF=$B/test/results.log; : > "$LOGF"
rm -rf "$T"; mkdir -p "$T/kdir" "$T/shim"
export SHIM=$T/shim BATON_RUN_DIR=$T/run BATON_WORK=$T/work BATON_FILE=$T/BATON BATON_STATUS=$T/STATUS.md BATON_CTL=$B/test/fake_ctl.sh \
  BATON_CHAIN_DIR=$T/chain KAGGLE=$B/test/kaggle_shim.sh BATON_KDIR=$T/kdir BATON_STOP=$T/STOP BATON_LOGS=$T/plogs BATON_PIDF=$T/auto.pid \
  POLL_S=2 RETRY_H=0 LIVE_POLL_S=1 LIVE_TRIES=6 BATON_CURSOR_DATA="$Q/2026-11-06_4b_local/data/final/incidents_train.jsonl $Q/2026-11-02_2b_r2/data/final/chat_train.jsonl"
export CUDA_VISIBLE_DEVICES=
pass=0; fail=0
ok() { if eval "$2"; then pass=$((pass + 1)); echo "PASS $1" | tee -a "$LOGF"; else fail=$((fail + 1)); echo "FAIL $1   [$2]" | tee -a "$LOGF"; fi; }
util() { nice -n 10 "$PY" "$B/baton_util.py" "$@"; }
stepof() { util step "$1/ckpt_latest/state.pt"; }
bget() { sed -n "s/^$1=//p" "$T/BATON" | tail -1; }
lap_running() { p=$(cat "$T/chain/chain.pid" 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
cleanup() { bash "$B/test/fake_ctl.sh" stop > /dev/null 2>&1; [ -s "$T/auto.pid" ] && kill "$(cat "$T/auto.pid")" 2>/dev/null; }
trap cleanup EXIT

mkdir -p "$T/run"
cp -r "$SRC"/ckpt_latest "$SRC"/ckpt_best_* "$SRC"/{schedule.json,best.json,status.json,plan.json,maxlen.json,train.log,losses.jsonl,dev.jsonl,gen_eval.jsonl} "$T/run/"
"$PY" - "$T/run" <<'EOF'
import os, sys, torch          # two tiny token caches (the real ones are 2.2 GB): enough to drive the cache-dataset path
for name in ("inc_aaaaaaaaaaaa_seg_tok.pt", "chat_bbbbbbbbbbbb_seg_tok.pt"):
    torch.save([{"id": name[:3] + str(i), "kind": "incident", "family": "", "hard": False, "ids": torch.arange(10, dtype=torch.int32),
                 "labels": torch.full((10,), -100, dtype=torch.int32)} for i in range(3)], os.path.join(sys.argv[1], name))
EOF
S0=$(stepof "$T/run"); echo "test lineage: copy of $SRC at step $S0" | tee -a "$LOGF"

echo "== 1. pack -> unpack round trip (md5)" | tee -a "$LOGF"
( source "$B/lib.sh"; pack_lineage "$R" "$T/p1" && unpack_lineage "$T/p1/lineage.tar" "$T/u1" ) > "$T/t1.log" 2>&1
ok "pack+unpack" '[ -s "$T/u1/ckpt_latest/state.pt" ]'
ok "every packed file identical" '(cd "$T/run" && while read -r f; do cmp -s "$f" "$T/u1/$f" || exit 1; done < "$T/p1/files.txt")'
ok "best-K dirs travel" '[ $(ls -d "$T"/u1/ckpt_best_* | wc -l) = 3 ]'
cp "$T/p1/lineage.tar" "$T/bad.tar"; cp "$T/p1/lineage.tar.md5" "$T/bad.tar.md5"; sed -i 's/ lineage.tar/ bad.tar/' "$T/bad.tar.md5"
printf 'X' | dd of="$T/bad.tar" bs=1 seek=4000000 conv=notrunc 2> /dev/null
ok "corrupted tar refused" '! ( source "$B/lib.sh"; unpack_lineage "$T/bad.tar" "$T/u2" ) > /dev/null 2>&1'
python3 - "$T/p1/lineage.tar" "$T/nomd5.tar" <<'EOF'
import sys, tarfile          # same files, one byte of best.json changed inside, no outer .md5 -> the inner MD5SUMS must catch it
src, dst = sys.argv[1:]
with tarfile.open(src) as a, tarfile.open(dst, "w") as b:
    for m in a.getmembers():
        f = a.extractfile(m)
        data = f.read() if f else None
        if m.name == "best.json":
            data = data.replace(b"1", b"2", 1)
        b.addfile(m, __import__("io").BytesIO(data) if data is not None else None)
EOF
ok "tampered file inside tar refused (inner MD5SUMS)" '! ( source "$B/lib.sh"; unpack_lineage "$T/nomd5.tar" "$T/u3" ) > /dev/null 2>&1'

echo "== 2. secret scan" | tee -a "$LOGF"
mkdir -p "$T/s1" "$T/s2" "$T/s3"; echo '{}' > "$T/s1/kaggle.json"; echo 'KAGGLE_KEY=abc' > "$T/s2/notes.txt"; echo ok > "$T/s3/a.txt"
ok "kaggle.json name refused" '! ( source "$B/lib.sh"; secret_scan "$T/s1" ) > /dev/null'
ok "secret-like text refused" '! ( source "$B/lib.sh"; secret_scan "$T/s2" ) > /dev/null'
ok "clean dir + real lineage tar pass" '( source "$B/lib.sh"; secret_scan "$T/s3" "$T/p1/lineage.tar" ) > /dev/null'

echo "== 3. CPU load test: laptop ckpt -> Kaggle code path -> laptop code path" | tee -a "$LOGF"
util loadtest "$T/run/ckpt_latest" "$HOME/models/qwen3.5-2b" > "$T/lt1.json" 2> "$T/lt1.err"; cat "$T/lt1.json" >> "$LOGF"
ok "loadtest (keys, shapes, AdamW8bit state exact, sched, scaler, RNG, step)" 'grep -q "\"ok\": true" "$T/lt1.json"'
ok "data cursor (schedule ids exist in the data, step <= plan)" 'util cursor "$T/run" $BATON_CURSOR_DATA > "$T/cur.json"'
"$PY" - "$B" <<'EOF' >> "$LOGF" 2>&1
import json, os, sys, tempfile
os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, sys.argv[1]); import baton_util as U
d = tempfile.mkdtemp()
json.dump({"r": 32, "lora_alpha": 64, "lora_dropout": 0.05, "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj",
           "down_proj", "in_proj_qkv", "in_proj_z", "in_proj_a", "in_proj_b", "out_proj"]}, open(os.path.join(d, "adapter_config.json"), "w"))
m = U.peft_skeleton(os.path.expanduser("~/models/qwen3.5-4b"), d)
n = sum(p.numel() for p in m.parameters() if p.requires_grad)
print("4B skeleton (meta device): trainable LoRA params %.1f M -> adapter %.0f MB fp32" % (n / 1e6, n * 4 / 1e6))
EOF
tail -1 "$LOGF"

echo "== 4. recipe (laptop-only fit flags dropped)" | tee -a "$LOGF"
ok "laptop-only flags dropped; memory levers + gen flags kept for Kaggle" 'util recipe "--model-dir /x --micro-tokens 7424 --head-cpu --ckpt-offload --mlp-chunk 512 --lean-host --shared-prefix --gen-r3 on --gen-every 200" 6144 | grep -q "\"flags\": \[\"--micro-tokens\", \"7424\", \"--ckpt-offload\", \"--mlp-chunk\", \"512\", \"--shared-prefix\", \"--gen-r3\", \"on\", \"--gen-every\", \"200\"\], \"dropped_laptop_only\": \[\"--model-dir\", \"/x\", \"--head-cpu\", \"--lean-host\"\]"'
ok "unknown flag refused" '! util recipe "--some-new-flag /path" 6144 > /dev/null 2>&1'

"$PY" - <<'EOF' > "$T/rb.json" 2>&1
import os, random, sys, json
os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle")
import torch, train_rsn3 as T
rnd = random.Random(5)
HC, HI = torch.randint(0, 9000, (4579,)), torch.randint(0, 9000, (1319,))      # chat header / incident prompt (r3 means)
gain = []
for s in range(200):
    rows = []
    for i in range(16):
        chat = rnd.random() < 0.5
        h = HC if chat else HI
        rows.append({"id": "r%d_%d" % (s, i), "ids": torch.cat([h, torch.randint(0, 9000, (rnd.randint(300, 1500 if chat else 1700),))])})
    sp = T.sp_rank_split(rows, 2, 256)
    assert sorted(e["id"] for p in sp for e in p) == sorted(e["id"] for e in rows)
    assert [[e["id"] for e in p] for p in sp] == [[e["id"] for e in p] for p in T.sp_rank_split(list(reversed(rows)), 2, 256)]
    gain.append(max(T.sp_cost(p, 256) for p in [rows[0::2], rows[1::2]]) / max(T.sp_cost(p, 256) for p in sp))
print(json.dumps({"ok": True, "mean_speedup_vs_strided": round(sum(gain) / len(gain), 3), "min": round(min(gain), 3)}))
EOF
cat "$T/rb.json" | tail -1 >> "$LOGF"
ok "rank split: every row exactly once, order-independent, never slower than strided" 'grep -q "\"ok\": true" "$T/rb.json" && python3 -c "import json,sys;d=json.loads(open(sys.argv[1]).read().strip().splitlines()[-1]);assert d[\"min\"]>=1.0" "$T/rb.json"'

echo "== 5. dry run with the fake kaggle CLI" | tee -a "$LOGF"
bash "$B/to_kaggle.sh" > "$T/a.log" 2>&1; rc=$?
ok "a. no token -> rc 10 (waiting for token), nothing uploaded" '[ $rc = 10 ] && [ ! -e "$SHIM/uploads.log" ]'
echo "fake-not-a-token" > "$T/kdir/access_token"; chmod 600 "$T/kdir/access_token"   # dummy: only existence + mode are tested
bash "$B/test/fake_ctl.sh" start > /dev/null; echo 1.0 > "$SHIM/quota"
bash "$B/to_kaggle.sh" > "$T/b.log" 2>&1; rc=$?
ok "b. quota 1.0 h -> rc 20, laptop untouched, nothing uploaded" '[ $rc = 20 ] && lap_running && [ ! -e "$SHIM/uploads.log" ]'
echo 25 > "$SHIM/quota"; echo 2 > "$SHIM/lag"; touch "$SHIM/zipdl"   # new version visible only on the 3rd check, served zipped
bash "$B/to_kaggle.sh" > "$T/c.log" 2>&1; rc=$?; S1=$((S0 + 10))
ok "c. handover -> rc 0" '[ $rc = 0 ]'
ok "c. laptop stopped cleanly first" '! lap_running'
ok "c. BATON holder=kaggle step=$S1 seq=1" '[ "$(bget holder)" = kaggle ] && [ "$(bget step)" = $S1 ] && [ "$(bget seq)" = 1 ]'
ok "c. data + token-cache + baton datasets uploaded, all private" '[ $(grep -c " private " "$SHIM/uploads.log") = 3 ] && ! grep -q PUBLIC "$SHIM/uploads.log"'
ok "c. r3 data md5-verified + gen-eval tree selftest passed" 'ls "$T"/work/data_selftest_*.ok > /dev/null && grep -q "\"ok\": true" "$T/work/logs/data_selftest.log"'
ok "c. kernel metadata: private, GPU, internet, T4, data + baton datasets" 'python3 -c "import json,sys;m=json.load(open(sys.argv[1]));assert m[\"is_private\"] and m[\"enable_gpu\"] and m[\"enable_internet\"] and m[\"machine_shape\"]==\"NvidiaTeslaT4\" and len(m[\"dataset_sources\"])>=2" "$SHIM/kernel/kernel-metadata.json"'
ok "c. kernel carries seq 1; budget = min(11.3, 25-0.3)" 'grep -q "EXPECT_SEQ = int(\"1\")" "$SHIM/kernel/rsn3_r3_baton.py" && grep -q "\"budget_h\": 11.3" "$SHIM/ds/rsn3-r3-baton/baton_cfg.json"'
ok "c. upload holds no token / board files" '! ls "$SHIM"/ds/*/ | grep -Eq "kaggle.json|access_token|htpd_profile|website_final|\.env"'
ok "c. laptop-only fit flags not in the Kaggle recipe" '! grep -q "head-cpu\|lean-host" <(python3 -c "import json;print(json.load(open(\"$SHIM/ds/rsn3-r3-baton/baton_cfg.json\"))[\"recipe\"][\"flags\"])")'
bash "$B/to_kaggle.sh" > "$T/d.log" 2>&1; rc=$?
ok "c. push waited until the new baton version was live (stale reads seen first)" '[ $(grep -c "^datasets download" "$SHIM/calls.log") -ge 3 ] && grep -q "seq 1 is live (checked 3 x)" "$T/STATUS.md"'
rm -f "$SHIM/zipdl"
ok "c. token caches uploaded once to the private cache dataset; kernel gets 3 datasets" '[ -f "$SHIM/ds/rsn3-r3-cache/TOKCACHE_OK" ] && [ $(grep -c "^rsn3-r3-cache private" "$SHIM/uploads.log") = 1 ] && python3 -c "import json,sys;assert len(json.load(open(sys.argv[1]))[\"dataset_sources\"])==3" "$SHIM/kernel/kernel-metadata.json"'
ok "c. kernel trains with --oom-stop (an OOM retries rows one per forward; a row that still OOMs stops with rc 7, never skips)" 'grep -q "EXTRA.append(\"--oom-stop\")" "$SHIM/kernel/rsn3_r3_baton.py" && grep -q "(\"OOM STOP\", 7)" "$SHIM/kernel/rsn3_r3_baton.py"'
ok "c. Kaggle speed knobs in baton_cfg (rank balance on, levers >4096 tokens, torch pin off)" 'python3 -c "import json,sys;c=json.load(open(sys.argv[1]));assert c[\"sp_rank_balance\"] and c[\"lever_min_tokens\"]==4096 and not c[\"pin_torch\"]" "$SHIM/ds/rsn3-r3-baton/baton_cfg.json"'
ok "d. second push while Kaggle holds the baton refused (rc 11)" '[ $rc = 11 ]'
bash "$B/from_kaggle.sh" --once > "$T/e1.log" 2>&1; rc1=$?
bash "$B/from_kaggle.sh" --once > "$T/e2.log" 2>&1; rc2=$?; S2=$((S1 + 50))
ok "e. poll while running -> 30, then pull -> 0" '[ $rc1 = 30 ] && [ $rc2 = 0 ]'
ok "e. installed step $S2 > $S1, BATON holder=laptop" '[ "$(stepof "$T/run")" = $S2 ] && [ "$(bget holder)" = laptop ] && [ "$(bget step)" = $S2 ]'
ok "e. previous lineage kept as backup" '[ -s "$T/run.prev_step$S1/ckpt_latest/state.pt" ]'
ok "e. fp16 scaler sidecar carried home" '[ -s "$T/run/baton_scaler_kaggle.pt" ]'
ok "e. best-K: Kaggle best dir installed, best.json dirs all present" 'util cursor "$T/run" $BATON_CURSOR_DATA | grep -q "\"best_dirs_missing\": \[\]"'
ok "e. Kaggle session log + result kept as proof" 'ls "$T"/plogs/kaggle_seq1_* > /dev/null'
util loadtest "$T/run/ckpt_latest" "$HOME/models/qwen3.5-2b" > "$T/lt2.json" 2> /dev/null
ok "e. Kaggle-made checkpoint (fp16, scaler, world 2) loads back on the laptop code path" 'grep -q "\"ok\": true" "$T/lt2.json"'
bash "$B/test/fake_ctl.sh" start > /dev/null; echo killed > "$SHIM/session"
bash "$B/to_kaggle.sh" > "$T/f1.log" 2>&1; rcp=$?; S3=$((S2 + 10))
ok "f. tagged causal_conv1d wheel + Triton cache from session 1 shipped to session 2; caches not re-uploaded" 'grep -q "__causal_conv1d-1.5.2" "$SHIM/kernel/baton_inputs.txt" 2>/dev/null || bash "$KAGGLE" kernels status x/y > /dev/null; grep -q "__causal_conv1d-1.5.2" "$SHIM/kernel/baton_inputs.txt" && grep -q "triton_cache.tar" "$SHIM/kernel/baton_inputs.txt" && [ $(grep -c "^rsn3-r3-cache" "$SHIM/uploads.log") = 1 ]'
ok "f. scaler sidecar injected into the next Kaggle session" 'grep -q "scaler state from step $S2 injected" "$SHIM/kernel/session.out" 2>/dev/null || { bash "$KAGGLE" kernels status x/y > /dev/null; grep -q "scaler state from step $S2 injected" "$SHIM/kernel/session.out"; }'
bash "$B/from_kaggle.sh" --once > "$T/f2.log" 2>&1; rc=$?
ok "f. session cut before packing: raw run dir installed (step $((S3 + 50)))" '[ $rcp = 0 ] && [ $rc = 0 ] && [ "$(stepof "$T/run")" = $((S3 + 50)) ]'
ok "f. exactly one backup kept (the lineage just replaced)" '[ $(ls -d "$T"/run.prev_step* | wc -l) = 1 ] && [ -d "$T/run.prev_step$S3" ]'
S4=$((S3 + 50 + 10)); bash "$B/test/fake_ctl.sh" start > /dev/null; echo stale > "$SHIM/session"
bash "$B/to_kaggle.sh" > "$T/g1.log" 2>&1; bash "$B/from_kaggle.sh" --once > /dev/null 2>&1; bash "$B/from_kaggle.sh" --once > "$T/g2.log" 2>&1; rc=$?
ok "g. stale dataset version: kernel aborts, rc 34, laptop lineage untouched" '[ $rc = 34 ] && [ "$(bget holder)" = laptop ] && [ "$(stepof "$T/run")" = $S4 ]'
echo ok > "$SHIM/session"; bash "$B/test/fake_ctl.sh" start > /dev/null
bash "$B/to_kaggle.sh" > "$T/h1.log" 2>&1
bash "$B/test/fake_ctl.sh" start > /dev/null; bash "$B/test/fake_ctl.sh" stop > /dev/null     # the laptop trains while Kaggle holds the baton
bash "$B/from_kaggle.sh" --once > /dev/null 2>&1; bash "$B/from_kaggle.sh" --once > "$T/h2.log" 2>&1; rc=$?
ok "h. laptop trained meanwhile: CONFLICT rc 33, holder=conflict, nothing installed" '[ $rc = 33 ] && [ "$(bget holder)" = conflict ] && [ "$(stepof "$T/run")" = $((S4 + 20)) ]'
( source "$B/lib.sh"; bset holder=laptop step=$((S4 + 20)) note="test: owner resolved conflict" )
echo quota > "$SHIM/push"
bash "$B/to_kaggle.sh" > "$T/i.log" 2>&1; rc=$?
ok "i. push refused for quota -> rc 20, holder laptop" '[ $rc = 20 ] && [ "$(bget holder)" = laptop ]'
echo ok > "$SHIM/push"
echo 99 > "$SHIM/lag"; n0=$(grep -c "^kernels push" "$SHIM/calls.log")
bash "$B/to_kaggle.sh" > "$T/j.log" 2>&1; rc=$?
ok "j. new baton version never live -> rc 22, no kernel push, holder laptop" '[ $rc = 22 ] && [ $(grep -c "^kernels push" "$SHIM/calls.log") = $n0 ] && [ "$(bget holder)" = laptop ]'
echo 0 > "$SHIM/lag"
mkdir -p "$T/sk"
cat > "$T/sk/train.log" <<'EOF'
[00:00:01] OOM in a shared-prefix batch at step 7: optimizer step skipped
[00:00:02] OOM on inc3-1 (7000 tokens) at step 9: optimizer step skipped
[00:00:03] OOM in a shared-prefix batch at step 11 (rank 0): retrying this rank's 8 rows one per forward
[00:00:04] OOM in a micro-batch at step 12 (rank 0): retrying this rank's 8 rows one per forward
EOF
cp "$T/run/schedule.json" "$T/sk/"
ok "k. skipped-step report: steps 7 and 9, 32 rows, 2 retries" 'util skipped "$T/sk" | python3 -c "import json,sys;d=json.load(sys.stdin);assert d[\"skipped_steps\"]==[7,9] and d[\"n_rows\"]==32 and d[\"shared_prefix_retries_rank0\"]==2, d"'

echo "== 6. baton_auto loop: Kaggle -> pull -> quota gone -> laptop -> STOP" | tee -a "$LOGF"
n0=$(grep -c "baton -> laptop: seq" "$T/STATUS.md")
echo 1.0 > "$SHIM/quota_after_push"
bash "$B/baton_auto.sh" > "$T/auto.log" 2>&1 &
AP=$!
for i in $(seq 1 300); do [ "$(grep -c "baton -> laptop: seq" "$T/STATUS.md")" -gt "$n0" ] && break; sleep 2; done
for i in $(seq 1 150); do lap_running && grep -q "Kaggle GPU quota left 1.0 h" "$T/STATUS.md" && break; sleep 2; done
touch "$T/STOP"; for i in $(seq 1 60); do kill -0 $AP 2>/dev/null || break; sleep 2; done
ok "auto: pushed, pulled, quota stop detected, laptop started, STOP honoured" 'grep -q "baton -> Kaggle: seq" "$T/auto.log" && [ "$(grep -c "baton -> laptop: seq" "$T/STATUS.md")" -gt "$n0" ] && lap_running && grep -q "STOP file: loop stops" "$T/STATUS.md" && ! kill -0 $AP 2>/dev/null'
rm -f "$T/STOP"; python3 -c "import json,sys;d=json.load(open(sys.argv[1]));d['stopped']='early_stop';json.dump(d,open(sys.argv[1],'w'))" "$T/run/status.json"
timeout 60 bash "$B/baton_auto.sh" > "$T/auto2.log" 2>&1
ok "auto: ends when training is finished" 'grep -q "training finished" "$T/auto2.log"'

echo "== 7. trainer OOM handling on CPU (tiny Qwen3.5, real main(), OOMs injected by monkeypatch; RAM-gated)" | tee -a "$LOGF"
if [ "${SKIP_OOM_TEST:-0}" = 1 ]; then echo "SKIP oom_retry_test.py (SKIP_OOM_TEST=1)" | tee -a "$LOGF"
else
  (cd /tmp && nice -n 15 "$PY" "$B/test/oom_retry_test.py" "$T/oom.json" > "$T/oom.log" 2>&1); tail -n 1 "$T/oom.log" >> "$LOGF"
  ok "oom: shared-prefix OOM -> rows retried one per forward, nothing skipped, adapter == no-fault run" 'python3 -c "import json,sys;c=json.load(open(sys.argv[1]))[\"checks\"];assert c[\"A_ref\"] and c[\"B_sp_retry\"]" "$T/oom.json"'
  ok "oom: --oom-stop micro-batch OOM -> retried one per forward, adapter == no-fault run" 'python3 -c "import json,sys;assert json.load(open(sys.argv[1]))[\"checks\"][\"D_mb_retry\"]" "$T/oom.json"'
  ok "oom: --oom-stop row OOM even per row -> rc 7 OOM STOP, ckpt at the step before, no skip" 'python3 -c "import json,sys;assert json.load(open(sys.argv[1]))[\"checks\"][\"E_oom_stop\"]" "$T/oom.json"'
  ok "oom: without --oom-stop the old behaviour stays (step skipped)" 'python3 -c "import json,sys;assert json.load(open(sys.argv[1]))[\"checks\"][\"F_default_skips\"]" "$T/oom.json"'
fi

grep -h "\[baton" "$T/STATUS.md" | sed 's/^/  /' >> "$LOGF"
echo "RESULT: $pass passed, $fail failed" | tee -a "$LOGF"
[ "$fail" = 0 ] && { cleanup; rm -rf "$T"; }
exit "$fail"
