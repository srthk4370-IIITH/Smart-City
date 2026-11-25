# rsn_v3 local pipeline status (append-only)

- 2026-11-24 22:13:06 [rsn_final final] nproc=8 -> 7 CPU threads, normal priority, no GPU throttle (owner away 8-9 h)
- 2026-11-25 03:44:19 [claude] owner: WSL 8GB/10 cores, closed Lively mpv/WhatsApp/Flow; restart final run (was still tokenizing)
- 2026-11-24 22:14:42 [rsn_final final] nproc=10 -> 9 CPU threads, normal priority, no GPU throttle (owner away 8-9 h)
- 2026-11-24 22:17:21 [rsn_final final] free RAM 1121 MB < 1500: page-cache drop requested
- 2026-11-25 01:36:27 [rsn_final final] chunk 1 rc=1
- 2026-11-25 01:48:55 [rsn_final final] free RAM 1078 MB < 1500: page-cache drop requested
- 2026-11-25 07:33:12 [claude] step-50 gen eval crashed (CUDA allocator INTERNAL ASSERT in chat generate, gen budget 12000). Fix: budget 8000, assert caught like OOM (retry/skip), missing eval re-run on resume. Kill + relaunch from ckpt 50 so the step-50 eval runs
- 2026-11-25 02:03:21 [rsn_final final] nproc=10 -> 9 CPU threads, normal priority, no GPU throttle (owner away 8-9 h)
- 2026-11-25 02:04:59 [rsn_final final] free RAM 1133 MB < 1500: page-cache drop requested
- 2026-11-25 06:15:34 [rsn_final final] free RAM 1471 MB < 1500: page-cache drop requested
- 2026-11-25 13:21:24 [claude] owner: stop final run now (~step 126), NO gate yet; next = short targeted fix top-up on work-friendly settings, then gate
- 2026-11-25 07:53:29 [rsn_final final] chunk 1 rc=3
