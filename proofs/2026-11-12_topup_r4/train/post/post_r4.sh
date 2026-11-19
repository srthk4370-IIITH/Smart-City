#!/usr/bin/env bash
# post_r4.sh: unattended post chain of the r4 top-up (run rsn3_4b_r4topup). Launched by supervisor_r4.sh after training (or by
# hand: bash proofs/detach.sh post_r4 <this>). Steps, each idempotent (marker post/markers/<step>.done):
#   wait    training finished (chain/train.done or status.json stopped early_stop/done) and no trainer / chain_r4 running
#   pick    best.json "top" (only checkpoints that beat the start adapter on the combined score with r3 kept): the first
#           ckpt_best_XXXX with an adapter -> copied with md5 to ~/smartcity_runs/rsn3_4b_r4topup_post/. No such checkpoint
#           -> verdict FAIL ("no top-up checkpoint beat r3-2800 on the dev slices"), r3-2800 stays, nothing is exported.
#   export  2026-11-06_4b_local/post/export_4b.sh -> Code/models_stage/rsn_v3_4b_r4_q4_0.gguf + .md5 (never the r3 name)
#   gate    gate_r4.sh -> post/gate_r4/GATE_r4.md + gate.json (PASS or FAIL both finish the step)
# Clean stop: touch post/STOP. Re-launch resumes. Board deployment is NOT part of this chain (owner decides).
export SCRIPT=post_r4; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
T4=$QIDK/proofs/2026-11-12_topup_r4/train; P=$T4/post; MK=$P/markers; mkdir -p "$MK"
RUN=rsn3_4b_r4topup; R=$HOME/smartcity_runs/$RUN; C=$T4/chain; NAME=rsn_v3_4b_r4
BASE=$HOME/models/qwen3.5-4b; PK=$HOME/smartcity_runs/${RUN}_post
export STOPF=$P/STOP STAGE_DIR=$QIDK/Code/models_stage LOGD=$P/export_r4 GATE_OUT=$P/gate_r4
G=$STAGE_DIR/${NAME}_q4_0.gguf
case "$NAME" in *r3*) die "refusing: export name $NAME would touch the r3 GGUF" 2;; esac
if [ -s "$P/post.pid" ] && kill -0 "$(cat "$P/post.pid")" 2>/dev/null; then die "post_r4 already running (pid $(cat "$P/post.pid"))" 8; fi
echo $$ > "$P/post.pid"; trap 'rm -f "$P/post.pid"' EXIT
stopchk() { [ -e "$STOPF" ] && { status "STOP file: post chain stops (rm post/STOP and relaunch to resume)"; exit 0; }; }
isdone() { [ -e "$MK/$1.done" ]; }
done_() { echo "$(date -Is) ${2:-}" > "$MK/$1.done"; status "step $1 done${2:+: $2}"; }
finished() { [ -e "$C/train.done" ] || grep -qE '"stopped": "(early_stop|done)"' "$R/status.json" 2>/dev/null; }
busy() { pgrep -f "topup_train.py.*$RUN" > /dev/null && { echo "trainer running"; return; }
  local p; p=$(cat "$C/chain.pid" 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo "chain_r4 running (pid $p)"; }
status "post chain start (pid $$, steps done: $(ls "$MK" 2>/dev/null | sed 's/.done//' | tr '\n' ' '))"

if ! isdone wait; then
  last=""
  while true; do
    stopchk
    why=""; finished || why="training not finished (step $(grep -oE 'step [0-9]+/' "$R/train.log" 2>/dev/null | tail -1 | tr -dc 0-9))"
    [ -z "$why" ] && why=$(busy)
    [ -z "$why" ] && [ ! -s "$R/best.json" ] && why="no best.json"
    [ -z "$why" ] && break
    w=${why%% (*}; [ "$w" != "$last" ] && status "waiting: $why"; last=$w
    for i in $(seq 1 20); do [ -e "$STOPF" ] && break; sleep 30; done
  done
  done_ wait "finished ($(grep -oE '"stopped": "[a-z_]+"' "$R/status.json" 2>/dev/null))"
fi
stopchk

if ! isdone pick; then
  python3 - "$R" "$PK" "$P/pick.json" <<'EOF' > "$P/pick.log" 2>&1; rc=$?
import hashlib, json, os, shutil, sys, time
R, PK, out = sys.argv[1:4]
b = json.load(open(os.path.join(R, "best.json")))
top = sorted(b.get("top") or [], key=lambda x: (-x[0], -x[1]))
for sc, st in top:
    d = os.path.join(R, "ckpt_best_%04d" % st)
    if all(os.path.isfile(os.path.join(d, f)) and os.path.getsize(os.path.join(d, f)) > 0 for f in ("adapter_model.safetensors", "adapter_config.json")):
        break
    print("skip missing %s" % d)
else:
    json.dump({"picked": None, "why": "no top-up checkpoint beat the start adapter (r3-2800) on the combined dev score with r3 kept",
               "best_json": b, "time": time.strftime("%Y-%m-%d %H:%M:%S")}, open(out, "w"), indent=1)
    print("NO_CANDIDATE start %s top %s" % (b.get("start"), top))
    sys.exit(5)
dst = os.path.join(PK, "ckpt_best_%04d" % st)
os.makedirs(dst + ".part", exist_ok=True)
md5 = {}
for f in ("adapter_model.safetensors", "adapter_config.json"):
    shutil.copyfile(os.path.join(d, f), os.path.join(dst + ".part", f))
    hs = []
    for p in (os.path.join(d, f), os.path.join(dst + ".part", f)):
        h = hashlib.md5()
        with open(p, "rb") as fh:
            for c in iter(lambda: fh.read(1 << 22), b""):
                h.update(c)
        hs.append(h.hexdigest())
    assert hs[0] == hs[1], "copy md5 mismatch " + f
    md5[f] = hs[0]
if os.path.exists(dst):
    shutil.rmtree(dst)
os.rename(dst + ".part", dst)
gen = {}
for l in open(os.path.join(R, "gen_eval.jsonl")):
    try:
        r = json.loads(l); gen[r["step"]] = r
    except Exception:
        pass
json.dump({"picked": st, "score": sc, "start": b.get("start"), "adapter": dst, "md5": md5, "best_json": b, "gen_eval_at_step": gen.get(st),
           "gen_eval_start": gen.get(0), "time": time.strftime("%Y-%m-%d %H:%M:%S")}, open(out, "w"), indent=1)
print("picked step %d combined %s (start %s) -> %s" % (st, sc, b.get("start"), dst))
EOF
  if [ $rc = 5 ]; then
    mkdir -p "$GATE_OUT"
    printf '# r4 top-up STRICT gate -> **FAIL**\n\nNo top-up checkpoint beat r3-2800 on the combined generation dev score (r4 dev + r3 slices, r3 not lower than start - 0.01): nothing exported. r3-2800 (rsn_v3_4b_r3_q4_0.gguf) stays the model.\n\n%s\n' "$(tail -n 1 "$P/pick.log")" > "$GATE_OUT/GATE_r4.md"
    echo '{"verdict": "FAIL", "why": "no candidate"}' > "$GATE_OUT/gate.json"
    done_ pick "no candidate"; done_ export "skipped (no candidate)"; done_ gate "FAIL (no candidate) -> $GATE_OUT/GATE_r4.md"
    status "post chain DONE: FAIL, no candidate; r3-2800 stays"; exit 0
  fi
  [ $rc = 0 ] || die "pick failed: $(tail -n 2 "$P/pick.log" | tr '\n' ' ')"
  done_ pick "$(tail -n 1 "$P/pick.log")"
fi
stopchk

if ! isdone export; then
  A=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['adapter'])" "$P/pick.json")
  bash "$QIDK/proofs/2026-11-06_4b_local/post/export_4b.sh" "$BASE" "$A" "$NAME" || die "export failed (rc $?)"
  stopchk
  [ -s "$G" ] && [ -s "$G.md5" ] || die "export: no $G after export_4b.sh"
  done_ export "$G md5 $(cut -d' ' -f1 "$G.md5")"
fi
stopchk

if ! isdone gate; then
  bash "$P/gate_r4.sh" "$G"; rc=$?
  case $rc in
    0|1) done_ gate "$( [ $rc = 0 ] && echo PASS || echo FAIL ) -> $GATE_OUT/GATE_r4.md";;
    3) exit 0;;
    *) die "gate rc $rc (see $GATE_OUT/; relaunch resumes)" $rc;;
  esac
fi
status "post chain DONE: $G, gate $(python3 -c "import json;print(json.load(open('$GATE_OUT/gate.json'))['verdict'])" 2>/dev/null) ($GATE_OUT/GATE_r4.md). Board deployment: owner decides; on FAIL r3-2800 stays."
