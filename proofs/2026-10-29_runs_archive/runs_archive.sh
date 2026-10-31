#!/usr/bin/env bash
# Owner 2026-10-29: free C: (WSL disk), keep proofs. 1) copy every small metadata/result file of ~/smartcity_runs (json, md,
# txt, log, yaml, csv, py, sh; no .jsonl row data, no weights; <= 20 MB) into proofs/2026-10-29_runs_archive/runs/,
# 2) record size + md5 of every weight file that is removed (MANIFEST.md), 3) remove only the files listed in DEL below:
# rejected or intermediate checkpoints and duplicate GGUFs. Kept: B50 adapter (young-window training starts from it),
# imatrix files, data sets, eval outputs, the HF base models (gated downloads), venvs. Symlinks were checked: the only
# links point at data files (eval3e/dev3f/rw5), none of which are removed.
set -u
R=~/smartcity_runs; P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_runs_archive; mkdir -p $P/runs
DEL=(
  "$R/agents_v2/post/gguf/ft_v2_f16.gguf|v2 f16 intermediate (superseded by B50; v2 results: HANDBOOK 2.42-2.45)"
  "$R/agents_v2/post/gguf/ft_v2_q4_0.gguf|v2 Q4_0 (superseded by B50)"
  "$R/agents_v2/merged_v2|merged v2 HF weights (B50 adapter kept in agents_yw/b50_adapter)"
  "$R/agents_v2_topup3f/post/gguf/ft_mixA50_q4_0.gguf|mixA50 (previous live agents; superseded by B50, HANDBOOK 2.5x)"
  "$R/agents_v2_topup3f/post/gguf/ft_T30_q4_0.gguf|T30 rejected (gate2 FAIL vs B50, HANDBOOK 2.54b)"
  "$R/agents_v2_topup3f/post/gguf/ft_B50_q4_0.gguf|duplicate of Code/models_stage/ft_B50_q4_0.gguf (md5 bfdca67b)"
  "$R/agents_v2_topup3f/p2|P2 blend candidates T30/T20/D90 (rejected; diag/gate2_* in proofs)"
  "$R/agents_v2_topup3f/lora_gguf|LoRA GGUFs of the P2 candidates (rejected)"
  "$R/agents_v2_topup3f/m50rw|intermediate top-up checkpoints"
  "$R/agents_v2_topup3f/m50rwB|intermediate top-up checkpoints"
  "$R/agents_p3/run_b/checkpoints|P3b checkpoints (all P3b blends failed gate2, HANDBOOK 2.54)"
  "$R/reasoner_v1/gguf/rsn_v2|rsn_v2 GGUF (rejected: RWH 106 severity 87.6% vs 94.7%, HANDBOOK 2.59)"
  "$R/reasoner_v1/gguf/rsn_v1|duplicate of Code/models_stage/rsn_v1_q4_0.gguf (md5 5ff2e1bc)"
  "$HOME/models/qwen3.5-4b-gguf|base-model GGUF (host baseline evals only; HF base kept)"
  "$HOME/models/llama-3.2-3b-instruct-gguf|base-model GGUF (host baseline evals only; HF base kept)"
)
# 1) small results
cd $R && find . -type f -size -20M \( -name '*.json' -o -name '*.md' -o -name '*.txt' -o -name '*.log' -o -name '*.yaml' -o -name '*.yml' -o -name '*.csv' -o -name '*.py' -o -name '*.sh' \) \
  ! -name 'tokenizer*.json' ! -name 'vocab.json' -print0 | while IFS= read -r -d '' f; do mkdir -p "$P/runs/$(dirname "$f")"; cp -p "$f" "$P/runs/$f"; done
echo "copied $(find $P/runs -type f | wc -l) small result files ($(du -sh $P/runs | cut -f1))"
# 2) manifest of removed weights
{
  echo; echo "## WSL ~/smartcity_runs and ~/models (removed $(date -u +%FT%TZ))"
  echo "Small result files of every run (metrics, trainer states, configs, eval summaries, logs) are copied to runs/ next to this file."
  echo; echo "| removed | size | md5 (files) | why |"; echo "|---|---|---|---|"
} >> $P/MANIFEST.md
for e in "${DEL[@]}"; do
  p=${e%%|*}; why=${e#*|}
  [ -e "$p" ] || { echo "| ${p/#$HOME/~} | (missing) | - | $why |" >> $P/MANIFEST.md; continue; }
  sz=$(du -sb "$p" | cut -f1)
  if [ -f "$p" ]; then m=$(md5sum "$p" | cut -c1-32); else m="$(find "$p" -type f -size +100M -exec md5sum {} + | awk '{n=$2; sub(".*/","",n); printf "%s %s; ", substr($1,1,12), n}')"; fi
  echo "| ${p/#$HOME/~} | $(awk -v s=$sz 'BEGIN{printf "%.2f GB", s/1073741824}') | ${m:-small files only} | $why |" >> $P/MANIFEST.md
done
# 3) remove
for e in "${DEL[@]}"; do p=${e%%|*}; [ -e "$p" ] && rm -rf -- "$p"; done
echo "done; ~/smartcity_runs now $(du -sh $R | cut -f1), ~/models $(du -sh ~/models | cut -f1); df / : $(df -h / | tail -1)"
echo "The Windows file ext4.vhdx shrinks only after compaction (wsl --shutdown + diskpart compact vdisk, admin)." >> $P/MANIFEST.md
