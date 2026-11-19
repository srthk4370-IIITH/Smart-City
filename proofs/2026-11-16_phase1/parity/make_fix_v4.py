"""Phase 1 parity fixtures (Python = reference, Go must match).

Writes into Code/smart-city-edge-agent/app/backend/testdata/ (and the embedded copies next to the Go code):
  cards_existing.json          cards.existing_cards() (+ fmt_v4 AC_COUNT) -> embedded by cards.go
  agt_v3_fixtures.json         agt_v3 prompts: (a) every v2 Go parity fixture converted as build_gate.v3_from_real does,
                               (b) synthetic / campus / unseen-metric rows (card + hist + hvac ctx) re-rendered by
                               evidence.agent_user; only rows whose Python re-render equals the stored row prompt
  v4_fixtures.json             fmt_v4.render_v4 (case, ctx, text) captured while gen_inc_v4 builds rows; system_v4 text
  site_tools_fixtures.json     gen_chat_v4.SiteTools results on campus_site() + gen_site() sites with overlays
  chat_header_r5.txt / chat_system_r5.txt   (backend/, embedded) r3 header + the 4 site tools; r3 system + SITE_RULE
usage (WSL): python3 make_fixtures.py
"""
import copy
import json
import os
import random
import re
import sys

QIDK = "/mnt/c/Users/hp/Desktop/qidk"
CORE = QIDK + "/proofs/2026-11-13_v3_data/core"
RSN = QIDK + "/proofs/2026-11-13_v3_data/rsn"
AGT = QIDK + "/proofs/2026-11-13_v3_data/agt_v3"
BE = QIDK + "/Code/smart-city-edge-agent/app/backend"
TD = BE + "/testdata"
sys.path.insert(0, CORE)
sys.path.insert(0, RSN)
import evidence as EV  # noqa: E402  (sets up training paths)
import cards as CD  # noqa: E402
import features as F  # noqa: E402
import features_v2 as V  # noqa: E402
import sitegraph as SG  # noqa: E402

out_stats = {}


def dump(path, obj):
    with open(path, "w", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=None, separators=(",", ":"))
    print("wrote", path, os.path.getsize(path))


import fmt_v4 as FM
# ----------------------------------------------------------------------------------------------- v4 reasoner
import gen_inc_v4 as G  # noqa: E402
cap = []
_orig = FM.render_v4


def jdef(o):
    if hasattr(o, "timestamp"):
        return {"__dt__": int(o.timestamp())}
    return list(o)


def rec(case, ctx):
    t = _orig(case, ctx)
    if len(cap) < 4000:
        cap.append((json.loads(json.dumps(case, default=jdef)), json.loads(json.dumps(ctx, default=jdef)), t))
    return t


FM.render_v4 = rec
R = random.Random(11)
for i in range(70):
    try:
        G.gen_r4(R, 0, "dev", agt=(i % 3 != 0))
    except Exception as ex:  # noqa: BLE001
        print("gen_r4 err", repr(ex)[:300]) if i < 2 else None
for i in range(40):
    try:
        G.gen_site_fam(R, "dev", R.choice(["panel_trip", "shared_panel_occ", "ac_multi_trip"]), agt=(i % 2 == 0))
    except Exception:  # noqa: BLE001
        pass
for i in range(50):
    try:
        G.gen_card(R, "dev", CD.TRAIN_TYPES, agt=True)
    except Exception:  # noqa: BLE001
        pass
FM.render_v4 = _orig
# dedupe and keep at most 400
seen, v4 = set(), []
for case, ctx, t in cap:
    if t in seen:
        continue
    seen.add(t)
    v4.append({"case": case, "ctx": ctx, "text": t})
R.shuffle(v4)
v4 = v4[:400]
sysr3 = open(BE + "/reasoner_v3_system.txt").read()
dump(TD + "/v4_fixtures.json", {"system_r3": sysr3, "system_v4": FM.system_v4(sysr3), "rows": v4})
out_stats["v4_rows"] = len(v4)

# ----------------------------------------------------------------------------------------------- site tools + header r5
import gen_chat_v4 as GC  # noqa: E402
sites = [SG.campus_site()] + [SG.gen_site(s, "dev") for s in range(6)]
st_rows = []
R = random.Random(5)
for si, site in enumerate(sites):
    for k in range(4):
        status, inc = GC.overlay(R, site)
        T = GC.SiteTools(site, status, inc)
        ids = [n["id"] for n in site["nodes"]]
        names = [n.get("name") for n in site["nodes"] if n.get("name")]
        calls = []
        for j in range(10):
            nm = R.choice(["get_site_tree", "nodes_under", "linked_equipment", "site_status"])
            node = R.choice(ids + names + ["nowhere-123"])
            if nm == "get_site_tree":
                a = {} if R.random() < 0.2 else {"node": node, "depth": R.choice([1, 2, 3])}
            elif nm == "nodes_under":
                a = {"node": node}
                if R.random() < 0.4:
                    a["kind"] = R.choice(FM.KINDS)
                if R.random() < 0.3:
                    a["status"] = R.choice(["normal", "warning", "critical", "data_issue"])
                if R.random() < 0.2:
                    a["metric"] = R.choice(["co2", "temp", "level", "power_kw", "occ"])
            elif nm == "linked_equipment":
                a = {"node": node}
                if R.random() < 0.4:
                    a["link"] = R.choice(FM.LINKS)
                if R.random() < 0.4:
                    a["direction"] = R.choice(["out", "in", "both"])
            else:
                a = {"node": node}
            calls.append({"name": nm, "args": a, "result": T.call(nm, dict(a))})
        st_rows.append({"site": si, "status": status, "incidents": inc, "calls": calls})
        # suspects + relation fixtures for grouping parity
    ix = SG.Index(site)
    sens = sorted(n["id"] for n in site["nodes"] if n["kind"] == "sensor")
    rel = []
    for j in range(60):
        a, b = R.choice(sens), R.choice(sens)
        r_, w, h = ix.relation(a, b)
        rel.append({"a": a, "b": b, "relation": r_, "window": w, "hops": h})
    sus = []
    for j in range(15):
        on = {s: 1793000000 + R.randrange(0, 4) * 600 for s in R.sample(sens, min(len(sens), R.randrange(2, 7)))}
        sus.append({"onsets": on, "suspects": ix.suspects(on)})
    st_rows.append({"site": si, "relations": rel, "suspects": sus})
dump(TD + "/site_tools_fixtures.json", {"sites": sites, "rows": st_rows})

tools_r3 = json.load(open(QIDK + "/proofs/2026-11-06_4b_local/tools/tools_r3.json")) if os.path.exists(
    QIDK + "/proofs/2026-11-06_4b_local/tools/tools_r3.json") else None
hdr = open(BE + "/chat_header_r3.txt").read()
lines = hdr.split("\n")
tl = [i for i, l in enumerate(lines) if l.startswith('{"type": "function"')]
if tools_r3 is not None:
    assert [json.loads(lines[i]) for i in tl] == tools_r3["chat"], "r3 header tools != tools_r3.json chat"
    assert all(lines[i] == json.dumps(t) for i, t in zip(tl, tools_r3["chat"])), "json.dumps format differs"
r5 = lines[:tl[-1] + 1] + [json.dumps(t, ensure_ascii=False) for t in FM.SITE_TOOLS] + lines[tl[-1] + 1:]
with open(BE + "/chat_header_r5.txt", "w", newline="\n") as f:
    f.write("\n".join(r5))
sys3 = open(BE + "/chat_system_r3.txt").read()
with open(BE + "/chat_system_r5.txt", "w", newline="\n") as f:
    f.write(FM.chat_system_r5(sys3))
tv4 = json.load(open(RSN + "/data/final/tools_v4.json"))
assert [json.loads(lines2) for lines2 in [json.dumps(t) for t in tv4["chat_r5"]]] == tv4["chat_r5"]
ok_r5 = [json.loads(l) for l in r5 if l.startswith('{"type": "function"')] == tv4["chat_r5"]
out_stats["header_r5_matches_tools_v4"] = ok_r5
print(json.dumps(out_stats, indent=1))
