import json, os, sys
V, M = sys.argv[1], sys.argv[2]
g = json.load(open(f"{V}/gates.json")) if os.path.exists(f"{V}/gates.json") else {}
res = open(f"{V}/result").read().strip() if os.path.exists(f"{V}/result") else "n/a"
cause = open(f"{V}/CAUSE.md").read() if os.path.exists(f"{V}/CAUSE.md") else "(see v8x3/host_* logs)"
bs = open(f"{V}/board_state.txt").read() if os.path.exists(f"{V}/board_state.txt") else ""
md = f"""# rsn_v2 retry with htpd_v8x3 (2026-10-29)

**Result:** {res}

## Cause and fix
{cause}

## Board numbers (split-3 + OPPOLL, htpd_v8x3; raw: `v8x3/raw_par`, `raw_v2`, `raw_cons`)
| check | value | gate |
|---|---|---|
| v8x3 + rsn_v1 parse (q10-q14) | {g.get('par_parse')}/5 | 5/5 |
| v8x3 + rsn_v1 same severity/label as v8x2 | {g.get('par_same')}/5 | >= 4/5 |
| reasoner mean s (v8x3 / v8x2, q10-q14) | {g.get('par_ms')} / {g.get('v1_ms')} | - |
| rsn_v2 parse (q10-q19) | {g.get('v2_parse')}/10, stops {g.get('v2_stops')}, q11 stop {g.get('v2_q11')} | 10/10 |
| severity vs gold v2 / v1 | {g.get('v2_sev_gold')} / {g.get('v1_sev_gold')} | v2 >= v1 |
| label vs gold v2 / v1 | {g.get('v2_lab_gold')} / {g.get('v1_lab_gold')} | v2 >= v1 |
| rsn_v2 mean s (q10-q19) | {g.get('v2_ms')} | - |
| rsn_v2 severity consistency (q11-q13 x 3) | {g.get('cons')} | >= 8/9 |
| split-6 at 6x3200 ctx, rsn_v1 q10-q14: parse / same sev+label as sp3 / mean s | {g.get('sp6_parse')}/5 / {g.get('sp6_same_as_sp3x')}/5 / {g.get('sp6_ms')} (sp3 {g.get('par_ms')}) | numbers only, no deploy |

Board state after the run:
```
{bs}
```
Rollback: restore `v8x3/known_good/htpd_profile` (and reinstall `known_good/app.apk`) with the app stopped; log `rsn_v2_retry.log`.
"""
open(f"{M}/RSN_V2_RETRY.md", "w").write(md)
p = "/mnt/c/Users/hp/Desktop/qidk/HANDBOOK.md"; s = open(p, encoding="utf-8").read()
if "## 2.58 " not in s:
    e = f"""## 2.58 rsn_v2 retry with htpd_v8x3 (2026-10-29, proofs/2026-10-28_master/RSN_V2_RETRY.md)

- Result: {res}
- htpd_v8x3: bounded constrained pick (top-64, then top-1024, then the forced token, with a full scan only as the last resort); 150 s wall-clock guard per reason request (stop "timeout" -> deterministic report); slow-pick counters in the log.
- Gates: parity {g.get('par_same')}/5, rsn_v2 parse {g.get('v2_parse')}/10, sev gold {g.get('v2_sev_gold')} vs {g.get('v1_sev_gold')}, label gold {g.get('v2_lab_gold')} vs {g.get('v1_lab_gold')}, consistency {g.get('cons')}.

"""
    s = s.replace("## 3. If something goes wrong", e + "## 3. If something goes wrong", 1); open(p, "w", encoding="utf-8").write(s)
