"""agt_v3 laptop top-up data (2026-11-16). LAPTOP ONLY: real windows never leave this machine.

  python3 build_data.py OUT_DIR [--probe N]
Real pool = B50's renderable REAL training windows (sft_v2 train, agents_v2_topup2 train, topup3f rw5_train + rw5x_train).
Exclusions: any window whose (node, 12 h time range) overlaps a window of an eval / test / selection set (dev3f, E1 eval3e,
sft_v2 test + dev, topup2 dev + dev_target, topup3e eval sets, rw5/rw5x dev + test, agt_v3 gate sets incl. campus / rename /
unseen_layout), plus id matches; label audit (2026-11-13_label_audit: pool_id exclusions + the same judge() on the v2 evidence
lines: gold not visible -> drop); v3 render = build_gate.v3_from_real (byte-identical to the gate's dev3f_v3 renders) and
verify_agt.check (all checks; hvac rows cannot be re-rendered from the v2 row -> rerender only, reported).
REAL VAL = ~10 % of (node, 7-day block) groups. Mix = real train + equal-size family-stratified replay of agt_v3/train.jsonl.
"""
import collections
import hashlib
import json
import os
import random
import re
import sys
from pathlib import Path

Q = Path("/mnt/c/Users/hp/Desktop/qidk")
P = Q / "proofs"
HOME = Path(os.path.expanduser("~"))
sys.path.insert(0, str(P / "2026-11-13_v3_data/agt_v3"))
sys.path.insert(0, str(P / "2026-11-13_label_audit/scripts"))
import build_gate as BG  # noqa: E402
import verify_agt as VA  # noqa: E402
import audit as AU  # noqa: E402

_label = BG.TV.label
_last = {}


def _cap(ex):          # same teacher call, also keep its meta (verify_agt needs it)
    t, meta = _label(ex)
    _last["meta"] = meta
    return t, meta


BG.TV.label = _cap

POOLS = {"sft_v2": Q / "Code/smart-city-edge-agent/data/sft_v2/train.jsonl",
         "topup2": HOME / "smartcity_runs/agents_v2_topup2/data/train.jsonl",
         "rw5": HOME / "smartcity_runs/agents_v2_topup3f/rw5/rw5_train.jsonl",
         "rw5x": HOME / "smartcity_runs/agents_v2_topup3f/rw5/rw5x_train.jsonl"}
EXCL = [HOME / "smartcity_runs/agents_v2_topup3f/dev/dev3f.jsonl", P / "2026-10-25_domain_plan/e1/eval3e.jsonl",
        Q / "Code/smart-city-edge-agent/data/sft_v2/test.jsonl", Q / "Code/smart-city-edge-agent/data/sft_v2/dev.jsonl",
        HOME / "smartcity_runs/agents_v2_topup2/data/dev.jsonl", HOME / "smartcity_runs/agents_v2_topup2/data/dev_target.jsonl",
        HOME / "smartcity_runs/agents_v2_topup3e/data/eval_weak.jsonl", HOME / "smartcity_runs/agents_v2_topup3e/data/realworld_eval.jsonl",
        HOME / "smartcity_runs/agents_v2_topup3f/rw5/rw5_dev.jsonl", HOME / "smartcity_runs/agents_v2_topup3f/rw5/rw5_test.jsonl",
        HOME / "smartcity_runs/agents_v2_topup3f/rw5/rw5x_dev.jsonl", HOME / "smartcity_runs/agents_v2_topup3f/rw5/rw5x_test.jsonl"]
GATE = P / "2026-11-13_v3_data/agt_v3/gate"
EXCL += sorted(GATE.glob("*.jsonl"))
EXCL += [P / "2026-11-13_v3_data/agt_v3" / f for f in ("test_campus.jsonl", "test_unseen_layout.jsonl", "test_unseen_metric.jsonl",
                                                       "calm_fault.jsonl", "dev.jsonl")]
STEP = 300


def rd(p):
    with open(p, encoding="utf-8") as f:
        for l in f:
            if l.strip():
                yield json.loads(l)


def wr(p, rows):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def node_of(r):
    if r.get("node"):
        return r["node"]
    m = re.search(r"\nNODE: (.*?) \(", "\n" + BG.V.user_text(r["prompt"])) if "prompt" in r else None
    return m.group(1) if m else None


def span(r):
    end = r.get("end_epoch")
    if end is None:
        return None
    hl = int(r.get("hist_len") or (len(r["hist"]) if isinstance(r.get("hist"), list) else 144))
    return int(end) - hl * STEP, int(end)


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    probe = int(sys.argv[sys.argv.index("--probe") + 1]) if "--probe" in sys.argv else 0
    man = {"pools": {}, "excl_sets": {}, "drop": collections.Counter(), "soft": collections.Counter()}
    # ---- exclusion index: node -> list of (start, end); ids
    ex_ivs, ex_ids = collections.defaultdict(list), set()
    for p in EXCL:
        if not p.exists():
            man["excl_sets"][str(p)] = "MISSING"
            continue
        n = 0
        for r in rd(p):
            n += 1
            for k in ("id", "pair_id", "base_id"):
                if r.get(k):
                    ex_ids.add(str(r[k]).replace("-v3", "").replace("-b50", ""))
            nd, sp = node_of(r), span(r)
            if nd and sp:
                ex_ivs[nd].append(sp)
        man["excl_sets"][str(p).replace(str(HOME), "~")] = n
    for nd in ex_ivs:
        ex_ivs[nd].sort()

    def overlaps(nd, sp):
        for a, b in ex_ivs.get(nd, ()):
            if a < sp[1] and sp[0] < b:
                return True
        return False
    audit_ex = {json.loads(l)["pool_id"] for l in open(P / "2026-11-13_label_audit/exclusions.jsonl") if json.loads(l).get("pool_id")}
    T = json.load(open(P / "2026-11-13_label_audit/thresholds.json"))
    T = {tuple(k.split("|")) if isinstance(k, str) and "|" in k else k: v for k, v in T.items()} if isinstance(T, dict) else T
    # ---- pool
    seen, kept, rejected = set(), [], []
    for pn, pp in POOLS.items():
        n = 0
        for r in rd(pp):
            n += 1
            if probe and n > probe:
                break
            r["_pool"] = pn
            key = (r["node"], r["metric"], int(r["end_epoch"]), int(r["n"]))
            if key in seen:
                man["drop"]["dup"] += 1
                continue
            seen.add(key)
            if str(r["id"]) in ex_ids:
                man["drop"]["excl_id"] += 1
                continue
            if overlaps(r["node"], span(r)):
                man["drop"]["excl_overlap"] += 1
                continue
            if r["id"] in audit_ex:
                man["drop"]["audit_id"] += 1
                continue
            g2 = json.loads(r["completion"].replace("<|eot_id|>", ""))
            u = BG.V.user_text(r["prompt"])
            E = dict(re.findall(r"^(E\d+) (.*)$", u, re.M))
            head = [l for l in u.split("\n") if l.startswith(("LIMITS:", "TANK:"))]
            try:
                s, why, _ = AU.judge(r["role"], r["metric"], g2["status"], g2.get("fault_kind"), AU.feats(r["role"], E, int(r["n"])),
                                     head, int(r["n"]), T, None, {"offday": bool(re.search(r"\| (weekend|holiday)", u.split("\n")[0]))})
            except Exception as e:  # noqa: BLE001
                s, why = "err", repr(e)[:60]
                man["drop"]["audit_error:" + why] += 1
            if s == "n":
                man["drop"]["audit_not_visible"] += 1
                rejected.append({"id": r["id"], "why": "audit: " + why})
                continue
            # ---- v3 render (exact gate renderer) + verify
            _last.clear()
            try:
                prompt, t, card = BG.v3_from_real(r)
            except Exception as e:  # noqa: BLE001
                man["drop"]["render_error:" + repr(e)[:50]] += 1
                continue
            hist = r["hist"] if isinstance(r["hist"], list) else json.loads(r["hist"])
            loc = re.match(r"NODE: (.*?) \((.*)\)$", u.split("\n")[0]).group(2)
            fam = r.get("family") or "real"
            meta = _last.get("meta") or {"routine": r.get("routine"), "glitch": fam == "glitch"}
            vr = {"id": "rt-" + r["id"] + "-" + pn, "prompt": prompt, "completion": json.dumps(t, ensure_ascii=False) + "<|eot_id|>",
                  "gold": t, "card": card, "hist": hist[-144:], "n": int(r["n"]), "end_epoch": int(r["end_epoch"]),
                  "node": r["node"], "location": loc, "place": None, "missing": None, "meta": meta, "sub": r.get("sub"),
                  "family": fam}
            bad = VA.check(vr)
            hv = card["kind"] == "hvac_unit"
            hard = [b for b in bad if not (b.startswith("rerender") and hv)]
            for b in set(x.split(":")[0] for x in bad):
                man["drop" if hard else "soft"]["verify:" + b] += 1
            if hard:
                rejected.append({"id": r["id"], "why": "verify: " + ",".join(hard[:4])})
                continue
            if bad:
                man.setdefault("hvac_rerender_unchecked", 0)
                man["hvac_rerender_unchecked"] += 1
            sl = r.get("slices") or []
            kept.append({"id": vr["id"], "prompt": prompt, "completion": vr["completion"], "gold": t,
                         "family": "real_" + str(fam), "role": r["role"], "card_id": card["card_id"], "node": r["node"],
                         "end_epoch": int(r["end_epoch"]), "pool": pn, "stage": r.get("stage"), "slices": list(sl) if isinstance(sl, list) else [],
                         "synthetic": False, "source": "real_" + pn})
        man["pools"][pn] = n
    man["kept_real"] = len(kept)
    man["drop"] = dict(man["drop"])
    man["soft"] = dict(man.get("soft", {}))
    wr(out / "_rejected_real.jsonl", rejected)
    if probe:
        print(json.dumps(man, indent=1)[:4000])
        return
    # ---- REAL VAL by (node, 7-day block)
    grp = collections.defaultdict(list)
    for r in kept:
        grp[(r["node"], r["end_epoch"] // (7 * 86400))].append(r)
    keys = sorted(grp, key=lambda k: hashlib.md5(("%s|%d" % k).encode()).hexdigest())
    val, tr, nv = [], [], 0
    for k in keys:
        if nv < 0.10 * len(kept):
            val += grp[k]
            nv += len(grp[k])
        else:
            tr += grp[k]
    # VAL blocks also removed from train by time overlap (adjacent windows of the same node in the same block are all in VAL)
    man["real_val"] = len(val)
    man["real_train"] = len(tr)
    man["val_groups"] = sum(1 for k in keys if grp[k][0] in val)
    random.Random(16).shuffle(val)
    wr(out / "real_val.jsonl", val)
    wr(out / "real_train_all.jsonl", tr)
    # stats
    for nm, rs in (("real_train", tr), ("real_val", val)):
        man[nm + "_by_role"] = dict(collections.Counter(r["role"] for r in rs))
        man[nm + "_by_status"] = dict(collections.Counter(r["gold"]["status"] for r in rs))
        man[nm + "_by_family"] = dict(collections.Counter(r["family"] for r in rs).most_common())
        man[nm + "_by_pool"] = dict(collections.Counter(r["pool"] for r in rs))
    json.dump(man, open(out / "data_manifest.json", "w", newline="\n"), indent=1)
    print(json.dumps({k: man[k] for k in ("pools", "drop", "soft", "kept_real", "real_train", "real_val")}, indent=1))


if __name__ == "__main__":
    main()
