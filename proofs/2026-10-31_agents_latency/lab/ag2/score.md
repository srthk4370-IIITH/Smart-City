base: 24 requests, wall sum 62.24 s (mean 2594 ms), prefill 15.95 s, after-prefill 46.29 s, draft steps 552, ms/step after prefill 83.9
v9e: 24 requests, wall sum 49.39 s (mean 2058 ms), prefill 17.04 s, after-prefill 32.35 s, draft steps 366, ms/step after prefill 88.4
base2: 24 requests, wall sum 67.35 s (mean 2806 ms), prefill 18.00 s, after-prefill 49.35 s, draft steps 552, ms/step after prefill 89.4
identical outputs base vs base2: 24/24 requests  diff []
identical outputs base vs v9e: 23/24 requests  diff ['a09']
identical outputs base2 vs v9e: 23/24 requests  diff ['a09']
base a00b (after swap) same as base a00: True
v9e a00b (after swap) same as v9e a00: True
base2 a00b (after swap) same as base2 a00: True
