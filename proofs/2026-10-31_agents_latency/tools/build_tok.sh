#!/bin/bash
L=$HOME/gpu_work/llama.cpp
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_agents_latency/tools
g++ -O2 -std=gnu++17 -I$L/include -I$L/ggml/include tok.cpp -o $HOME/tok -L$L/build-host/bin -Wl,-rpath,$L/build-host/bin -lllama -lggml -lggml-base || exit 1
printf '{"pattern": "step_increase\x1e<|eot_id|>hello' | $HOME/tok $L/models/ggml-vocab-llama-bpe.gguf 2>/dev/null
