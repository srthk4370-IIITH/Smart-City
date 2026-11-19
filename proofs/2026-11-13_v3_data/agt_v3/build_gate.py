"""Gate sets for the agt_v3 vs B50 gate (proofs/2026-11-13_v3_train/agt/gate_config.json). LAPTOP ONLY (dev3f / E1 are
real windows; source fields say so, so check_data.py refuses them for upload).

  python3 build_gate.py DATA_DIR
Inputs: DATA_DIR/agt_v3/{dev,test_unseen_layout,test_campus,test_unseen_metric,calm_fault}.jsonl (verified),
        ~/smartcity_runs/agents_v2_topup3f/dev/dev3f.jsonl, proofs/2026-10-25_domain_plan/e1/eval3e.jsonl
Outputs (DATA_DIR/agt_v3/gate/): dev3f_v3/b50, e1_v3/b50, rename_v3, test_unseen_metric, test_unseen_layout(+_b50),
        test_campus_v3(+_b50), calm_fault_v3, gate_manifest.json.
v3 renders of the real windows reuse the app-identical evidence block (WINDOW line onward) of the v2 prompt (byte
parity shown by core/evidence.verify_fixtures) under a CARD + NODE header; v3 gold = teacher_v3 on the same window with
the v2 gold pattern as the shape (onset / event_active kept). B50 rows = today's v2 prompt + v2-key gold.
"""
from __future__ import annotations

import copy
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "core"))
sys.path.insert(0, str(HERE))
import evidence as EV  # noqa: E402
import cards as CD  # noqa: E402
import teacher_v3 as TV  # noqa: E402
import features as F  # noqa: E402
import features_v2 as V  # noqa: E402
import hvac as HV  # noqa: E402
import hvac_adapter as HVA  # noqa: E402
HVA.register()   # 2026-11-13 fix: B50 hvac schema hint needs the hvac role registered (KeyError 'hvac')

EC = CD.existing_cards()
ROOT = HERE.parents[2]
NODE_LIMITS = json.loads((ROOT / "Code/smart-city-edge-agent/app/device/data/node_limits_v2.json").read_text())
DEV3F = Path(os.path.expanduser("~/smartcity_runs/agents_v2_topup3f/dev/dev3f.jsonl"))
E1 = ROOT / "proofs/2026-10-25_domain_plan/e1/eval3e.jsonl"
SAFETY = ("leak_night", "leak_day_norefill", "ac_not_cooling_14h", "ac_fast_stepped")
V2KEYS = ("pattern", "status", "observations", "likely_cause", "confidence", "event_active", "onset", "fault_kind", "action")
HV_SEV = {"stable": "inside the comfort band: normal (card)", "normal_cycling": "normal thermostat cycling (card)",
          "pull_down": "normal pull-down after start (card)", "setback_drift": "setback drift with AC off is normal (card cycle)"}


def rd(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def wr(p, rows):
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def b(x):
    return x if isinstance(x, bool) else str(x) == "True"


def v2_user(prompt):
    return V.user_text(prompt)


def card_for(role, metric, node, location):
    c = copy.deepcopy(EC[CD.metric_to_card(role, metric, node, location)])
    if c["card_id"] == "tank_level":
        tl = NODE_LIMITS.get(node)
        c["tank"] = {k: tl[k] for k in ("high", "overflow", "fill_min")} if tl else None
    return c


def v3_from_real(r):
    """v3 prompt + gold for one v2 row (real window)."""
    role, metric, node = r["role"], r["metric"], r["node"]
    u = v2_user(r["prompt"])
    lines = u.split("\n")
    m = re.match(r"NODE: (.*?) \((.*)\)$", lines[0])
    location = m.group(2)
    card = card_for(role, metric, node, location)
    wi = next(i for i, l in enumerate(lines) if l.startswith("WINDOW: "))
    n = int(r["n"])
    user = "\n".join([CD.render_full(card), f"NODE: {node} ({location})"] + lines[wi:])
    prompt = F.llama3_prompt(EV.agent_system(card, n), user)
    g2 = json.loads(r["completion"].replace("<|eot_id|>", ""))
    hist = r["hist"] if isinstance(r["hist"], list) else json.loads(r["hist"])
    end = int(r["end_epoch"])
    if card["kind"] == "hvac_unit":
        st = g2["status"]
        fk = g2.get("fault_kind")
        if st == "sensor_fault":
            sev = f"{g2['pattern'].replace('_', ' ')}: data fault, not an event (card faults)"
            dq = {"verdict": "fault", "why": g2["pattern"].replace("_", " "), "src": ["E7"]}
        else:
            sev = HV_SEV.get(g2["pattern"], f"{g2['pattern'].replace('_', ' ')}: {st} (card)")
            dq = {"verdict": "ok", "why": "plausible room temperature, readings complete", "src": ["E8"]}
        t = {"pattern": g2["pattern"], "status": st, "data_quality": dq, "severity_reason": sev,
             "evidence": TV.ids_in(sev, *g2["observations"], " ".join(dq["src"]))}
        for k in ("observations", "likely_cause", "confidence", "event_active", "onset"):
            t[k] = g2[k]
        if fk:
            t["fault_kind"] = fk
        t["action"] = g2["action"]
        return prompt, TV.order(t), card
    xs = hist[-n:]
    if card["kind"] == "binary_state":
        _, info = V.history_items("occupancy", "occ", hist[-144:], end, 0, "0/1")
        t, _ = TV.label({"card": card, "xs": xs, "end": end, "n": n, "info": info, "rng": random.Random(r["id"]), "family": "real"})
        return prompt, t, card
    key = CD.metric_key(card)
    st = F.compute_stats(xs, card["decimals"])
    _, info = V.history_items(key[0], key[1], hist[-144:], end, card["decimals"], card["unit"])
    fam = r.get("family", "event")
    fam = {"real_longrange": "old_shift" if any(f["kind"] == "level_shift" for f in info.get("long_view") or []) else "long_drift"}.get(fam, fam)
    hint = {"calib_drift": "drift", "noise_increase": "noise"}.get(r.get("sub"), r.get("sub")) if fam == "fault" else None
    ex = {"card": card, "pattern": g2["pattern"], "family": fam, "size": None, "xs": xs, "hist": hist, "n": n, "end": end,
          "st": st, "info": info, "rng": random.Random(r["id"]), "zero": fam == "zero_idle" or (g2["pattern"] == "flatline" and g2["status"] == "normal"),
          "fault_hint": hint, "active": b(r.get("event_active")), "onset_time": g2.get("onset")}
    t, meta = TV.label(ex)
    t["onset"], t["event_active"] = g2["onset"], g2["event_active"]
    return prompt, t, card


def b50_from_v3(r):
    """today's v2 prompt of a synthetic v3 row (existing, non-jittered cards, no GAPS line) + v2-key gold."""
    card = r["card"]
    if card["rules"].get("synthetic") or card["rules"].get("jittered") or "\nGAPS: " in r["prompt"]:
        return None
    role, metric = card["rules"]["legacy_key"]
    n, end, hist = r["n"], r["end_epoch"], r["hist"]
    if role == "hvac":
        c = dict(r["hvac_ctx"], end=end, node=r["node"])
        for k in ("sp", "on", "alarm", "missing", "thermo", "occ"):
            if c.get(k) is not None:
                c[k] = c[k][-n:]
        user, st, ev = HV.user_prompt(r["node"], r["location"], hist[-n:], c)
        hv, info = V.history_items("hvac", "room_temp", hist[-144:], end, 1, "C")
        user = user + "\n" + "\n".join(f"{e} {t}" for e, _, t in hv)
        system = HV.SYSTEM_PROMPT + V.system_rules(n) + " " + V.output_schema_hint("hvac")
        prompt = F.llama3_prompt(system, user)
    else:
        if card.get("tank"):
            V.NODE_LIMITS[r["node"]] = {"high": card["tank"]["high"], "overflow": card["tank"]["overflow"], "fill_min": card["tank"]["fill_min"]}
        prompt = V.agent_prompt(role, r["node"], r["location"], metric, hist, n, end)[0]
    g = {k: r["gold"][k] for k in V2KEYS if k in r["gold"]}
    return {"id": r["id"] + "-b50", "pair_id": r["pair_id"], "family": r["family"], "role": r["role"], "stage": r.get("stage"),
            "slices": r.get("slices", []), "prompt": prompt, "completion": json.dumps(g, ensure_ascii=False) + "<|eot_id|>",
            "gold": g, "synthetic": True, "source": r["source"]}


def conv_real(rows, tag):
    v3, b50, agree = [], [], Counter()
    for r in rows:
        try:
            prompt, t, card = v3_from_real(r)
        except Exception as e:  # noqa: BLE001
            agree["error:" + repr(e)[:60]] += 1
            continue
        g2 = json.loads(r["completion"].replace("<|eot_id|>", ""))
        agree["status_same" if g2["status"] == t["status"] else "status_diff"] += 1
        agree["pattern_same" if g2["pattern"] == t["pattern"] else "pattern_diff"] += 1
        sl = r.get("slices_all") or []
        sl = json.loads(sl.replace("'", '"')) if isinstance(sl, str) else list(sl)
        if "stage_early" in sl:
            sl.append("stage_40min")
        safety = tag == "e1" and r.get("story") in SAFETY and r.get("intended") not in (None, "None")
        if safety:
            sl.append("safety")
        base = {"pair_id": r["id"], "family": r.get("family"), "role": r["role"], "slices": sl,
                "stage": next((s[6:] for s in sl if s.startswith("stage_")), None), "synthetic": False,
                "source": f"real_{tag}", "safety": safety}
        v3.append(dict(base, id=r["id"] + "-v3", prompt=prompt, completion=json.dumps(t, ensure_ascii=False) + "<|eot_id|>",
                       gold=t, card_id=card["card_id"]))
        b50.append(dict(base, id=r["id"] + "-b50", prompt=r["prompt"], completion=r["completion"], gold=g2))
    return v3, b50, agree


def rename(r, rng):
    """same window, new node name + building code in NODE/location (v3 prompt)."""
    code = "".join(rng.choice("BCDFGHJLMNPQRSTVWXZ") for _ in range(2))
    u = V.user_text(r["prompt"])
    lines = u.split("\n")
    i = next(k for k, l in enumerate(lines) if l.startswith("NODE: "))
    m = re.match(r"NODE: (.*?) \((.*)\)$", lines[i])
    dev, loc = m.group(1), m.group(2)
    new_dev = re.sub(r"[A-Za-z]{2}(\d{2})", lambda mm: code + mm.group(1), dev, count=1)
    if new_dev == dev:
        new_dev = f"{code}-{dev}"
    new_loc = re.sub(r"\b[A-Z]{2}\b", code, loc)
    lines[i] = f"NODE: {new_dev} ({new_loc})"
    sys_ = r["prompt"].split("<|start_header_id|>system<|end_header_id|>\n\n")[1].split("<|eot_id|>")[0]
    return F.llama3_prompt(sys_, "\n".join(lines))


def main():
    D = Path(sys.argv[1]) / "agt_v3"
    G = D / "gate"
    G.mkdir(parents=True, exist_ok=True)
    man = {}
    dev3f = rd(DEV3F)
    v3, b50, ag = conv_real(dev3f, "dev3f")
    wr(G / "dev3f_v3.jsonl", v3)
    wr(G / "dev3f_b50.jsonl", b50)
    man["dev3f"] = {"n": len(v3), "v2_vs_v3_gold": dict(ag)}
    e1 = rd(E1)
    v3, b50, ag = conv_real(e1, "e1")
    wr(G / "e1_v3.jsonl", v3)
    wr(G / "e1_b50.jsonl", b50)
    man["e1"] = {"n": len(v3), "safety_rows": sum(r["safety"] for r in v3), "v2_vs_v3_gold": dict(ag)}
    for name, out_v3, out_b50 in (("test_unseen_layout", "test_unseen_layout.jsonl", "test_unseen_layout_b50.jsonl"),
                                  ("test_campus", "test_campus_v3.jsonl", "test_campus_b50.jsonl")):
        rows = rd(D / f"{name}.jsonl")
        wr(G / out_v3, rows)
        bb = [x for x in (b50_from_v3(r) for r in rows) if x]
        wr(G / out_b50, bb)
        man[name] = {"n": len(rows), "b50_pairs": len(bb)}
    um = rd(D / "test_unseen_metric.jsonl")
    wr(G / "test_unseen_metric.jsonl", um)
    man["test_unseen_metric"] = {"n": len(um), "types": dict(Counter(r["card_type"] for r in um))}
    cf = rd(D / "calm_fault.jsonl")
    wr(G / "calm_fault_v3.jsonl", cf)
    man["calm_fault"] = {"n": len(cf)}
    rng = random.Random(77)
    base = [r for r in rd(D / "test_unseen_layout.jsonl")][:200]
    ren = []
    for r in base:
        o = dict(r, id=r["id"] + "-orig", pair_id=r["id"], variant="orig")
        n_ = dict(r, id=r["id"] + "-ren", pair_id=r["id"], variant="ren", prompt=rename(r, rng))
        p_ = dict(r, id=r["id"] + "-rep", pair_id=r["id"], variant="rep")
        ren += [o, n_, p_]
    wr(G / "rename_v3.jsonl", ren)
    man["rename"] = {"pairs": len(base), "rows": len(ren)}
    (G / "gate_manifest.json").write_text(json.dumps(man, indent=1))
    print(json.dumps(man, indent=1))


if __name__ == "__main__":
    main()
