"""eval stub (CPU, no GPU): --model --rows --out [--limit]. Right/wrong decided by a hash of (row id, model tag) against a per-set
accuracy table, so the paired tests in select_k.py have something to find. Same sample format as hosteval.py."""
import hashlib, json, os, sys
sys.path.insert(0, os.environ.get("AGT_DIR", "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt") + "/kaggle")
import rows as RW
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
model, rows, out = a["--model"], a["--rows"], a["--out"]
tag = "s1750" if "snap_1750" in model else [t for t in ("s0050", "s0100", "s0150") if t in model][0]
kind = "val" if "val_sel" in rows else "syn" if "syn_slice" in rows else "unk"
ACC = {"val": {"s1750": .67, "s0050": .72, "s0100": .75, "s0150": .74}, "syn": {"s1750": .88, "s0050": .88, "s0100": .66, "s0150": .88},
       "unk": {"s1750": .85, "s0050": .85, "s0100": .6, "s0150": .86}}
thr = ACC[kind][tag]
with open(out, "a") as f:
    for r in map(RW.norm, RW.read_jsonl(rows)):
        h = int(hashlib.md5((r["id"] + "|" + ("base" if tag == "s1750" else "c")).encode()).hexdigest()[:8], 16) / 16 ** 8
        h2 = int(hashlib.md5((r["id"] + "|" + tag).encode()).hexdigest()[:8], 16) / 16 ** 8
        g = dict(r["gold"])
        ok = (h if tag == "s1750" else (0.5 * h + 0.5 * h2)) < thr
        if not ok:
            g["status"] = "critical" if g.get("status") != "critical" else "normal"
        s = RW.score(r["gold"], json.dumps(g))
        s.update(id=r["id"], text=json.dumps(g), role=r["role"], family=r["family"])
        f.write(json.dumps(s) + "\n")
print("stub eval", kind, tag, flush=True)
