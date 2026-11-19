#!/usr/bin/env bash
# post_chain.sh: unattended post-training chain of the 4B r3 run (rsn3_4b_r3). Launch once, detached (POST.md):
#   wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh post_4b /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post/post_chain.sh
# Steps, each idempotent (marker post/markers/<step>.done), status lines [post_4b] in proofs/2026-10-29_rsn_v3/kaggle/STATUS.md:
#   wait    training finished (chain/train.done, or status.json stopped after_epoch1 / early_stop, or done) AND the laptop
#           holds the baton (baton/BATON holder=laptop or no BATON yet, no <run>/BATON_AT_KAGGLE) AND nothing trains or moves
#           the lineage (no train_rsn3.py for the run, chain_4b / to_kaggle / from_kaggle not running) AND best.json exists.
#           Checks every 10 min; a status line only when the reason changes.
#   pick    best checkpoint by the generation dev score: best.json "top" (sorted by score, then newest step), the first
#           ckpt_best_XXXX that holds an adapter; copied (2 small files) to ~/smartcity_runs/rsn3_4b_r3_post/ -> post/pick.json
#   export  export_4b.sh: merge (alpha/r, as export_gguf.sh) -> bf16 GGUF -> Q4_0 -> Code/models_stage/rsn_v3_4b_r3_q4_0.gguf + .md5
#   gate    gate_4b.sh: host GPU gate vs rsn_v1 -> post/gate_r3/GATE.md + gate.json (PASS or FAIL both finish the step)
# Clean stop: touch post/STOP (checked between steps and inside the waits; the gate stops its server). Re-launch resumes.
# Board deployment is NOT part of this chain (owner decides).
SCRIPT=${SCRIPT:-post_4b}; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
STATUS=${POST_STATUS:-$STATUS}   # tests write their status lines elsewhere
H=$QIDK/proofs/2026-11-06_4b_local; P=$H/post; D=${POST_OUT:-$P}; MK=$D/markers; mkdir -p "$MK"   # P = code, D = state (tests: POST_OUT)
RUN=${POST_RUN:-rsn3_4b_r3}; R=${POST_RUNDIR:-$HOME/smartcity_runs/$RUN}; NAME=${POST_NAME:-rsn_v3_4b_r3}
BASE=${POST_BASE:-$HOME/models/qwen3.5-4b}; CH=${POST_CHAIN_DIR:-$H/chain}; BATONF=${POST_BATON:-$H/baton/BATON}
PK=${POST_PICK_DIR:-$HOME/smartcity_runs/${RUN}_post}
export STOPF=$D/STOP STAGE_DIR=${STAGE_DIR:-$QIDK/Code/models_stage} LOGD=$D/export_r3 GATE_OUT=$D/gate_r3
G=$STAGE_DIR/${NAME}_q4_0.gguf
if [ -s "$D/post.pid" ] && kill -0 "$(cat "$D/post.pid")" 2>/dev/null; then die "post_chain already running (pid $(cat "$D/post.pid"))" 8; fi
echo $$ > "$D/post.pid"; trap 'rm -f "$D/post.pid"' EXIT
stopchk() { [ -e "$STOPF" ] && { status "STOP file: post chain stops (rm post/STOP and relaunch to resume)"; exit 0; }; }
isdone() { [ -e "$MK/$1.done" ]; }
done_() { echo "$(date -Is) ${2:-}" > "$MK/$1.done"; status "step $1 done${2:+: $2}"; }
status "post chain start (pid $$, run $R, steps done: $(ls "$MK" 2>/dev/null | sed 's/.done//' | tr '\n' ' '))"

finished() {
  [ -e "$CH/train.done" ] && return 0
  grep -qE '"stopped": "(after_epoch1|early_stop)"|"done": true' "$R/status.json" 2>/dev/null
}
holder() { local h; h=$(sed -n 's/^holder=//p' "$BATONF" 2>/dev/null | tail -1); echo "${h:-laptop}"; }
busy() {   # prints why the run dir is not safe to read, nothing when idle
  pgrep -f "train_rsn3.py.*$RUN( |$)" > /dev/null && { echo "trainer running"; return; }
  local p; p=$(cat "$CH/chain.pid" 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null && { echo "chain_4b running (pid $p)"; return; }
  pgrep -f "[t]o_kaggle.sh|[f]rom_kaggle.sh" > /dev/null && { echo "baton hop in progress"; return; }
}

# ---- wait
if ! isdone wait; then
  last=""
  while true; do
    stopchk
    why=""
    finished || why="training not finished (step $(grep -oE 'step [0-9]+/' "$R/train.log" 2>/dev/null | tail -1 | tr -dc 0-9))"
    [ -z "$why" ] && [ "$(holder)" != laptop ] && why="baton holder=$(holder)"
    [ -z "$why" ] && [ -e "$R/BATON_AT_KAGGLE" ] && why="BATON_AT_KAGGLE in the run dir"
    [ -z "$why" ] && why=$(busy)
    [ -z "$why" ] && [ ! -s "$R/best.json" ] && why="no best.json"
    [ -z "$why" ] && break
    w=${why%% (*}; [ "$w" != "$last" ] && status "waiting: $why"; last=$w
    for i in $(seq 1 20); do [ -e "$STOPF" ] && break; sleep 30; done
  done
  done_ wait "finished ($(grep -oE '"stopped": "[a-z_0-9]+"' "$R/status.json" 2>/dev/null)$( [ -e "$CH/train.done" ] && echo ' train.done'))"
fi
stopchk

# ---- pick
if ! isdone pick; then
  [ -z "$(busy)" ] || die "pick: $(busy)" 7
  python3 - "$R" "$PK" "$D/pick.json" <<'EOF' > "$D/pick.log" 2>&1 || die "pick failed: $(tail -n 2 "$D/pick.log" | tr '\n' ' ')"
import hashlib, json, os, shutil, sys, time
R, PK, out = sys.argv[1:4]
b = json.load(open(os.path.join(R, "best.json")))
top = sorted(b.get("top") or [], key=lambda x: (-x[0], -x[1]))
gen = {}
gp = os.path.join(R, "gen_eval.jsonl")
if os.path.exists(gp):
    for l in open(gp):
        try:
            r = json.loads(l); gen[r["step"]] = r
        except Exception:
            pass
src, why = None, ""
for sc, st in top:
    d = os.path.join(R, "ckpt_best_%04d" % st)
    if all(os.path.isfile(os.path.join(d, f)) and os.path.getsize(os.path.join(d, f)) > 0 for f in ("adapter_model.safetensors", "adapter_config.json")):
        src, why = (sc, st, d), "best by gen dev score"
        break
    print("skip missing %s" % d)
if src is None:
    sys.exit("no ckpt_best_XXXX with an adapter for best.json top %s (not picking ckpt_epoch1/latest silently)" % top)
sc, st, d = src
dst = os.path.join(PK, "ckpt_best_%04d" % st)
os.makedirs(dst + ".part", exist_ok=True)
md5 = {}
for f in ("adapter_model.safetensors", "adapter_config.json"):
    shutil.copyfile(os.path.join(d, f), os.path.join(dst + ".part", f))
    for p in (os.path.join(d, f), os.path.join(dst + ".part", f)):
        hh = hashlib.md5()
        with open(p, "rb") as fh:
            for c in iter(lambda: fh.read(1 << 22), b""):
                hh.update(c)
        md5.setdefault(f, []).append(hh.hexdigest())
    assert md5[f][0] == md5[f][1], "copy md5 mismatch " + f
if os.path.exists(dst):
    shutil.rmtree(dst)
os.rename(dst + ".part", dst)
st_json = {}
try:
    st_json = json.load(open(os.path.join(R, "status.json")))
except Exception:
    pass
json.dump({"step": st, "score": sc, "why": why, "src": d, "adapter": dst, "md5": {k: v[0] for k, v in md5.items()}, "best_json": b,
           "gen_eval_at_step": gen.get(st), "status_json": st_json, "time": time.strftime("%Y-%m-%d %H:%M:%S")}, open(out, "w"), indent=1)
print("picked step %d score %s -> %s" % (st, sc, dst))
EOF
  done_ pick "$(tail -n 1 "$D/pick.log")"
fi
stopchk

# ---- export
if ! isdone export; then
  A=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['adapter'])" "$D/pick.json")
  bash "$P/export_4b.sh" "$BASE" "$A" "$NAME" || die "export failed (rc $?)"
  stopchk
  [ -s "$G" ] && [ -s "$G.md5" ] || die "export: no $G after export_4b.sh"
  done_ export "$G md5 $(cut -d' ' -f1 "$G.md5")"
fi
stopchk

# ---- gate
if ! isdone gate; then
  bash "$P/gate_4b.sh" "$G"; rc=$?
  case $rc in
    0|1) done_ gate "$( [ $rc = 0 ] && echo PASS || echo FAIL ) -> $D/gate_r3/GATE.md";;
    3) exit 0;;                                              # STOP file inside the gate
    *) die "gate rc $rc (see $D/gate_r3/; relaunch resumes from the last finished step)" $rc;;
  esac
fi
status "post chain DONE: $G ($(cut -d' ' -f1 "$G.md5")), gate $(python3 -c "import json;print(json.load(open('$D/gate_r3/gate.json'))['verdict'])" 2>/dev/null) ($D/gate_r3/GATE.md). Board deployment: owner decides."
