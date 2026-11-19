# Cleanup 2026-11-06 (owner: "delete what is not needed, keep its proof, never delete what is needed")

md5 + size of every deleted model file: `DELETED_MD5S.txt`. Logs/manifests kept in this dir.

## Round 1 (03:00 IST): 7.3 GB in WSL
| deleted | why not needed | proof kept |
|---|---|---|
| ~/smartcity_runs/rsn3_2b_r2bench_base, rsn3_2b_r2bench_mt6144 | 2B speed benches, finished | proofs/2026-11-02_2b_r2/bench |
| rsn3_2b_r1/probe, rsn3_2b_r2/probe, all *_tok.pt there | fit probes + token caches, regenerated in minutes | maxlen.json in the run dirs |
| ~/.cache/go-build | Go build cache, regenerated on build | - |

## Round 2 (13:20 IST): 9.6 GB in WSL + 1.15 GB on C:
| deleted | why not needed | proof kept |
|---|---|---|
| ~/smartcity_runs/fit4b_probe (1.3 GB) | r2 token caches for the 4B; the run uses r3 caches (fit4b_r3, kept) | FIT.md, logs/ |
| ~/smartcity_runs/rsn3_2b_r1 (1.0 GB) | 2B r1 run, superseded by r2 (live) | rsn3_2b_r1/ here (train.log, losses, gen_eval, best.json); gate proofs/2026-10-29_rsn_v3/kaggle/gate/g2b_r1 |
| Code/models_stage/rsn_v3_2b_q4_0.gguf (1.15 GB) | 2B r1 GGUF, not on the board (board runs r2) | .md5 next to it, gate g2b_r1 |
| agents_v2/post/gguf/ft_v2_q4_0.gguf + imatrix_v2.gguf (2.7 GB) | domain agent v2, superseded by ft_B50 (live, from agents_v2_topup3f, kept) | agents_v2_gguf/ here; agents_v2/post/eval kept |
| ~/models/llama-3.2-3b-instruct-gguf/...q4_0.gguf (1.8 GB) | base Llama Q4 for the P0 benchmark (done); HF base kept, re-quantisable | P0 results in proofs |
| ~/models/qwen3.5-4b-gguf/qwen3.5-4b-q4_0.gguf (2.6 GB) | base 4B Q4 for P0 (done); HF base + q8_0 kept | P0 results |
| docker images hello-world, nvidia/cuda:12.6.0-base (0.36 GB) | test images from the abandoned docker build | - |

## Kept on purpose
HF bases (qwen3.5-2b, qwen3.5-4b, qwen3.5-4b-nf4, llama-3.2-3b-instruct), qwen3.5-4b-q8_0 (replay), reasoner_v1 (live 4B source),
rsn3_2b_r2 (live 2B source), agents_v2_topup3f (live ft_B50 source), agents_v2 adapters, fit4b_r3 (live run caches),
gpu_work (board chat server build), venvs/train (GGUF export), venvs/rsn, venvs/kaggle, qairt/ndk/android-sdk (board builds).
RAM: closed WhatsApp and Edge (owner asked); left Chrome, zebar, Omen Command Center (fans), system processes.
WSL space returns to Windows gradually (sparseVhd) or via the owner's compact script.
