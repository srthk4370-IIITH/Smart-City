"""r2 incident training file + incident TEST file (stdlib python3; CPU).
train = kaggle/build/r2x/data/incidents3_train.jsonl (round-1 generator seed 47, 30,000 rows + 192 heat_r2 rows)
        + data/targeted/train.jsonl + data/heat_r2b/train.jsonl
test  = data/test/test_incidents_gen.jsonl (held-out split, families balanced)  slice gen_heldout
        + data/targeted/test.jsonl (contrastive app-story classes; ~35 % unseen building codes)  slice targeted[_novel]
        + data/heat_r2b/dev.jsonl + rsn_v3 data/heat_r2/dev.jsonl                                slice heat
Leakage: a train row is dropped when its user prompt occurs in RWH, RWH-2, round-1 dev, the gate's dev60 or any test row;
duplicates inside train are dropped. Every row (train and test) is re-checked with round-1 verify.py; the Go gate is run
afterwards on the written files (go_gate.sh) and failing rows are removed by --drop-gate.
  python3 build_inc_r2.py --out DIR            then  go_gate.sh ...  then  python3 build_inc_r2.py --out DIR --drop-gate G1 G2"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
V3 = os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3")
R1 = os.path.join(QIDK, "proofs", "2026-10-25_reasoner_final")
R2 = os.path.join(QIDK, "proofs", "2026-11-02_2b_r2")
sys.path.insert(0, os.path.join(R1, "pipeline"))
import verify as V  # noqa: E402

NOVEL = ("QX", "ZR", "EL", "WD", "FY", "UV")


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []


def write(p, rows):
    with open(p + ".part", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(p + ".part", p)


def u(r):
    return r["messages"][1]["content"]


def sev_label(r):
    o = json.loads(r["messages"][-1]["content"])
    return o["severity"], o["label"], o["checklist"][0]["action"]


def comp(rows):
    c = collections.Counter()
    for r in rows:
        s, l, a = sev_label(r)
        c["sev:" + s] += 1
        c["label:" + l] += 1
        c["first:" + a] += 1
        m = u(r).split("(mode ", 1)[1].split(")", 1)[0]
        c["mode:" + m] += 1
        for role in {ln.rsplit("(", 1)[1].rstrip(")") for ln in u(r).split("\n") if "[FLAGGED]" in ln and ln.endswith(")")}:
            c["flagged_role:" + role] += 1
        c["+tool" if any(m_.get("tool_calls") for m_ in r["messages"]) else "no_tool"] += 1
        c["outdoor_context"] += " | outdoor " in u(r).split("\n", 1)[0]
    return dict(sorted(c.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--drop-gate", nargs="*", default=[], help="go_gate.sh result jsonl files: rows with pass=false are removed")
    a = ap.parse_args()
    D = os.path.join(R2, "data")
    os.makedirs(a.out, exist_ok=True)
    pt, ptest = os.path.join(a.out, "incidents_train.jsonl"), os.path.join(a.out, "incidents_test_r2.jsonl")
    if a.drop_gate:
        bad = set()
        for g in a.drop_gate:
            bad |= {json.loads(l)["id"] for l in open(g) if not json.loads(l)["pass"]}
        tr, te = load(pt), load(ptest)
        tr2, te2 = [r for r in tr if r["id"] not in bad], [r for r in te if r["id"] not in bad]
        write(pt, tr2)
        write(ptest, te2)
        m = json.load(open(os.path.join(a.out, "incidents_manifest.json")))
        m["go_gate_dropped"] = {"train": len(tr) - len(tr2), "test": len(te) - len(te2)}
        m["rows"] = {"train": len(tr2), "test": len(te2)}
        json.dump(m, open(os.path.join(a.out, "incidents_manifest.json"), "w"), indent=1)
        print("go gate: dropped train %d, test %d -> train %d, test %d" % (len(tr) - len(tr2), len(te) - len(te2), len(tr2), len(te2)))
        return
    tests = []
    for p, sl in ((os.path.join(D, "test", "test_incidents_gen.jsonl"), "gen_heldout"), (os.path.join(D, "targeted", "test.jsonl"), "targeted"),
                  (os.path.join(D, "heat_r2b", "dev.jsonl"), "heat"), (os.path.join(V3, "data", "heat_r2", "dev.jsonl"), "heat")):
        for r in load(p):
            s = sl
            if sl == "targeted" and any(" %s building" % b in u(r) for b in NOVEL):
                s = "targeted_novel_names"
            r["slice"] = s
            tests.append(r)
    held = set()
    for p in [os.path.join(R1, "data", n) for n in ("incidents_rwh.jsonl", "incidents_rwh.ok.jsonl", "incidents_dev.jsonl", "incidents_dev.ok.jsonl")] + \
             [os.path.join(V3, "kaggle", "build", "r1", "heldout", "incidents_rwh2.jsonl"), os.path.join(V3, "kaggle", "build", "r2x", "data", "incidents_dev60.jsonl")]:
        held |= {u(r) for r in load(p)}
    st = collections.Counter()
    tseen, test = set(), []
    for r in tests:
        if u(r) in held or u(r) in tseen:
            st["test_drop_heldout_or_dup"] += 1
            continue
        if V.check_incident(r):
            st["test_drop_verify"] += 1
            continue
        tseen.add(u(r))
        test.append(r)
    train, seen = [], set()
    srcs = ((os.path.join(V3, "kaggle", "build", "r2x", "data", "incidents3_train.jsonl"), "r2x_generator"),
            (os.path.join(D, "targeted", "train.jsonl"), "targeted"), (os.path.join(D, "heat_r2b", "train.jsonl"), "heat_r2b"))
    for p, src in srcs:
        for r in load(p):
            if u(r) in held or u(r) in tseen:
                st["train_drop_leak:" + src] += 1
                continue
            if u(r) in seen:
                st["train_drop_dup:" + src] += 1
                continue
            if V.check_incident(dict(r, meta=r.get("meta", {}))):
                st["train_drop_verify:" + src] += 1
                continue
            seen.add(u(r))
            r["r2_src"] = src if not r["family"].startswith("heat_r2:") or src != "r2x_generator" else "heat_r2"
            train.append(r)
            st["train:" + r["r2_src"]] += 1
    import random
    random.Random(4711).shuffle(train)
    write(pt, train)
    write(ptest, test)
    m = {"rows": {"train": len(train), "test": len(test)}, "stats": dict(st),
         "train_composition": comp(train), "test_composition": comp(test),
         "test_slices": dict(collections.Counter(r["slice"] for r in test)),
         "test_slice_severity": {s: dict(collections.Counter(sev_label(r)[0] for r in test if r["slice"] == s)) for s in
                                 sorted({r["slice"] for r in test})},
         "train_families": dict(collections.Counter(r["family"].split(":")[0].split("+")[0] for r in train).most_common())}
    json.dump(m, open(os.path.join(a.out, "incidents_manifest.json"), "w"), indent=1)
    print("incidents r2: train %d, test %d; %s" % (len(train), len(test), dict(st)))


if __name__ == "__main__":
    main()
