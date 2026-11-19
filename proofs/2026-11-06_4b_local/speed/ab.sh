#!/usr/bin/env bash
# ab.sh: GPU A/B of trainer speed flags on the REAL next steps of the live 4B r3 run, from a COPY of its latest checkpoint.
# Run only at a clean stop (ctl_4b.sh stop -> STOPPED). Never writes to the live run dir; each arm gets its own scratch copy
# (~/smartcity_runs/ab_<tag>_<arm>), so both arms train the same rows (same schedule.json + step + RNG state).
#   usage: wsl bash ab.sh [N_STEPS=6]
#   env:   A="<flags>" B="<flags>" (added to the live FIT_FLAGS of run.env), TAG=name, KEEP=1 keeps the scratch dirs
#   default arms: A = live flags; B = live + --shared-prefix
#   e.g.  B="--shared-prefix --offload-min 3072 --mlp-chunk-min 3072" TAG=sp_thr bash ab.sh 6
#         B="--offload-min 5120 --mlp-chunk-min 5120" bash ab.sh 6
#   B-only (reuse an earlier arm A): ARMS=B SRC=~/smartcity_runs/ab_base44 REF=speed/ab_spthr.txt B="..." TAG=x bash ab.sh 2
#         SRC = run dir holding the checkpoint to start from (default: the live run dir; token caches always from the live dir),
#         REF = an earlier ab_*.txt whose arm-A rows are shown next to B (same SRC step => same rows)
# Output: per-step table (tok/s, s, peak alloc/reserved GiB, loss) for A and B side by side + means -> speed/ab_<tag>.txt
# Guards: GPU_LOCK taken (refuses if held), refuses while the live trainer runs, MemAvailable >= 1500 MB to start,
#         aborts an arm at < 600 MB; GPU >= 92 C pauses the trainer (SIGSTOP) until <= 88 C (pauses are excluded from step
#         time only in the sense that they are logged; compare arms with the same number of pauses or rerun).
set -u
N=${1:-6}
H=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local; KG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle
LIVE=$HOME/smartcity_runs/rsn3_4b_r3; SRC=${SRC:-$LIVE}; ARMS=${ARMS:-A B}; REF=${REF:-}; PY=$HOME/venvs/rsn/bin/python; LOCK=$KG/../GPU_LOCK
TAG=${TAG:-$(date +%m%d_%H%M)}; OUT=$H/speed/ab_$TAG.txt
set -a; . $H/run.env; set +a
A_FLAGS="$FIT_FLAGS ${A:-}"; B_FLAGS="$FIT_FLAGS ${B:---shared-prefix}"
D=$H/data/final
die() { echo "ab.sh: $*" >&2; exit 1; }
pgrep -f "train_rsn3.py.*rsn3_4b_r3" > /dev/null && die "live trainer is running: stop it first (ctl_4b.sh stop)"
[ -e "$LOCK" ] && die "GPU_LOCK held: $(cat $LOCK)"
[ -s "$SRC/ckpt_latest/state.pt" ] || die "no $SRC/ckpt_latest"
av() { awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo; }
[ "$(av)" -ge 1500 ] || die "MemAvailable $(av) MB < 1500"
echo "ab_speed $TAG $(date -Is) pid=$$" > "$LOCK"; trap 'grep -q "^ab_speed " "$LOCK" 2>/dev/null && rm -f "$LOCK"' EXIT
S0=$($PY -c "import torch;print(torch.load('$SRC/ckpt_latest/state.pt',map_location='cpu',weights_only=False)['step'])")
STOPAT=$((S0 + N))
echo "A/B $TAG: steps $S0 -> $STOPAT of the live schedule (from $SRC; arms: $ARMS${REF:+; arm A rows from $REF})" | tee "$OUT"
echo "A: $A_FLAGS" | tee -a "$OUT"; echo "B: $B_FLAGS" | tee -a "$OUT"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  TORCHINDUCTOR_COMPILE_THREADS=1 MALLOC_ARENA_MAX=2 RSN3_SEG_TOKENIZE=1
for arm in $ARMS; do
  O=$HOME/smartcity_runs/ab_${TAG}_$arm; rm -rf "$O"; mkdir -p "$O"
  cp -r "$SRC/ckpt_latest" "$O/"; cp "$SRC/schedule.json" "$LIVE/maxlen.json" "$O/"
  [ -e "$SRC/best.json" ] && cp "$SRC/best.json" "$O/"
  for f in "$LIVE"/*_tok.pt; do ln -s "$(readlink -f "$f")" "$O/$(basename "$f")"; done
  ML=$($PY -c "import json;print(json.load(open('$O/maxlen.json'))['max_len'])")
  [ $arm = A ] && FL=$A_FLAGS || FL=$B_FLAGS
  echo "== arm $arm ($O) $(date +%T)" | tee -a "$OUT"
  nice -n 10 $PY "$KG/train_rsn3.py" --base $HOME/models/qwen3.5-4b --model-dir $HOME/models/qwen3.5-4b-nf4 --tools $D/tools_r3.json \
    --inc $D/incidents_train.jsonl --chat $D/chat_train_r3.jsonl --quant nf4 --dtype bf16 --out "$O" --max-len $ML --accum 16 \
    --max-steps $STOPAT --hours 3 --save-every 100000 --eval-every 100000 --gen-every 100000 --step-log $FL > "$O/stdout.log" 2>&1 &
  TP=$!; hot=0; pauses=0
  while kill -0 $TP 2>/dev/null; do
    sleep 5
    t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9)
    if [ "$(av)" -lt 600 ]; then kill -CONT $TP; kill $TP; echo "arm $arm aborted: MemAvailable < 600 MB" | tee -a "$OUT"; break; fi
    if [ $hot = 0 ] && [ -n "$t" ] && [ "$t" -ge 92 ]; then kill -STOP $TP; hot=1; pauses=$((pauses + 1)); fi
    if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 88 ]; then kill -CONT $TP; hot=0; fi
  done
  cp "$O/steps.jsonl" "$H/speed/ab_${TAG}_${arm}_steps.jsonl" 2>/dev/null
  wait $TP; echo "arm $arm rc $? heat pauses $pauses; $(grep -h 'fit levers\|shared prefix\|OOM' "$O/train.log" | tr '\n' ' ')" | tee -a "$OUT"
  sleep 60     # let the GPU cool a bit between arms
done
$PY - "$HOME/smartcity_runs/ab_${TAG}_A/steps.jsonl" "$HOME/smartcity_runs/ab_${TAG}_B/steps.jsonl" "$REF" <<'EOF' | tee -a "$OUT"
import json, sys
def rd(p):
    try:
        return {r["step"]: r for r in map(json.loads, open(p))}
    except OSError:
        return {}
A, B = rd(sys.argv[1]), rd(sys.argv[2])
if not A and sys.argv[3]:          # arm A rows of an earlier table: step | tok/s s alloc reserved loss | ...
    for l in open(sys.argv[3]):
        c = l.split("|")
        if len(c) >= 2 and c[0].strip().isdigit() and c[1].split() and c[1].split()[0] != "-":
            t, s_, al, rs, lo = map(float, c[1].split()[:5])
            A[int(c[0])] = {"tok_s": t, "s": s_, "peak_alloc_gib": al, "peak_reserved_gib": rs, "loss": lo, "row_tokens": t * s_}
print("%5s | %8s %7s %6s %6s %8s | %8s %7s %6s %6s %8s | %6s" % ("step", "A tok/s", "A s", "A al", "A rs", "A loss", "B tok/s", "B s", "B al", "B rs", "B loss", "dloss"))
for s in sorted(set(A) | set(B)):
    a, b = A.get(s, {}), B.get(s, {})
    f = lambda r, k, fm: (fm % r[k]) if k in r else "-"
    dl = ("%.4f" % (b["loss"] - a["loss"])) if a and b else "-"
    print("%5d | %8s %7s %6s %6s %8s | %8s %7s %6s %6s %8s | %6s" % (s, f(a, "tok_s", "%.0f"), f(a, "s", "%.1f"), f(a, "peak_alloc_gib", "%.2f"),
          f(a, "peak_reserved_gib", "%.2f"), f(a, "loss", "%.4f"), f(b, "tok_s", "%.0f"), f(b, "s", "%.1f"), f(b, "peak_alloc_gib", "%.2f"),
          f(b, "peak_reserved_gib", "%.2f"), f(b, "loss", "%.4f"), dl))
for n, R in (("A", A), ("B", B)):
    if R:
        rs = list(R.values())[1:] or list(R.values())      # first step includes warm-up
        print("%s: %d steps, %.1f tok/s (sum tokens / sum s, first step excluded), max peak alloc %.2f GiB, reserved %.2f GiB, mean loss %.4f" % (
            n, len(R), sum(r["row_tokens"] for r in rs) / sum(r["s"] for r in rs), max(r["peak_alloc_gib"] for r in R.values()),
            max(r["peak_reserved_gib"] for r in R.values()), sum(r["loss"] for r in R.values()) / len(R)))
EOF
[ -n "${KEEP:-}" ] || rm -rf "$HOME/smartcity_runs/ab_${TAG}_A" "$HOME/smartcity_runs/ab_${TAG}_B"
echo "written $OUT"
