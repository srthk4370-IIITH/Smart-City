#!/usr/bin/env bash
# chain.sh: agt_v3 laptop top-up end to end (resumable; phase markers in $T/state/). LAPTOP ONLY, nothing uploaded.
#  1 wait data build  2 GPU lock  3 10-step pilot (tok/s)  4 size + mix  5 train in 150-step chunks from snap_1750 (LR 5e-5 cosine,
#  save 50) -> after each chunk: export merged Q4_0 (shared agt_v3 imatrix) -> host eval REAL VAL + synthetic slice -> keep best,
#  stop after PATIENCE evals without gain  6 small re-gate (gate_subset.py)  7 report numbers (report.py).
set -u -o pipefail
Q=/mnt/c/Users/hp/Desktop/qidk; PF=$Q/proofs/2026-11-16_agt_topup; S=$PF/scripts; AG=$Q/proofs/2026-11-13_v3_train/agt
T=$HOME/smartcity_runs/agt_topup; D=$T/data; M=$T/mix; R=$T/run; mkdir -p $T/state $T/post $T/logs
PY=$HOME/venvs/rsn/bin/python; LOCK=$Q/proofs/2026-10-29_rsn_v3/GPU_LOCK
SNAP0=$HOME/smartcity_runs/agt_v3/run/snap_1750; BASE=$HOME/models/llama-3.2-3b-instruct
HOURS=${HOURS:-4}; CHUNK=${CHUNK:-75}; PATIENCE=${PATIENCE:-2}; MIN_GAIN=${MIN_GAIN:-0.002}; LR=${LR:-5e-5}; MICRO=${MICRO:-1}
LOG=$PF/STATUS.md
st() { local l="- $(date '+%F %T') $*"; echo "$l" >> "$LOG"; echo "$l"; }
done_() { [ -e "$T/state/$1" ]; }; mark() { touch "$T/state/$1"; }
export AGT_DIR=$AG RUN_DIR=$R WORK=$T/work POST=$T/post PLOGS=$T/logs STATUS=$LOG STOPF=$PF/STOP STATEF=$T/state/STATE GPU_ASSUME_FREE=1
holdlock() { echo "agt_topup $1 $(date -Is) pid $$ (laptop top-up chain; heat pause 92/88)" > "$LOCK"; }
release() { grep -q "^agt_topup " "$LOCK" 2>/dev/null && rm -f "$LOCK"; }
trap 'release; [ -n "${WD:-}" ] && kill $WD 2>/dev/null' EXIT
gputemp() { nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9; }
watchdog() {   # heat pause of the trainer: SIGSTOP at >= 92 C, SIGCONT at <= 88 C
  local p=0 t pid; while sleep 20; do t=$(gputemp); pid=$(pgrep -f "[t]rain_agt3.py.*$R" | head -1); [ -n "$pid" ] || { p=0; continue; }
    if [ $p = 0 ] && [ "${t:-0}" -ge 92 ]; then kill -STOP $pid; p=1; st "heat pause trainer at ${t} C"
    elif [ $p = 1 ] && [ "${t:-0}" -le 88 ]; then kill -CONT $pid; p=0; st "heat resume trainer at ${t} C"; fi; done; }
cfree() { [ "$(df -Pm /mnt/c | awk 'NR==2{print $4}')" -ge 20480 ] || { st "FAIL: C: < 20 GB free"; exit 5; }; }
[ -e "$PF/STOP" ] && exit 0

# ---- 1. data
until grep -q BUILD_DONE ~/detached/agt_topup_build.log 2>/dev/null; do
  pgrep -f "[b]uild_data.py" > /dev/null || { st "FAIL: data build ended without BUILD_DONE: $(tail -n 2 ~/detached/agt_topup_build.log | tr '\n' ' ')"; exit 2; }; sleep 60; done
done_ data || { st "data built: $(python3 -c "import json;d=json.load(open('$D/data_manifest.json'));print({k:d[k] for k in ('kept_real','real_train','real_val')}, 'drops', d['drop'])")"; mark data; }

# ---- 2. GPU lock (wait while someone else holds it or the GPU is busy)
said=0
while :; do
  if [ -e "$LOCK" ] && ! grep -q "^agt_topup " "$LOCK"; then [ $said = 0 ] && st "waiting for GPU lock: $(head -c 120 "$LOCK")"; said=1; sleep 120; continue; fi
  u=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -dc 0-9)
  [ "${u:-0}" -lt 800 ] && break; [ $said = 0 ] && st "waiting: GPU memory used ${u} MiB"; said=1; sleep 120
done
holdlock start; st "GPU lock taken"
watchdog & WD=$!

newrun() {   # newrun OUTDIR: lineage dir whose ckpt_latest = snap_1750 adapter (no state.pt -> step 0, fresh optimizer)
  mkdir -p "$1/ckpt_latest"; [ -s "$1/ckpt_latest/adapter_model.safetensors" ] || cp "$SNAP0"/adapter_config.json "$SNAP0"/adapter_model.safetensors "$1/ckpt_latest/"; }
train() {   # train OUT TRAINFILE EPOCHS MAXSTEPS
  CUDA_VISIBLE_DEVICES=0 TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 \
  "$PY" "$AG/kaggle/train_agt3.py" --base "$BASE" --train "$2" --dev "$M/gendev.jsonl" --out "$1" --rank 32 --alpha 32 --dropout 0.05 \
    --lr "$LR" --warmup 0.03 --min-lr-ratio 0.1 --rows-per-step 32 --micro "$MICRO" --max-len 1536 --epochs "$3" --seed 3 --quant nf4 \
    --dtype fp16 --optim adamw8bit --save-every 50 --snap-every "$CHUNK" --gen-n 1 --max-new 64 --patience 999 --max-steps-session "$4" \
    >> "$T/logs/train_$(basename "$1").out" 2>&1
}

# ---- 3. pilot (10 steps on a 640-row mix of the same kind) -> tok/s
if ! done_ pilot; then
  python3 "$S/mix.py" "$D" 640 "$T/pilotmix" 50 10 > /dev/null && cp "$T/pilotmix/gendev.jsonl" "$T/pilotmix/gd.jsonl"
  mkdir -p "$M"; cp "$T/pilotmix/gendev.jsonl" "$M/gendev.jsonl"
  rm -rf "$T/pilot"; newrun "$T/pilot"; holdlock pilot
  train "$T/pilot" "$T/pilotmix/mix_train.jsonl" 1 10; rc=$?
  tps=$(grep "step 10/" "$T/pilot/train.log" | grep -o "[0-9]* tok/s" | tail -1 | tr -dc 0-9)
  [ -n "$tps" ] || { st "FAIL: pilot rc $rc: $(tail -n 3 "$T/logs/train_pilot.out" | tr '\n' ' ' | cut -c1-300)"; exit 3; }
  python3 - "$T/pilot" "$tps" > "$T/state/pilot.json" <<'P'
import json, sys
L = [json.loads(l) for l in open(sys.argv[1] + "/losses.jsonl")]
fp = json.load(open(sys.argv[1] + "/tokfp.json"))
print(json.dumps({"tok_s": int(sys.argv[2]), "tok_per_row": fp["tokens"] / fp["n"], "s_per_step": (L[-1]["t"] - L[1]["t"]) / (len(L) - 2),
                  "loss_first": L[0]["loss"], "loss_10": L[-1]["loss"], "steps": len(L)}))
P
  st "pilot: $(cat $T/state/pilot.json)"; mark pilot
fi

# ---- 4. size + mix (HOURS of training at the pilot speed, 1 epoch)
if ! done_ mix; then
  N=$(python3 -c "import json;p=json.load(open('$T/state/pilot.json'));print(int($HOURS*3600/p['s_per_step'])*32)")
  python3 "$S/mix.py" "$D" "$N" "$M" 400 120 > "$T/state/mix.out" || { st "FAIL: mix"; exit 4; }
  st "mix (target $N rows = $HOURS h at pilot speed): $(cat $T/state/mix.out)"; mark mix
fi

# ---- B50 + snap_1750 references on REAL VAL / syn slice (step 0 of the curve)
evalq() {   # evalq GGUF ROWS OUT
  holdlock "eval $(basename "$3")"
  [ -e "$3.done" ] && return 0
  mkdir -p "$(dirname "$3")"
  python3 "$AG/hosteval.py" --model "$1" --rows "$2" --out "$3" > "$3.log" 2>&1 && touch "$3.done"
}
score() { python3 - "$1" "$AG/kaggle" <<'P'
import json, sys
sys.path.insert(0, sys.argv[2]); import rows as RW
s = [json.loads(l) for l in open(sys.argv[1])]
agg = {k: round(sum(bool(x[k]) for x in s if x.get(k) is not None) / max(1, sum(x.get(k) is not None for x in s)), 4) for k in ("json", "status", "pattern", "cause", "dq")}
print(json.dumps(dict(score=round(RW.gen_score(s), 5), n=len(s), **agg)))
P
}
if ! done_ refs; then
  python3 - "$M/val_sel.jsonl" "$M/val_sel_b50.jsonl" <<'P'
import json, sys
# B50 reference rows = the same REAL VAL windows in their original v2 prompt (B50's own format) + v2 gold
pools = {"sft_v2": "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/data/sft_v2/train.jsonl",
         "topup2": "/home/hp_srthk4370/smartcity_runs/agents_v2_topup2/data/train.jsonl",
         "rw5": "/home/hp_srthk4370/smartcity_runs/agents_v2_topup3f/rw5/rw5_train.jsonl", "rw5x": "/home/hp_srthk4370/smartcity_runs/agents_v2_topup3f/rw5/rw5x_train.jsonl"}
want = {}
for l in open(sys.argv[1]):
    r = json.loads(l); pid = r["id"][3:].rsplit("-", 1); want.setdefault(pid[1], {})[pid[0]] = r["id"]
with open(sys.argv[2], "w", newline="\n") as o:
    for pn, ids in want.items():
        for l in open(pools[pn]):
            x = json.loads(l)
            if x["id"] in ids:
                o.write(json.dumps({"id": ids.pop(x["id"]) + "-b50", "prompt": x["prompt"], "completion": x["completion"], "role": x["role"]}) + "\n")
P
  G0=$HOME/smartcity_runs/agt_v3/post/snap_1750/agt3_snap_1750_q4_0.gguf
  mkdir -p $T/post/ref
  evalq "$Q/Code/models_stage/ft_B50_q4_0.gguf" "$M/val_sel_b50.jsonl" "$T/post/ref/val_b50.jsonl" && \
  evalq "$G0" "$M/val_sel.jsonl" "$T/post/ref/val_s1750.jsonl" && evalq "$G0" "$M/syn_slice.jsonl" "$T/post/ref/syn_s1750.jsonl" \
    || { st "FAIL: reference evals (see $T/post/ref/*.log)"; exit 6; }
  st "refs REAL VAL: B50 $(score $T/post/ref/val_b50.jsonl) | snap_1750 $(score $T/post/ref/val_s1750.jsonl) | snap_1750 syn $(score $T/post/ref/syn_s1750.jsonl)"
  mark refs
fi

# ---- 5. train chunks + selection
mkdir -p $T/post; [ -s $T/post/imatrix_agt3_shared.gguf ] || cp $HOME/smartcity_runs/agt_v3/post/imatrix_agt3_shared.gguf* $T/post/
newrun "$R"
while ! done_ trained; do
  [ -e "$PF/STOP" ] && { st "STOP file"; exit 0; }
  cfree; holdlock train
  s0=$(python3 -c "import json;print(json.load(open('$R/status.json'))['step'])" 2>/dev/null || echo 0)
  train "$R" "$M/mix_train.jsonl" 1 "$CHUNK"; rc=$?
  s1=$(python3 -c "import json;print(json.load(open('$R/status.json'))['step'])" 2>/dev/null || echo 0)
  ns=$(python3 -c "import json;print(json.load(open('$R/schedule.json'))['n_steps'])")
  st "train chunk rc $rc: step $s0 -> $s1 / $ns ($(grep -o '[0-9]* tok/s' $R/train.log | tail -1))"
  [ "$s1" -gt "$s0" ] || { st "FAIL: no progress (rc $rc): $(tail -n 3 $T/logs/train_run.out | tr '\n' ' ' | cut -c1-300)"; exit 7; }
  sn=$R/snap_$(printf %04d $s1); [ -d "$sn" ] || { [ "$rc" = 0 ] || { st "FAIL: no snapshot at $s1"; exit 7; }; }
  tag=s$(printf %04d $s1); P=$T/post/$tag
  bash "$AG/export.sh" "$sn" "$tag" shared || { st "FAIL: export $tag (see $P/export.log)"; exit 8; }
  evalq "$P/agt3_${tag}_q4_0.gguf" "$M/val_sel.jsonl" "$P/val.jsonl" && evalq "$P/agt3_${tag}_q4_0.gguf" "$M/syn_slice.jsonl" "$P/syn.jsonl" \
    || { st "FAIL: eval $tag"; exit 6; }
  echo "{\"step\": $s1, \"val\": $(score $P/val.jsonl), \"syn\": $(score $P/syn.jsonl)}" > "$P/score.json"
  sel=$(python3 - "$T/post" "$PATIENCE" "$MIN_GAIN" <<'P'
import glob, json, os, sys
post, pat, mg = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
sc = sorted((json.load(open(f)) for f in glob.glob(post + "/s[0-9]*/score.json")), key=lambda d: d["step"])
ref = json.load(open(post + "/ref_val_s1750.json")) if os.path.exists(post + "/ref_val_s1750.json") else None
best, bs, since = None, None, 0
for d in sc:
    v = d["val"]["score"]
    if best is None or v > best + mg:
        best, bs, since = v, d["step"], 0
    else:
        since += 1
sel = {"curve": sc, "best_step": bs, "best": best, "since_best": since, "stop": since >= pat}
json.dump(sel, open(post + "/selection.json", "w"), indent=1)
for d in sc:                      # disk: keep only the best Q4_0
    if d["step"] != bs:
        for g in glob.glob(post + "/s%04d/*.gguf" % d["step"]):
            os.remove(g)
print(json.dumps({k: sel[k] for k in ("best_step", "best", "since_best", "stop")}))
P
)
  st "select $tag: $(cat $P/score.json) -> $sel"
  echo "$sel" | grep -q '"stop": true' && { st "early stop: $PATIENCE evals without REAL VAL gain"; mark trained; }
  [ "$rc" = 0 ] && mark trained
done
mark trained

# ---- 6. small re-gate of the best
if ! done_ gate; then
  b=$(python3 -c "import json;print(json.load(open('$T/post/selection.json'))['best_step'])")
  SN=$R/snap_$(printf %04d $b); FT=final_s$(printf %04d $b)
  holdlock "gate export"
  bash "$AG/export.sh" "$SN" "$FT" own || { st "FAIL: final export"; exit 8; }
  python3 "$S/gate_subset.py" "$T/gate" > "$T/state/gate_subset.out" || { st "FAIL: gate_subset"; exit 9; }
  G=$T/post/$FT/agt3_${FT}_q4_0.gguf; SD=$T/gate/samples_cand
  for set in $(python3 -c "import json;print(' '.join(json.load(open('$T/gate/gate_config.json'))['sets']))"); do
    f=$(python3 -c "import json;print(json.load(open('$T/gate/gate_config.json'))['sets']['$set']['v3'])")
    evalq "$G" "$T/gate/rows/$f" "$SD/${set}_v3.jsonl" || { st "FAIL: gate eval $set"; exit 6; }
  done
  release
  python3 "$AG/gate.py" "$T/gate/gate_config.json" "$T/gate/rows" "$SD" "$PF/GATE_topup.md" "$PF/gate_topup.json" "agt_v3 topup snap_$(printf %04d $b) ($(cat $G.md5))"
  python3 "$AG/gate.py" "$T/gate/gate_config.json" "$T/gate/rows" "$T/gate/samples_s1750" "$PF/GATE_s1750_subset.md" "$PF/gate_s1750_subset.json" "agt_v3 snap_1750 (same subsets)"
  st "gate: $(head -n 1 $PF/GATE_topup.md)"; mark gate
fi
release
python3 "$S/report.py" "$T" "$PF" && st "REPORT numbers written" && echo CHAIN_DONE
