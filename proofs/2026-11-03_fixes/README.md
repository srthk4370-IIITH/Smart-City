# 2026-11-03 fixes (before the 2026-11-04 evaluation)

Backend: `Code/smart-city-edge-agent/app/backend`. Not committed, not deployed. The board was not touched.

## What changed

1. **chatGuard time span** (`chat_guard.go`): `rank_readings`, `faulty_sensors` and `what_if` are now in `chatTimeTools`. A model call to any of them gets the question's period, the same as the incident tools. Comparisons are left alone, as before.
2. **pH direction** (new `phdir.go`, wired into `reasoner_v3.go` and `retrieval.go`). The text "turning acidic (pH below 6.5)" on a pH 9.6 incident (board INC-0660) did not come from the rules. It came from:
   - the retrieval preliminary: `rag_seed.json` has only low-pH water cases, so a high-pH match picked up their wording;
   - the reasoner, which was trained on the same wording.

   The fix reads `phDirection` from the incident's flagged pH window: above 8.5 means high, below 6.5 means low. `phFixText` then rewrites only the sentences that mention pH:
   - high pH: acidic becomes alkaline, below 6.5 becomes above 8.5, below 6.0 becomes above 9.0, "falling below" becomes "rising above", "below the critical limit" becomes "above …";
   - low pH: the reverse.

   This applies to the retrieved root cause and to the v3 report's title, root_cause, causal_chain, explanation, monitor_next, observations and checklist "why". Each rewrite is logged in `Repairs`.
3. **Model label** (`reasoner_v3.go` `reasonerModelLabel`, `chat.go`). The fixed "qwen3.5-4b (htpd)" label is now "qwen3.5-2b rsn_v3 (htpd)" when `chat_think=adaptive` or the reasoner GGUF name contains "2b". Otherwise it stays "qwen3.5-4b (htpd)". The chat label follows the same rule ("… chat (htpd)"). The web UI shows the backend's string, so it needed no change.
4. **Router fixes for blind2** (`chat_router_v25.go`, `chat_router_ops.go`, `chat_peak.go`, `chat.go`):
   - **Q17** ("what about the one with the fewest"): a grouped answer now records its grouping (`_group` in the tool args). A follow-up with a rank word (fewest/least/most/top) reuses that grouping. Ties are named. Follow-ups with "most serious" still go to the worst incident.
   - **Q30** ("water quality alerts"): "water quality" now means pH and TDS (new metric word `wq`, like `aq`). Before, it meant TDS only. Incidents on the water-quality node are now listed with no metric filter, so the pH criticals (INC-0660, INC-0549) appear.
   - **Q32** ("then should the AC be on there?" after an occupancy answer): the judge now also triggers on should/need/chahiye. In a sensors follow-up it also sees the earlier occupancy reading, so "AC on + room empty" is called out.
   - **Q37** ("dismissed this week, and how many approved?"): both counts are now given in one answer. v25 uses its own span, where "this week" means since Monday. The older route handles questions with no period: last 7 days, with a new `count_incidents` group_by "approval" used only by the router.

## Tests

- New file `chat_fixes_1103_test.go` with four tests: TestChatGuardTimeSpanMoreTools, TestPHDirectionWording, TestReasonerModelLabel, TestChatRouterBlind2Fixes.
- `go vet ./...` plus `go test ./...` (WSL Go SDK, `gotest.sh`): **ok edgeagent 71 s**, all pass (`go_test.txt`).
- Offline replay of the four deploy25 board sweeps through the current router (`replay_all.sh`, outputs in `replay/`). Blind2 before vs after (`replay_sweep9_blind2_before.jsonl` vs `replay_sweep9_blind2.jsonl`): only Q17, Q30 and Q37 changed, all for the better:
  - Q17 now gives "Fewest: SB (41)", which matches the truth.
  - Q30 now lists 62 water-quality incidents, with the pH criticals first.
  - Q32 cannot be shown in the replay: the replay fixture has no AC reading. The unit test covers it.

## APK

`SmartCityEdge.r2fix.apk` was built by `build_r2fix.sh`, using the same steps as build25.sh (app/build.sh, then android/build_apk.sh). Build log: `build.log`.

md5 `e0ccda2bf319ca3fa6c341fe16cf59b9` (also in `SmartCityEdge.r2fix.apk.md5`).

The build also rewrote `app/device/edge-agent`, `app/device/edge-agent-host` and `app/android/out/SmartCityEdge.apk`. The deploy25 and r2tools APKs were not touched.

## Not done / notes

- Not installed on the board and not swept live. Before relying on it, check it in the app.
- Q37: in the blind2 data, nothing happened after Monday 19 Oct, so the v25 answer is "No incident this week (since Monday) …, so none was dismissed or approved". The board's earlier answer was "44 dismissed", which used the last 7 days. Both are right for the window they state. v25 has always read "this week" as since Monday.
- The pH fix only rewrites wording. The model can still write other wrong text. The seed library still has no high-pH cases.
- `reason.go` still has an old example comment that mentions "qwen3.5-4b". It is a comment only.
