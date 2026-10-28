"""Off-label / garbage outputs on the device: where they occur (window length, batch), and whether whole batches break."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from a1_confusion import parse
SRC = Path(__file__).resolve().parents[2] / "2026-10-20_v2_post" / "device"
LAB = {'stable','spike','dip','gradual_increase','gradual_decrease','step_increase','step_decrease','exponential_increase','oscillation','throttling','flatline','erratic'}
rows = [json.loads(l) for l in open(SRC / "placement_v2" / "samples.jsonl", encoding="utf-8")]
bad = []; byn = Counter(); totn = Counter(); batches = defaultdict(list)
for r in rows:
    a = parse(r["text"]); ok = bool(a) and a.get("pattern") in LAB
    totn[r["n"]] += 1
    batches[(r["n"], r["batch_s"], r["board_c_before"])].append(ok)
    if not ok:
        byn[r["n"]] += 1; bad.append(r)
print("off-label/invalid by window n:", {n: f"{byn[n]}/{totn[n]}" for n in sorted(totn)})
print("stop reasons of bad rows:", Counter(r["stop"] for r in bad))
print("garbage (ctx-limit runaway) by n:", Counter(r["n"] for r in bad if r["stop"] == "ctx"))
bb = [v for v in batches.values() if not all(v)]
print("batches with >=1 bad:", len(bb), "of", len(batches), "; bad per affected batch:", Counter(sum(1 for x in v if not x) for v in bb))
print("board temp of bad rows:", sorted(r["board_c_before"] for r in bad))
print("board temp overall median:", sorted(r["board_c_before"] for r in rows)[len(rows)//2])
for name in ("host400", "test_all"):
    rs = [json.loads(l) for l in open(SRC / name / "samples.jsonl", encoding="utf-8")]
    st = Counter(r.get("stop") for r in rs)
    nj = sum(1 for r in rs if not r.get("json"))
    print(name, "stops", st, "json invalid", nj, "/", len(rs), "ctx-runaway by n:", Counter(r["n"] for r in rs if r.get("stop") == "ctx"))
