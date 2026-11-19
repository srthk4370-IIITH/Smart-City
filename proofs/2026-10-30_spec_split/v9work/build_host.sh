#!/bin/bash
# host (WSL x86 CPU) build of htpd against ~/gpu_work/llama.cpp (620d2225, same headers as the board build) build-host libs
# usage: build_host.sh <src dir> <out binary>
set -e
L=~/gpu_work/llama.cpp
g++ -std=gnu++17 -O2 -g -DNDEBUG -I$L/include -I$L/ggml/include -Wall -Wextra -Wno-unused-function -o "$2" "$1/htpd.cpp" \
  -L$L/build-host/bin -Wl,-rpath,$L/build-host/bin -lllama -lggml -lggml-base -lggml-cpu -pthread
md5sum "$2"
