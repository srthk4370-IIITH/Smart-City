"""eval stub for the dry run of select_v2.sh (CPU, no GPU): --model --rows --out [--t1]. Right/wrong from a hash of (row id, model tag) vs a per-set accuracy table."""
import hashlib, json, os, sys
sys.path.insert(0, os.environ.get("AGT_DIR", "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt") + "/kaggle")
import rows as RW
a = dict(zip([x for x in sys.argv[1:]][0::2], sys.argv[2::2]))
model, rows, out = a["--model"], a["--rows"], a["--out"]
tag = [t for t in ("s0300", "s0100", "s0200") if t in model][0]
kind = [k for k, f in (("val", "val_sel"), ("syn", "syn_slice"), ("unk", "unseen100"), ("hard", "hard_val"), ("t2", "tool_t2"), ("t1", "tool_t1")) if f in rows][0]
ACC = {"val": {"s0300": .80, "s0100": .81, "s0200": .82}, "syn": {"s0300": .88, "s0100": .88, "s0200": .60}, "unk": {"s0300": .87, "s0100": .87, "s0200": .87},
       "hard": {"s0300": .55, "s0100": .70, "s0200": .75}, "t2": {"s0300": .30, "s0100": .70, "s0200": .80}, "t1": {"s0300": .0, "s0100": .8, "s0200": .85}}
thr = ACC[kind][tag]
with open(out, "a") as f:
    for r in map(RW.norm, RW.read_jsonl(rows)):
        h = int(hashlib.md5((r["id"] + "|" + tag).encode()).hexdigest()[:8], 16) / 16 ** 8
        ok = h < thr
        if kind == "t1":
            turn = r["raw"].get("turn")
            s = {"json": True, "call": None, "turn": turn, "call_ok": (ok if turn == "call" else None),
                 "direct_ok": (True if turn != "call" and tag != "s0300" or (turn != "call" and h < .97) else None if turn == "call" else False),
                 "status": None, "pattern": None, "cause": None, "dq": None}
            if turn != "call":
                s["direct_ok"] = h < 0.97
        else:
            g = dict(r["gold"])
            if not ok:
                g["status"] = "critical" if g.get("status") != "critical" else "normal"
            s = RW.score(r["gold"], json.dumps(g))
        s.update(id=r["id"], role=r["role"], family=r["family"])
        f.write(json.dumps(s) + "\n")
print("stub eval", kind, tag, flush=True)
