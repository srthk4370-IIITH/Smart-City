cd ~/gpu_work; nm -D llama.cpp/build-host/bin/libllama.so | grep -c "llama_n_rs_seq\|llama_memory_seq_cp"; nm -D llama.cpp/build-host/bin/libllama.so | grep "n_rs_seq\|model_is_hybrid"
ls -la htpd_v8x3_host/ llama.cpp/build-host/bin/libllama.so
grep -n "n_rs_seq" llama.cpp/include/llama.h | head -3
diff <(grep -v "^$" llama.cpp/include/llama.h) <(grep -v "^$" /mnt/c/Users/hp/gpu_work/llama.cpp/include/llama.h) | head -20
ls ~/gpu_work/dev | head
