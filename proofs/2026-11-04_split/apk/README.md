# 2026-11-04 split: chat on the GPU (2B), reports on the NPU (4B)

Backend: `Code/smart-city-edge-agent/app/backend`. Not committed and not deployed. The board was not touched.

## Change

- New profile key `chat_url` (env `SCE_CHAT_URL`), for example `chat_url=http://127.0.0.1:8090`. It points at a llama.cpp llama-server that runs the 2B rsn_v3 model on the board GPU. A board-side script starts that server; the app only talks to it over HTTP.
- When `chat_url` is set, every chat model call goes to `POST <chat_url>/completion`. That covers tool-call steps, answers and the keep-warm pings (`chatLLM` -> `chatGPULLM`, in `chat_gpu.go`). The request body is:
  `{"prompt": <full prompt>, "n_predict": <max_new>, "temperature": 0, "top_k": 1, "cache_prompt": true, "stream": false}`
  The app reads `content` from the response. The prompt is the same text htpd gets: htpd's `prefix` field is only a cache hint, and the prompt already starts with it. No `stop` is sent, because htpd's chat decoding stops only at EOG, which is also llama-server's default.
- Fallback: if the server errors, times out (2 min) or cannot be reached, that call goes to htpd as before, and the failure is logged. The GPU is then skipped for 60 s.
- Chat queue: while the GPU is up, a question does not wait for an incident analysis on the NPU. The one-chat-at-a-time lock stays. An htpd fallback still waits for the NPU first (alerts first).
- Labels: chat answers carry `model` in the API: `qwen3.5-2b rsn_v3 (gpu)`, or `qwen3.5-4b chat (htpd)` when the call fell back. This field is only set when `chat_url` is set. The report label now follows `reasoner_model` only (4B -> `qwen3.5-4b (htpd)`). `chat_think=adaptive` now only switches the chat format (15-tool header and adaptive thinking); it no longer relabels reports as 2B.
- `chat_url` unset: htpd receives the same request as before (a unit test checks this). Reports, the validator and the agents are unchanged.
- The htpd_v9g process-name additions were dropped (v9g was cancelled). `htpdPids` already matches any `htpd_*` name.

## Tests (`go_test.txt`, `gotest.sh`)

- `go vet`: ok.
- New `chat_gpu_test.go`, run against a fake llama-server (httptest). It covers: the request body shape, fallback to htpd plus the backoff, chat_url unset giving the same htpd request as before, reports staying on the 4B (prompt, label and engine), and the GPU chat skipping the NPU queue. All pass, together with the existing label, htpd and queue tests.
- Full suite: one failure, `TestChatRouterBlind2Fixes` (Q37 "this week"). The cause is the calendar: its fixture places incidents relative to now, and "this week" counts from Monday. On Wednesday an extra incident, from Monday, falls inside the week. My change does not touch the router.

## APK

`build_split.sh` (same steps as `proofs/2026-11-03_fixes/build_r2fix.sh`) -> `SmartCityEdge.split.apk`, md5 `d956b9033728d2eef1b2f8ce184bdd3f` (`SmartCityEdge.split.apk.md5`, log `build.log`). The build also rewrote `app/device/edge-agent*` and `app/android/out/SmartCityEdge.apk`. The files in 2026-11-03_fixes were not touched.

Not tested on the board yet. Before relying on it, set `chat_url` with the GPU server running and check the chat in the app.
