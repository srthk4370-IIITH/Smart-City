L=$HOME/llama-cuda-b11815/bin
export LD_LIBRARY_PATH=$L:$LD_LIBRARY_PATH
exec $L/llama-server -m /mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v3_4b_v5_q4_0.gguf -c 16384 -np 2 -ngl 99 -fa auto --port 8291 --host 127.0.0.1 -t 4 --no-webui > /mnt/c/Users/hp/AppData/Local/Temp/claude/5cb597a87cde10fb/125df7ac-c9eb-46de-b63b-ce87f4c7e8ce/scratchpad/heat/srv.log 2>&1
