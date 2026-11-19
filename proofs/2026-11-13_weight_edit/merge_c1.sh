# reasoner: r3-2800 (base + LoRA) merged + kept neuron edits C1 (A2g rewires + B1 agent-normal detectors x0.2) -> bf16 base for the fine-tune
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
O=/mnt/c/Users/hp/qidk_models/r3_edit_C1; mkdir -p $O
CUDA_VISIBLE_DEVICES= nice -n 15 ~/venvs/rsn/bin/python merge_neuron.py ~/models/qwen3.5-4b ~/smartcity_runs/KEEP_rsn3_4b_r3_s2800/ckpt_best_2800 $O tweaks/C1_A2g_B1.json ~/we_work/dir_close_grad.npy
cp ~/we_work/dir_close_grad.npy $O/; echo MERGE_DONE
