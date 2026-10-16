./bin/llama-batched-bench -m /data/local/tmp/gpu/ft_device_q4exact.gguf --device HTP0 -ngl 99 -fa on -c 12288 -ctk q8_0 -ctv q8_0 -b 512 -ub 512 -npp 600 -ntg 80 -npl 13
