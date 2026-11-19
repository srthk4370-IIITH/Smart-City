#!/usr/bin/env bash
# dryrun.sh: whole Kaggle top-up pipeline on a tiny subset, CPU only, NO Kaggle calls (fake CLI), NO GPU, NO adb, real GPU_LOCK untouched,
# original agt_v3 STATE / lineage / work untouched (everything under $DRY). Run in WSL:  bash dryrun.sh
set -u -o pipefail
TK=$(dirname "$(readlink -f "$0")"); Q=/mnt/c/Users/hp/Desktop/qidk; AG=$Q/proofs/2026-11-13_v3_train/agt
export DRY=${DRY:-$HOME/dry_topup_k}; rm -rf "$DRY"; mkdir -p "$DRY/kdir" "$DRY/pf"
export TOPUP_K=$DRY/k STATUS=$DRY/STATUS.md STOPF=$DRY/STOP KDIR=$DRY/kdir KAGGLE=$TK/dryrun_stubs/fakekaggle KAGGLE_USER=dryuser
export REAL_APPROVED=$DRY/pf/REAL_APPROVED.json REAL_EXCEPTION_LOG=$DRY/REAL_EXCEPTION.log GEN_N=10 KDS_POLL_S=1 LIVE_POLL_S=1
export GPU_LOCK=$DRY/GPU_LOCK_FAKE GPU_ASSUME_FREE=1 FINAL_K=$DRY/FINAL_K OLDREF=$DRY/no_old_ref G0=$DRY/snap_1750_g0.gguf
echo fake > "$KDIR/access_token"; chmod 600 "$KDIR/access_token"; echo fake > "$G0"
ok() { echo "[dry] $*"; }; bad() { echo "[dry] FAIL: $*"; exit 1; }
# 1. mix (96 rows, 75 % real) into the dry area
python3 "$TK/build_mix.py" 96 0.75 --out="$TOPUP_K" --pf="$DRY/pf" --gen-n=10 || bad build_mix
sed -i "s#/home/[^\"]*/agt_topup_k/local/val_sel.jsonl#$TOPUP_K/local/val_sel.jsonl#" "$REAL_APPROVED"
ok "mix built: $(python3 -c "import json;d=json.load(open('$DRY/pf/mix_manifest.json'));print(d['n_total'],d['real'],d['synthetic'],'steps',d['steps_1_pass'])")"
# 2. negative tests of the data check: wrong md5 and a real row without the exception must be refused
mkdir -p "$DRY/neg"; cp "$TOPUP_K/mixdata/gendev.jsonl" "$DRY/neg/"; head -n -1 "$TOPUP_K/mixdata/train.jsonl" > "$DRY/neg/train.jsonl"
o=$(python3 -I "$TK/check_data_topup.py" "$DRY/neg/train.jsonl" "$DRY/neg/gendev.jsonl" "$Q/proofs/2026-11-13_v3_data/calib_stats.json" 10 "$DRY/neg/out"); echo "$o" | grep -q "REFUSED: train/gendev md5" && ok "tampered train.jsonl refused (md5 pin)" || bad "md5 pin"
o=$(python3 -I "$AG/check_data.py" "$TOPUP_K/mixdata/train.jsonl" "$TOPUP_K/mixdata/gendev.jsonl" "$Q/proofs/2026-11-13_v3_data/calib_stats.json" 10 "$DRY/neg/out2"); echo "$o" | grep -q REFUSED && ok "ORIGINAL check_data.py still refuses these real rows (exception is local to the topup checker)" || bad "original checker"
# 3. push (fake Kaggle): data check with exception, tensor hashes (cached copy), token fingerprint on CPU, lineage.bin seeded from snap_1750
mkdir -p "$TOPUP_K/work"; cp "$HOME"/smartcity_runs/agt_v3/work/tensor_sha_*.json "$TOPUP_K/work/"
bash "$TK/push_topup.sh"; rc=$?; ok "push_topup.sh rc $rc"; [ $rc = 0 ] || { tail -n 5 "$DRY/STATUS.md"; bad push; }
ls "$DRY/pushed"; python3 - <<P
import json,tarfile,glob
c=json.load(open("$DRY/live_cfg.json")); print("[dry] cfg: seq",c["seq"],"step",c["step"],"fresh",c["fresh"],"recipe",c["recipe"]["lr"],c["recipe"]["epochs"],c["save_every"],c["snap_every"],c["gen_n"],c["patience"])
b=glob.glob("$DRY/pushed/*/lineage.bin")[0]; print("[dry] lineage.bin:",sorted(tarfile.open(b).getnames()))
k=json.load(open("$DRY/kernel_pushed/kernel-metadata.json")); print("[dry] kernel:",k["id"],k["dataset_sources"],"private",k["is_private"])
P
tail -n 3 "$DRY/REAL_EXCEPTION.log" | cut -c1-200
# 4. pull (fake Kaggle output: steps 50/100/150, three snapshots)
O=$DRY/fake_out; mkdir -p "$O" "$DRY/mk/ckpt_latest"
for s in 0050 0100 0150; do mkdir -p "$DRY/mk/snap_$s"; echo '{}' > "$DRY/mk/snap_$s/adapter_config.json"; done
echo x > "$DRY/mk/ckpt_latest/state.pt"; echo '{"step": 150, "n_steps": 313}' > "$DRY/mk/status.json"
(cd "$DRY/mk" && find . -type f | sed 's|^\./||' | sort | xargs md5sum > ../MD5SUMS.tmp && mv ../MD5SUMS.tmp MD5SUMS && tar -cf "$O/lineage.tar" $(find . -type f ! -name MD5SUMS | sed 's|^\./||' | sort) MD5SUMS)
(cd "$O" && md5sum lineage.tar > lineage.tar.md5); echo '{"ok": true, "rc": 0, "step_to": 150, "session_h": 0.1}' > "$O/KAGGLE_RESULT.json"
POLL_S=1 bash "$TK/pull_topup.sh" --once; rc=$?; ok "pull_topup.sh rc $rc; run/: $(ls "$TOPUP_K/run" | tr '\n' ' ')"
# 5. selection + no-harm (stub export + stub eval, fake lock): s0100 harms synthetic/unseen and must be rejected
export EXPORT_CMD=$TK/dryrun_stubs/export_stub.sh EVAL_CMD="python3 $TK/dryrun_stubs/eval_stub.py"
bash "$TK/select_topup.sh"; rc=$?; ok "select_topup.sh rc $rc"
cat "$FINAL_K" 2>/dev/null; python3 -c "import json;d=json.load(open('$TOPUP_K/post/selection_k.json'));print('[dry] best_step',d['best_step'],'harm',{c['step']:c['harm'] for c in d['curve']})"
ok "done"
