"""v2 step 1: windows for the agt_v3 real-output family (CPU, deterministic).
  python3 v2_windows.py --out data/final_v2/work/windows.jsonl [--n-syn 1500] [--n-real 500] [--seed 31115]
Synthetic: fresh gen_agt windows on TRAIN sites (new seed; existing, non-jittered cards only).
Real: cleaned real pool windows (train split, label audit supported, not used by any test suite), hist from sft_v2/test.jsonl,
agt_v3 prompt rebuilt with core/evidence.py. Every window keeps the E-lines the agent sees (parsed from its prompt) and a gold
that passes the label-audit judge on those exact lines (evidence-supported); others are dropped and counted."""
import argparse
import collections
import datetime as dt
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
Q = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "agt_v3"))
import gen_agt as GA  # noqa: E402
import evidence as EV  # noqa: E402
import cards as CD  # noqa: E402
sys.path.insert(0, os.path.join(Q, "proofs", "2026-11-13_label_audit", "scripts"))
import audit as AU  # noqa: E402

ALLOWED = {"co2_indoor": ("air_quality", "co2"), "temp_indoor": ("air_quality", "temp"), "rh_indoor": ("air_quality", "rh"),
           "pm25_indoor": ("air_quality", "pm25"), "pm25_outdoor": ("air_quality", "pm25"), "pm10_outdoor": ("air_quality", "pm10"),
           "tank_level": ("water", "level"), "water_flow": ("water", "flow"), "power_load": ("power", "power_kw"),
           "power_pf": ("power", "pf"), "weather_temp": ("weather", "temp"), "weather_rh": ("weather", "rh"),
           "weather_wind": ("weather", "wind"), "occupancy": ("occupancy", "occ"), "hvac_unit": ("hvac", "room_temp")}
UNIT = {"co2": "ppm", "temp": "C", "rh": "%", "pm25": "ug/m3", "pm10": "ug/m3", "level": "level", "flow": "m3/h", "power_kw": "kW",
        "pf": "ratio", "wind": "m/s", "occ": "0/1", "room_temp": "C] with AC state and setpoint ["}
FAMS = {"ex_event": 30, "ex_fault": 16, "ex_stable": 8, "ex_longrange": 5, "ex_occupancy": 4, "ex_hvac": 5, "hole_power": 12,
        "hole_water": 9, "hole_calm_fault": 6, "calm_routine": 10, "dq_edge": 5}
THR = json.load(open(os.path.join(Q, "proofs", "2026-11-13_label_audit", "thresholds.json")))


def lim_head(card):
    w, c = card.get("warning"), card.get("critical")
    if card["card_id"] == "tank_level":
        t = card.get("tank") or {}
        return ["TANK: high level above %.1f, overflow risk above %.1f; usual fill up to %d min" % (t["high"], t["overflow"], t["fill_min"])] if t else []
    if card["card_id"] == "hvac_unit":
        return ["LIMITS: comfort band setpoint -3/+2 C; warning above 30, critical above 34"]
    if not w or not c or "at" not in w:
        return []
    d = "above" if w["dir"] == "high" else "below"
    f = lambda x: ("%g" % x)  # noqa: E731
    return ["LIMITS: warning %s %s, critical %s %s" % (d, f(w["at"]), d, f(c["at"]))]


def elines(prompt):
    u = prompt.split("user<|end_header_id|>", 1)[1].split("<|eot_id|>", 1)[0]
    return [[m.group(1), m.group(2)] for m in re.finditer(r"^(E\d+) (.*)$", u, re.M)]


def supported(role, metric, gold, head, ev, n, end):
    F = AU.feats(role, dict(ev), n)
    off = dt.datetime.fromtimestamp(end, EV.V.IST).weekday() >= 5
    s, why, sg = AU.judge(role, metric, gold["status"], gold.get("fault_kind"), F, head, n, THR, None, {"offday": off})
    strong = any("p97.5" not in x for x in sg)
    if gold["status"] == "sensor_fault" and not strong:   # v1 rule for fault golds: strong signature only
        return "n", "fault_weak_signature"
    return s, why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-syn", type=int, default=1500)
    ap.add_argument("--n-real", type=int, default=500)
    ap.add_argument("--seed", type=int, default=31115)
    a = ap.parse_args()
    st = collections.Counter()
    out = []
    # ---------------- synthetic (train sites)
    R = random.Random(a.seed)
    tasks = {f: GA.Task("train", f, 900 + i, 10 ** 6, a.seed) for i, f in enumerate(FAMS)}
    fams, w = list(FAMS), list(FAMS.values())
    tries = 0
    while sum(1 for x in out if x["src"] == "syn") < a.n_syn and tries < a.n_syn * 30:
        tries += 1
        f = R.choices(fams, w)[0]
        try:
            r = GA.one(tasks[f])
        except Exception as ex:  # noqa: BLE001
            st["syn_exc:" + type(ex).__name__] += 1
            continue
        if not r:
            continue
        if r.get("jittered") or r.get("card_synthetic") or r["card_id"] not in ALLOWED:
            st["syn_skip_card"] += 1
            continue
        role, metric = ALLOWED[r["card_id"]]
        card = r["card"]
        head = lim_head(card)
        ev = elines(r["prompt"])
        g = r["gold"]
        s, why = supported(role, metric, g, head, ev, r["n"], r["end_epoch"])
        if s != "y":
            st["syn_unsupported"] += 1
            continue
        node = r["node"] if not r["card_id"].endswith("_outdoor") else "AQ-OUT-%02d" % R.randrange(100)
        out.append({"wid": "syn-%05d" % len(out), "src": "syn", "family_agt": f, "card_id": r["card_id"], "role": role, "metric": metric,
                    "node": node, "loc": r["location"], "n": r["n"], "end_epoch": r["end_epoch"], "prompt": r["prompt"],
                    "head": ["NODE: %s (%s)" % (node, r["location"]), ("METRIC: %s [%s]" % (metric, UNIT[metric])).replace(" [] ", " ").replace("setpoint []", "setpoint")] + head,
                    "ev": ev, "gold": {k: g.get(k) for k in ("pattern", "status", "likely_cause", "fault_kind", "event_active", "onset")},
                    "audit_why": why})
        st["syn:" + g["status"]] += 1
    st["syn_tries"] = tries
    # ---------------- real (cleaned pool)
    aud = {json.loads(l)["pool_id"]: json.loads(l) for l in open(os.path.join(Q, "proofs", "2026-11-13_label_audit", "pool_audit.jsonl"))}
    ban = set()
    for l in open(os.path.join(Q, "proofs", "2026-11-13_label_audit", "audit.jsonl")):
        x = json.loads(l)
        if x["file"] not in ("r3_train", "r1_train", "r4_replay") and x["pool_id"]:
            ban.add(x["pool_id"])
    pool = {}
    for l in open(os.path.join(Q, "proofs", "2026-10-25_reasoner_final", "data", "real_pool.jsonl")):
        p = json.loads(l)
        if p["split"] == "train" and aud.get(p["id"], {}).get("supported") == "y" and p["id"] not in ban and p["role"] != "hvac":
            pool.setdefault(p["id"], p)
    ids = sorted(pool)
    R.shuffle(ids)
    want = set(ids)
    hist = {}
    for l in open(os.path.join(Q, "Code", "smart-city-edge-agent", "data", "sft_v2", "test.jsonl"), encoding="utf-8"):
        m = re.search(r'"id": "([^"]+)"', l[-400:]) or re.search(r'"id": "([^"]+)"', l)
        if m and m.group(1) in want:
            d = json.loads(l)
            hist[d["id"]] = d["hist"]
    st["real_candidates"] = len(ids)
    nreal = 0
    for pid in ids:
        if nreal >= a.n_real:
            break
        p = pool[pid]
        h = hist.get(pid)
        if not h or p["n"] % 2:
            st["real_nohist"] += 1
            continue
        loc = next((x.split("(", 1)[1].rstrip(")") for x in p["head"] if x.startswith("NODE:") and "(" in x), p["node"])
        try:
            cid = CD.metric_to_card(p["role"], p["metric"], p["node"], loc)
            card = json.loads(json.dumps(CD.existing_cards()[cid]))
            if cid == "tank_level":
                tl = GA.NODE_LIMITS.get(p["node"])
                card["tank"] = {k: tl[k] for k in ("high", "overflow", "fill_min")} if tl else None
            prompt, _, _, _ = EV.agent_prompt(card, p["node"], loc, h[-144:], p["n"], p["end_epoch"])
        except Exception as ex:  # noqa: BLE001
            st["real_exc:" + type(ex).__name__] += 1
            continue
        ev = elines(prompt)
        head = [x for x in p["head"] if x.startswith(("LIMITS:", "TANK:"))]
        s, why = supported(p["role"], p["metric"], p["gold"], head, ev, p["n"], p["end_epoch"])
        if s != "y":
            st["real_unsupported_new_elines"] += 1
            continue
        st["real_elines_same_as_pool"] += int(ev == p["ev"])
        out.append({"wid": "real-%05d" % nreal, "src": "real", "pool_id": pid, "card_id": cid, "role": p["role"], "metric": p["metric"],
                    "node": p["node"], "loc": loc, "n": p["n"], "end_epoch": p["end_epoch"], "prompt": prompt,
                    "head": [x for x in p["head"] if not x.startswith("WINDOW:")], "ev": ev, "gold": p["gold"], "audit_why": why})
        st["real:" + p["gold"]["status"]] += 1
        nreal += 1
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out + ".part", "w", encoding="utf-8", newline="\n") as f:
        for x in out:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    os.replace(a.out + ".part", a.out)
    json.dump(dict(sorted(st.items())), open(a.out + ".stats.json", "w", newline="\n"), indent=1)
    print(json.dumps(dict(sorted(st.items()))))


if __name__ == "__main__":
    main()
