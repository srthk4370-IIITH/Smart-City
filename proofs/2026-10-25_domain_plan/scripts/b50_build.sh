#!/usr/bin/env bash
# Standalone B50 build (run in MAIN's shell): mixA50 + 0.5 (v21 - v2) merged in bf16 (merge_mix, layer-wise, low RAM) -> f16 GGUF
# -> Q4_0 with the mixA50/v2 recipe (imatrix_v2, ffn_down q4_0, output q8_0, token_embd f16; post_3f.sh) -> stage in Code/models_stage
# (.part + md5 + mv) -> proofs/2026-10-25_domain_plan/B50_STAGED.json. Resumable (post_3f skips finished steps). CPU only.
R=~/smartcity_runs/agents_v2_topup3f; D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; STAGE=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage
exec >> $D/b50_build.log 2>&1 < /dev/null; echo "=== $(date -u +%FT%TZ) b50_build"
mkdir -p $R/post/B50 $STAGE
cat > $R/post/B50/choice.json <<J
{"mix": [["$R/m50_adapter", 1.0], ["$HOME/smartcity_runs/agents_v21/run1/checkpoints/checkpoint-621", 0.5], ["$HOME/smartcity_runs/agents_v2/adapter", -0.5]],
 "chosen": "B50", "note": "mixA50 + 0.5 (v21 - v2); m50_adapter = exact LoRA form of mixA50 (the 3e run2/c49 dir is no longer on disk)"}
J
[ -s $R/post/gguf/ft_B50_q4_0.gguf ] || { rm -rf $R/post/B50/merged.tmp; bash /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f/post_3f.sh none B50; }
Q=$R/post/gguf/ft_B50_q4_0.gguf
[ -s $Q ] || { echo "BUILD FAILED, see $R/post/B50/post.log"; tail -5 $R/post/B50/post.log; exit 1; }
cp $Q $STAGE/ft_B50_q4_0.gguf.part && md5sum $STAGE/ft_B50_q4_0.gguf.part | cut -d" " -f1 > $STAGE/ft_B50_q4_0.gguf.md5 && mv -f $STAGE/ft_B50_q4_0.gguf.part $STAGE/ft_B50_q4_0.gguf
python3 - $R/post/B50/gguf_check.json $STAGE/ft_B50_q4_0.gguf.md5 $D/B50_STAGED.json <<'P'
import json, sys, os
chk = json.load(open(sys.argv[1])) if os.path.exists(sys.argv[1]) else None
out = {"model": "B50 = mixA50 + 0.5 (v21 - v2)", "staged": "/mnt/c/Users/hp/Desktop/qidk/Code/models_stage/ft_B50_q4_0.gguf",
       "md5": open(sys.argv[2]).read().strip(), "gguf_check_vs_v2_recipe": chk,
       "gate2": "PASS: dev3f net +1 (CI -39..+40), severity +61, E1 +4, safety 16/16, no Holm-worse slice (diag/gate2_p2p3.json)",
       "parity_runtime_lora_vs_q4": "not run (GPU busy with P3b); B50 is a plain linear mix, merged exactly like mixA50"}
json.dump(out, open(sys.argv[3], "w"), indent=1); print(json.dumps(out)[:300])
P
echo "=== $(date -u +%FT%TZ) B50 staged md5 $(cat $STAGE/ft_B50_q4_0.gguf.md5)"
