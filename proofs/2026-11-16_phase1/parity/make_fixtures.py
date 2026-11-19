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


# ----------------------------------------------------------------------------------------------- cards
EC = CD.existing_cards()
import fmt_v4 as FM  # noqa: E402
cards = dict(EC)
cards["ac_units_on"] = FM.AC_COUNT
dump(BE + "/cards_existing.json", {"schema": CD.SCHEMA_VERSION, "cards": cards,
                                    "domain_names": CD.DOMAIN_NAMES, "base_actions": list(CD.BASE_ACTIONS),
                                    "faults_all": list(CD.FAULTS_ALL)})
# render checks for every card (full + line) -> Go TestCardRenderParity
rend = []
for cid, c in sorted(cards.items()):
    r = {"card_id": cid, "line": CD.render_line(c)}
    if cid != "ac_units_on":
        r["full"] = CD.render_full(c)
        r["full_place"] = CD.render_full(c, "lecture hall, capacity 120")
        r["validate"] = CD.validate_card(c)
    rend.append(r)
# synthetic cards (train + test types) for render + validate parity
R = random.Random(7)
syn = []
for ty in list(CD.TRAIN_TYPES) + list(CD.TEST_TYPES):
    for k in range(3):
        c = CD.synthetic_card(ty, R)
        syn.append({"card": c, "full": CD.render_full(c), "line": CD.render_line(c), "validate": CD.validate_card(c)})
# broken cards -> validator messages
bad = []
for mut in ("kind", "dir", "order", "imp", "causes", "action", "missing"):
    c = copy.deepcopy(EC["co2_indoor"])
    if mut == "kind":
        c["kind"] = "blob"
    elif mut == "dir":
        c["warning"] = {"dir": "up", "at": 1000}
    elif mut == "order":
        c["critical"] = {"dir": "high", "at": 900}
    elif mut == "imp":
        c["impossible"] = {"below": 500, "above": 5000}
    elif mut == "causes":
        c["causes"] = ["normal_conditions"]
    elif mut == "action":
        c["actions"] = c["actions"] + ["open_valve"]
    elif mut == "missing":
        del c["noise"]
    bad.append({"mut": mut, "card": c, "validate": CD.validate_card(c)})
dump(TD + "/cards_fixtures.json", {"existing": rend, "synthetic": syn, "broken": bad})

# ----------------------------------------------------------------------------------------------- agt_v3
sys.path.insert(0, AGT)
import build_gate as BG  # noqa: E402
sys.path.insert(0, AGT)


def v3_from_v2_prompt(role, metric, node, location, v2prompt, n):
    u = V.user_text(v2prompt)
    lines = u.split("\n")
    card = BG.card_for(role, metric, node, location)
    wi = next(i for i, l in enumerate(lines) if l.startswith("WINDOW: "))
    user = "\n".join([CD.render_full(card), f"NODE: {node} ({location})"] + lines[wi:])
    return F.llama3_prompt(EV.agent_system(card, n), user), card


fx = json.load(open(TD + "/v2_prompt_fixtures.json"))
agt_a = []
for i, f in enumerate(fx["fixtures"]):
    role = f["role"]
    p, card = v3_from_v2_prompt(role, f["metric"], f["node"], f.get("location", ""), f["prompt"], int(f["n"]))
    agt_a.append({"idx": i, "card_id": card["card_id"], "tank": card.get("tank"), "prompt": p})

agt_b = []
want = {"dev.jsonl": 160, "test_unseen_metric.jsonl": 120, "test_campus.jsonl": 60}
for fn, k in want.items():
    got, tried = 0, 0
    kinds = {}
    with open(AGT + "/" + fn) as fh:
        for line in fh:
            if got >= k:
                break
            r = json.loads(line)
            if r["card"]["kind"] in kinds and kinds[r["card"]["kind"]] > k // 2 and r["card"]["kind"] != "hvac_unit":
                continue
            tried += 1
            hist = r["hist"] if isinstance(r["hist"], list) else json.loads(r["hist"])
            n, end = int(r["n"]), int(r["end_epoch"])
            hc = r.get("hvac_ctx")
            try:
                if hc is not None:
                    hc = dict(hc)
                    hc["end"] = end
                user, st, ev, info = EV.agent_user(r["card"], r["node"], r["location"], hist, n, end, place=r.get("place"), hvac_ctx=hc)
            except Exception as ex:  # noqa: BLE001
                continue
            p = F.llama3_prompt(EV.agent_system(r["card"], n), user)
            if p != r["prompt"]:
                continue
            kinds[r["card"]["kind"]] = kinds.get(r["card"]["kind"], 0) + 1
            agt_b.append({"id": r["id"], "card": r["card"], "node": r["node"], "location": r["location"], "place": r.get("place"),
                          "hist": hist, "n": n, "end": end, "hvac_ctx": r.get("hvac_ctx"), "prompt": p,
                          "completion": r["completion"]})
            got += 1
    out_stats["agt_" + fn] = {"kept": got, "tried": tried, "kinds": kinds}
dump(TD + "/agt_v3_fixtures.json", {"from_v2": agt_a, "rows": agt_b})

print(json.dumps(out_stats, indent=1))
