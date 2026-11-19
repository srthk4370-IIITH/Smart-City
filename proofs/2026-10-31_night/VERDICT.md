# 2026-10-31 night steward: soak + chat drafts (deploy21)

## Board
- deploy20 (htpd_v9e agent draft index) went live at 03:50 IST.
- **deploy21 went live at about 07:40 IST:** htpd_v9f, verified chat drafts plus a chat corpus (HANDBOOK 2.66).
  - Checks: chaos 2 rc=0; fastcheck x2 passed (fast path 5.7 s and 5.6 s, AI update 26.7 s and 37.1 s; deploy20 gave 21.7 s and 32.5 s on the same code path, so the difference is run-to-run noise); chat 4/4.
  - Rollback: proofs/2026-10-29_latency/deploy21/known_good (= deploy20).
- The board was never rebooted. The NPU library was not changed. There was one NPU client at a time, and the soak was paused during the lab window and the deploy.

## Chat drafts (htpd_v9f)
- **Offline sim** (chat_sim.py, the board's chats.json, 34 model answers, held out by question): prompt-only drafts gave -9 to -13% modelled time. That is why deploy15 lost. Prompt + chat-corpus drafts at match >= 4 gave -46%.
- **Lab cl1** (chatlab/, 10 real chat rounds, corpus = outputs of other questions only):
  - Mean request time: base 2864 ms, v9f 2383 ms (-17%), base2 2845 ms.
  - Text identical to base: v9f 10/10, base2 10/10. Lossless on this set.
  - Per request: c9 3323 -> 1088 ms, c5 2600 -> 1685 ms, c3 3360 -> 2747 ms. Short answers are unchanged.
- **Live:** the first model chat drafted 16.7% (prompt only, corpus 0). The gain grows as chat_corpus.jsonl grows with real use.

## Fast-path "44 s" in the soak (owner question)
- The CO2 incident and a direct pH test (diag_fast.py) both opened the fast incident in about 2.8 s.
- PM2.5, pH and power-factor incidents in the soak opened after about 44 s, at the same sim time each run.
- **Cause:** a held /api/ingest value stops producing readings after 15 min of wall time (apiHoldSec, dataquality.go). Between soak cycles the sensors went silent for 17 min. When the test resumed them, the 4 h window had a gap, and the gap rules (at most 3 missing of 48) hold the event gate until about 40 new readings have arrived.
- This is real app behaviour, not NPU time: a critical value after a silent period waits for window coverage.
  - In real time that is about 40 readings x 5 min.
  - **Open issue for the owner:** let the critical fast path bypass the window-coverage gate. This was not changed tonight because it changes alert semantics.
- The soak's 90-94 C temperatures are read just after the test, while the NPU has just run. Each test starts only below 60 C, and the pre-test gate held on every cycle.

## Soak
See soak.csv / soak.log; the summary is in the steward's report.
- **16 tests, 16 passed** (03:48-08:54 IST): incident 6/6, chat 5/5, normal-readings 5/5 with no false incident.
- No crashes (logcat crash buffer 0 lines). htpd and edge-agent were alive on every cycle. MemAvailable stayed at or above 4218 MB.
- **Incidents:**
  - Fast path: 2.7 s on a sensor that was still being fed; 44-46 s after the 17-min silence (gap gate, see above).
  - AI update: 22.7 s, or 71-73 s after the silence. In both cases it comes 27 s after the fast incident.
- **Chat:** routed answers 0.2 s; model answers 10.0, 13.2 and 11.1 s, including the reasoner swap-in.
- **Anomaly:** INC-0564 (outdoor temperature 45 C, weather only). The reasoner report was rejected because "a critical report must start with an inspect_* or request_facility_review action", so the deterministic report was used instead. The incident was still valid and done. The validator may need a weather-only rule, or the reasoner needs training for this case. Owner to decide.
