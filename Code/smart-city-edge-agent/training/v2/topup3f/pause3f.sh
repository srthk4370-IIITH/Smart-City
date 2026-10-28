#!/usr/bin/env bash
# pause3f.sh STOP|CONT : send SIGSTOP / SIGCONT to the 3f jobs (used by ramguard3f.ps1). Excludes itself.
PAT='master[0-9]*_3f.sh|master[0-9]*_3g.sh|pipe_lora.sh|conv_lora_3f.sh|convert_lora_to_gguf|gen_rw5.py|mix_to_lora.py|build_rw5sft.py|review_v2.py|pipe_3f.sh|queue_train_3f.sh|agents_v2_topup3f|llama-cuda-shim/build-host/bin/llama-server|post_3f.sh|merge_mix.py|convert_hf_to_gguf|llama-quantize|train_3e.py|anchor_3f.py'
for p in $(pgrep -f "$PAT"); do [ $p != $$ ] && [ $p != $PPID ] && kill -$1 $p 2>/dev/null; done
