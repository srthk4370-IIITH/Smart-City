#!/usr/bin/env bash
# run_dryrun.sh: offline end-to-end dry run of runner.sh with the kaggle shim (no network, no GPU, no uploads, real token untouched).
# Synthetic sample + tiny random Llama; the REAL agt3_kernel.py + train_agt3.py run on CPU (torchrun 2 procs, gloo) inside the
# shim; export/eval are stubs. Checks: waits without approval (no upload), then push -> train -> pull x2 (exit 3 resume),
# private-only uploads, live-version lag, selection, GATE_agt.md; plus secret-scan and provenance refusals.
set -u
A=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt
T=${T:-$HOME/smartcity_runs/agt_v3_dryrun}; rm -rf "$T"; mkdir -p "$T/kdir"
PYR=$HOME/venvs/rsn/bin/python
ok=0; bad=0; t() { if eval "$2"; then echo "PASS $1"; ok=$((ok+1)); else echo "FAIL $1"; bad=$((bad+1)); fi; }
CUDA_VISIBLE_DEVICES= $PYR "$A/test/make_synth.py" "$T/synth" "$HOME/models/llama-3.2-3b-instruct" > "$T/synth.log" 2>&1 || { cat "$T/synth.log"; exit 1; }
echo "dummy-not-a-token" > "$T/kdir/access_token"; chmod 600 "$T/kdir/access_token"
mkdir -p "$T/shim"; echo 1 > "$T/shim/lag"
export KAGGLE=$A/test/kaggle_shim.sh SHIM=$T/shim KDIR=$T/kdir TINY=$T/synth/tiny_llama BASE_LOCAL=$T/synth/tiny_llama \
  DATA_DIR=$T/synth/data RUNS=$T/runs STATUS=$T/STATUS.md STATEF=$T/STATE STOPF=$T/STOP PLOGS=$T/plogs RUNNER_PID=$T/runner.pid OUTD=$T \
  QUANT=none GEN_N=4 MAX_NEW=8 SNAP_EVERY=2 SAVE_EVERY=1 PATIENCE=50 ROWS_PER_STEP=8 MICRO=2 EPOCHS=1 SESSION_STEPS=4 \
  POLL_S=1 LIVE_POLL_S=1 KDS_POLL_S=1 APPROVAL_POLL_S=2 EXPORT_CMD="bash $A/test/stub_export.sh" EVAL_CMD="$PYR $A/test/stub_eval.py" \
  B50_GGUF=$T/b50.gguf GPU_LOCK=$T/GPU_LOCK GPU_ASSUME_FREE=1 MIN_C_FREE_MB=1 FAKE_LAUNCH="torchrun --standalone --nproc_per_node 2 "
echo "fake b50" > "$T/b50.gguf"
bash "$A/runner.sh" > "$T/runner.log" 2>&1 & RP=$!
sleep 8
t "waits for approval (no upload)" "grep -q 'waiting for owner approval' $T/STATUS.md && [ ! -s $T/shim/uploads.log ]"
touch "$T/synth/data/APPROVED_AGENTS"
for i in $(seq 1 180); do kill -0 $RP 2>/dev/null || break; sleep 5; done
kill -0 $RP 2>/dev/null && { echo "runner still running after 15 min"; kill $RP; }
wait $RP; rc=$?
echo "--- STATUS"; cat "$T/STATUS.md"; echo "--- STATE"; cat "$T/STATE"
t "runner finished (gate ran; rc 0/1)" "[ $rc -le 1 ] && [ -s $T/GATE_agt.md ]"
t "two sessions, step 6/6 done" "grep -q '^seq=2' $T/STATE && grep -q '^step=6' $T/STATE"
t "session 1 exit 3 + resume" "grep -q 'EXIT (hours limit' $T/runs/run/train.log && grep -q 'resumed at step 4' $T/runs/run/train.log"
t "trainer ran 2 ranks (gloo)" "grep -q 'world 2' $T/runs/run/train.log"
t "snapshots pulled + scored" "ls -d $T/runs/run/snap_0002 $T/runs/run/snap_0004 $T/runs/run/snap_0006 >/dev/null && [ -s $T/runs/post/selection.json ]"
t "uploads private only, no gguf/sqlite/token" "! grep -qv ' private ' $T/shim/uploads.log && ! (cd $T/shim/ds && find . -type f | grep -Eq 'gguf|sqlite|access_token')"
t "live-version lag handled" "grep -c 'agt3-run' $T/shim/calls.log >/dev/null && grep -q 'seq 2' $T/STATUS.md"
mkdir -p "$T/sec"; echo '{"token": "KGAT_abcdefghijklmnopqrstu"}' > "$T/sec/x.json"
t "secret scan refuses a token-like file" "! (source $A/lib.sh >/dev/null 2>&1; secret_scan $T/sec >/dev/null)"
head -1 "$T/synth/data/agt_v3/train.jsonl" | sed 's/"source": "synthetic"/"source": "real_heldout"/' > "$T/real.jsonl"
t "provenance check refuses a real row" "! $PYR -I $A/check_data.py $T/real.jsonl $T/synth/data/agt_v3/dev.jsonl $T/synth/data/calib_stats.json 4 $T/chk >/dev/null"
echo "--- GATE"; cat "$T/GATE_agt.md"
echo "dry run: $ok pass, $bad fail"; [ $bad = 0 ]
