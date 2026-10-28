#!/usr/bin/env bash
S=/c/Users/hp/Desktop/qidk/proofs/2026-10-23_3d_quant_fix/scripts
until grep -q "STEP2B DONE" "C:/Users/hp/AppData/Local/Temp/claude/C--Users-hp-Desktop-qidk/125df7ac-c9eb-46de-b63b-ce87f4c7e8ce/tasks/bimoehj8g.output"; do sleep 30; done
$S/step2c.sh
H=/home/hp_srthk4370/smartcity_runs
$S/run_evals.sh 3d_q4_0_deployed=$H/agents_v2_topup3d/post/gguf/ft_v2t3d_q4_0.gguf \
                3d_q8_0=$H/agents_v2_topup3d/post/gguf_fix/work/ft_v2t3d_q8_0.gguf \
                v2_q8_0=$H/agents_v2_topup3d/post/gguf_fix/work/ft_v2_q8_0.gguf \
                v2_q4_0_deployed=$H/agents_v2/post/gguf/ft_v2_q4_0.gguf
echo PIPELINE1 DONE
