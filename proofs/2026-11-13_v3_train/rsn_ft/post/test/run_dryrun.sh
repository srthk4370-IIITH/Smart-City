#!/usr/bin/env bash
# run_dryrun.sh [n]: CPU dry run of gate_ft.sh with the stub server (test/stub_server.py), n items per suite (default 8; v4 incident files round-robin over reasoning types).
# No GPU (DRYRUN=1: no nvidia-smi wait, no GPU_LOCK, no llama-server), no board, nothing written outside <post>/test/dry_<time>.
# Checks: every step ran and resumes (a second launch does nothing), every hard-check group was computed, the stub's planted
# failures show up as failed checks (so the verdict is FAIL), and every info section exists.
# Then the text metrics self-test and the export guard (refuses a missing adapter) are checked.
set -u
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/rsn_ft/post
N=${1:-8}; O=$P/test/dry_$(date +%Y%m%d_%H%M%S); mkdir -p "$O"
ok=0; bad=0; t() { if eval "$2"; then echo "PASS $1"; ok=$((ok+1)); else echo "FAIL $1"; bad=$((bad+1)); fi; }
echo "fake candidate (dry run)" > "$O/fake_cand_q4_0.gguf"
export DRYRUN=1 LIMIT=$N GATE_OUT=$O/gate POST_STATUS=$O/status.md STOPF=$O/STOP EARLY_STOP=0 PORT=18190 \
  SERVER_CMD="python3 $P/test/stub_server.py" CUDA_VISIBLE_DEVICES= GATE_TAG=dry_cand
t0=$(date +%s)
bash "$P/gate_ft.sh" "$O/fake_cand_q4_0.gguf" > "$O/gate_run1.log" 2>&1; rc1=$?
t1=$(date +%s)
bash "$P/gate_ft.sh" "$O/fake_cand_q4_0.gguf" > "$O/gate_run2.log" 2>&1; rc2=$?
echo "run 1 rc=$rc1 ($((t1 - t0)) s), run 2 rc=$rc2 ($(( $(date +%s) - t1 )) s)"
G=$O/gate/gate_ft.json
t "gate ran to the end (rc 0/1/2)" "[ $rc1 -le 2 ] && [ -s $G ] && [ -s $O/gate/GATE_FT.md ]"
t "second launch skips every step" "[ $rc2 = $rc1 ] && ! grep -q 'done (' <(grep -v score $O/gate_run2.log)"
t "every step has a marker" "[ \$(ls $O/gate/.m | wc -l) -ge 21 ]"
t "no GPU_LOCK written by the dry run" "! grep -q dry_cand /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK 2>/dev/null"
python3 - "$G" > "$O/check_groups.txt" <<'EOF'
import json, sys
g = json.load(open(sys.argv[1]))
groups = sorted({c["group"].split()[0] for c in g["checks"]})
print("verdict", g["verdict"], "checks", g["n_checks"], "failed", g["n_failed"])
print("groups", " ".join(groups))
print("missing", g["missing"])
for c in g["checks"]:
    print("  %-4s %-16s %-36s %-34s new=%s base=%s" % ("ok" if c["ok"] else "FAIL", c["group"], c["suite"][:36], c["metric"][:34], c["new"], c["base"]))
print("info", " ".join(g["info"]))
EOF
cat "$O/check_groups.txt"
t "hard groups H1..H11 all computed" "grep -q '^groups H1 H10 H11 H2 H3 H4 H5 H6 H7 H8 H9$' $O/check_groups.txt"
t "planted failures detected (verdict FAIL)" "grep -q '^verdict FAIL' $O/check_groups.txt"
t "nothing missing" "grep -q '^missing \[\]' $O/check_groups.txt"
t "BLEU/ROUGE/chrF + taxonomy + real-agent info present" "grep -q text_chat $O/check_groups.txt && grep -q text_v4_incidents $O/check_groups.txt && grep -q taxonomy_by_type_hops $O/check_groups.txt && grep -q real_agent_claims $O/check_groups.txt"
t "text metrics self-test" "python3 $P/text_metrics.py > $O/text_metrics.log 2>&1"
mkdir -p "$O/noadapter"
POST_STATUS=$O/status.md STAGE_DIR=$O/stage LOGD=$O/export_log bash "$P/export_ft.sh" "$O/noadapter" "$O/noadapter" dry_none > "$O/export_guard.log" 2>&1; erc=$?
t "export refuses a dir without an adapter (rc 2)" "[ $erc = 2 ] && grep -q 'no adapter' $O/export_guard.log"
echo "dry run: $ok pass, $bad fail -> $O"
[ $bad = 0 ]
