./bin/llama-batched-bench -m /data/local/tmp/gpu/ft_device_q4exact.gguf --device HTP0 -ngl 99 -fa on -c 1024 -b 256 -ub 256 -npp 128 -ntg 16 -npl 1
