# Overnight plan, 2026-10-29 (evaluation at 12:00 IST)

The live status is regenerated every 10 min in `OVERNIGHT_STATUS.md`, by `overnight_watch.sh` (detached as `watch`).

## Already decided (board-measured)
- **Agents: B50.** T30 failed gate2 head-to-head against it (HANDBOOK 2.54b). P3b blends all failed.
- **Reasoner: rsn_v1 for now.** On the board, rsn_v2 stalled htpd at 100% CPU on prompt q11. A retry with an htpd fix is below.
- **Split: 3 for now.** sp4/sp6 never really ran (their request files lacked a trailing newline). The fixed rerun is below.
- **App: fast-path build** (edge-agent c97afdeb). Early AI is off; the gate study was not run (no laptop evals).

## Chain (each step is a standalone job, gated by BOARD_LOCK and step markers; times are IST and approximate)
| # | job | when | what | if it fails |
|---|---|---|---|---|
| 1 | `final` F6/F7 | 23:49 → ~00:30 | app check: chaos2 6 scenarios + fastcheck (critical fast path, then the AI on the same incident); writes FINAL_STATUS.md + HANDBOOK 2.56 | auto-rollback to the 10-28 known-good + a 2-scenario re-check |
| 2 | `split_post` | ~00:30 → ~01:45 | sp6x/sp4x with rsn_v1 vs the sp3 run (30 RWH); switch only if the fastest passing split beats sp3 on gold, then a 3-incident app check | back to split 3 |
| 3 | `rag_deploy` | ~01:45 → ~02:45 | retrieval preliminary APK (ebd08e13 / 4baf7f79), seeds folded in if ready by 09:30; app check (preliminary within 2 s, then the AI on the same incident) | `rag_rollback.sh`; never starts after 10:30 |
| 4 | `rag_seed` (laptop GPU) | 23:46 → 08:45 | rsn_v1 writes ≤1,000 train-split reference reports for the retrieval library | deploy without seeds |
| 5 | rsn_v2 retry (speed agent) | after #3, by 09:30 | reproduce the q11 stall on the host, fix the htpd slow path + add a 150 s guard (htpd_v8x3), board parity with v1, then rsn_v2 30 RWH + 6×5 consistency | keep rsn_v1 (v8x3 ships only with parity and a passing app check) |
| 6 | website (agent) | drafts now; final by 11:15 | journey + today pages from the files above; wrangler deploy (password <site password>); commit + push | the first deploy stays up |

## Safety
- One NPU client at a time. Every request starts at ≤60 °C. Never reboot. Big files go .part + md5 + mv.
- The watchdog SIGTERMs a stalled htpd (≥90% CPU for 10 min with no log growth). It does nothing else.
- Board stop fix: `pkill -f "[b]in/htpd"` sent through adb killed its own shell. All active scripts now use pidof + kill -TERM.

## Rollback commands
- Everything back to the 10-28 known-good: `bash proofs/2026-10-28_master/final_rollback.sh`
- Retrieval APK only: `bash proofs/2026-10-28_master/rag_rollback.sh`

## Rate-limit independence (owner, 00:15 IST)
Every remaining step ends up as a standalone script, so the night completes even if no Claude session is running:
- **rsn_v2 retry:** one detached script carries all its decision rules and cutoffs, and writes RSN_V2_RETRY.md + HANDBOOK 2.58 itself.
- **Website:** `website_final` (detached) builds with the status files injected at build time, runs the wrangler deploy (password <site password>) at about 10:50 IST, then commits and pushes.
- **Docs:** `ppt.md` and `teach.md` are rewritten now. `finalize_docs` (detached) fills the `<<filled from …>>` markers from the status files at about 10:40 IST, then commits and pushes.
- **Watchdog:** `watch` rewrites OVERNIGHT_STATUS.md every 10 min until 12:00 IST.
