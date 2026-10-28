#!/usr/bin/env bash
# After pipeline1: domain imatrix (3d) -> candidates -> host evals. Each heavy step behind gate.sh.
S=/c/Users/hp/Desktop/qidk/proofs/2026-10-23_3d_quant_fix/scripts; SW=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-23_3d_quant_fix/scripts
P1="C:/Users/hp/AppData/Local/Temp/claude/C--Users-hp-Desktop-qidk/125df7ac-c9eb-46de-b63b-ce87f4c7e8ce/tasks/bxbds3c50.output"
until grep -q "PIPELINE1 DONE" "$P1"; do sleep 60; done
DC="wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'"
IMX=/home/hp_srthk4370/smartcity_runs/agents_v2_topup3d/post/gguf_fix/imatrix_dom_3d.gguf
$S/gate.sh wsl.exe -d Ubuntu -- bash $SW/step3_imatrix.sh 3d; eval $DC
q() { $S/gate.sh wsl.exe -d Ubuntu -- bash $SW/step3_quant.sh 3d "$@"; }
q dimx $IMX 'ffn_down=q4_0'
q dimx_v8_d8 $IMX 'attn_v=q8_0' 'ffn_down=q8_0'
q dimx_v8_edge8 $IMX 'attn_v=q8_0' 'blk\.(0|1|2|25|26|27)\.ffn_down=q8_0' 'ffn_down=q4_0'
G=/home/hp_srthk4370/smartcity_runs/agents_v2_topup3d/post/gguf_fix
$S/run_evals.sh 3d_dimx=$G/ft_v2t3d_dimx.gguf 3d_dimx_v8_d8=$G/ft_v2t3d_dimx_v8_d8.gguf 3d_dimx_v8_edge8=$G/ft_v2t3d_dimx_v8_edge8.gguf
echo PIPELINE2 DONE
