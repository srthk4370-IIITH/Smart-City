./bin/llama-batched-bench -m /data/local/tmp/gpu/ft_device_q4exact.gguf --device HTP0 -ngl 99 -fa on -c 4096 -b 512 -ub 512 -npp 600 -ntg 80 -npl 1,2,4
