"""Device per-row confusions for weak slices of host400 + test_all (water unseen, power)."""
import json
from collections import Counter, defaultdict
from pathlib import Path
P = Path(__file__).resolve().parents[2] / "2026-10-20_v2_post" / "device"
rows = {}
for f in ("host400", "test_all"):
    for r in map(json.loads, open(P / f / "samples.jsonl", encoding="utf-8")):
        rows.setdefault(r["id"], r)
rows = list(rows.values())
out = [f"rows (host400 U test_all, dedup): {len(rows)}"]
for role in ("water", "power", "air_quality"):
    for seen in ("seen", "unseen", "unseen_sepoct"):
        sel = [r for r in rows if r["role"] == role and r["seen"] == seen]
        if not sel: continue
        a = sum(bool(r["pattern"]) for r in sel) / len(sel); s = sum(bool(r["status"]) for r in sel) / len(sel)
        cm = Counter((r["gold_pattern"], (r.get("pred") or {}).get("pattern")) for r in sel if not r["pattern"])
        out.append(f"\n{role}/{seen}: n={len(sel)} pattern {a:.2f} status {s:.2f}; top pattern errors (gold, pred): {cm.most_common(8)}")
        cs = Counter((r["gold_status"], (r.get("pred") or {}).get("status")) for r in sel if not r["status"])
        out.append(f"   status errors (gold, pred): {cs.most_common(6)}")
        fam = defaultdict(list)
        for r in sel: fam[r["family"]].append(bool(r["pattern"]))
        out.append("   by family: " + ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in sorted(fam.items())))
        nodes = Counter(r["id"] for r in sel)
open(Path(__file__).parent / "weak_roles.md", "w", encoding="utf-8").write("# Weak slices on the device (host400 + partial test split)\n\n" + "\n".join(out))
print("\n".join(out))
