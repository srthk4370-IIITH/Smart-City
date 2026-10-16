GGML_OPENCL_Q40_MC3=1 ./llama-batched-bench -m ft_device_q4exact.gguf -ngl 99 -fa off -kvu -c 8192 -b 512 -ub 512 -npp 600 -ntg 80 -npl 1,2,3,4,6,8
