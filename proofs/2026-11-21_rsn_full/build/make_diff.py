"""make_diff.py: writes ../TOOLS_DIFF.md (app tools vs tools_v4 / tools_v5, pool + gen5 counts, one real result example per tool)."""
import collections
import json
import os

H = os.path.dirname(os.path.abspath(__file__))
Q = os.path.abspath(os.path.join(H, "..", ".."))
D = os.path.join(H, "..", "data")
v4 = json.load(open(Q + "/2026-11-20_rsn_big/data/final_big/tools_v4.json"))
v5 = json.load(open(D + "/tools_v5.json"))
hdr = {}
for l in open(Q.replace("/proofs", "") + "/Code/smart-city-edge-agent/app/backend/chat_header_r5.txt", encoding="utf-8"):
    if l.startswith('{"type": "function"'):
        f = json.loads(l)["function"]
        hdr[f["name"]] = f["parameters"]
v4n = {f["function"]["name"]: f["function"]["parameters"] for f in v4["chat_r5"]}
v5n = {f["function"]["name"]: f["function"]["parameters"] for f in v5["chat_r6"]}
pool = collections.Counter()
for fn in ("pool_train_new.jsonl", "pool_replay.jsonl"):
    for l in open(Q + "/2026-11-20_rsn_big/data/final_big/" + fn, encoding="utf-8"):
        r = json.loads(l)
        if r.get("tools") == "chat_r5":
            for m in r["messages"]:
                for tc in m.get("tool_calls") or []:
                    pool[tc["function"]["name"]] += 1
gen, ex = collections.Counter(), {}
for l in open(D + "/gen5_tools.jsonl", encoding="utf-8"):
    r = json.loads(l)
    ms = r["messages"]
    for i, m in enumerate(ms):
        for tc in m.get("tool_calls") or []:
            n = tc["function"]["name"]
            gen[n] += 1
            if n not in ex and ms[i + 1]["role"] == "tool":
                ex[n] = (json.dumps(tc["function"]["arguments"]), ms[i + 1]["content"][:230])
ROUTER = {"forecast_crossing", "data_health"}
L = ["# TOOLS_DIFF: tools the on-board app can call vs tools_v4.json", "",
     "Sources: backend chat.go / chat_tools_v3.go / chat_fog.go / chat_site.go (model-callable, schemas in chat_header_r5.txt), chat_polish.go + chat_router_v25.go (router-only records),",
     "reasoner_v3.go/reasoner_v4.go (report/incident tools), agent_tools.go (agent protocol). Schema match = header JSON `parameters` equal to tools_v4 `chat_r5` (checked by script).", "",
     "| tool | callable by | in tools_v4 | schema match v4 | in tools_v5 | pool rows | gen5 rows | result example (twin) |", "|---|---|---|---|---|---|---|---|"]
for n in v5n:
    by = "router only (not in model header)" if n in ROUTER else "model (chat_header_r5)"
    in4 = n in v4n
    match = ("yes" if hdr.get(n) == v4n[n] else "NO") if in4 and n in hdr else ("n/a" if not in4 else "yes (v4 only)")
    e = ex.get(n)
    L.append("| %s | %s | %s | %s | yes | %d | %d | `%s` -> `%s` |" % (n, by, "yes" if in4 else "NO", match, pool[n], gen[n], e[0] if e else "-", (e[1].replace("|", "/") if e else "-")))
L += ["", "## Incident / report tools (reasoner_v3/v4)", "",
      "related_context, get_sensor_history, get_action_history, find_incidents: all four in tools_v4 `incident` / `incident_v4` (v4 related_context description patched in reasoner_v4.go v4Header, matches incident_v4).", "",
      "## Agent tools (agent_tools.go, domain agents, NOT the chat protocol)", "",
      "get_history(hours 6|12), get_neighbors(), get_card(): JSON-in-text calls `{\"tool\": ..., \"args\": {...}}` with H*/N* result lines; belong to the sensor-agent dataset, deliberately not in tools_v5 chat/incident sets.", "",
      "## Findings", "",
      "- All 25 model-callable chat tools are in tools_v4 chat_r5 with identical schemas (script-verified); nothing missing for the model header.",
      "- Missing from tools_v4: `forecast_crossing(node, metric, target)` and `data_health()`. Both are produced by the deterministic router (chat_polish.go), recorded as ChatTool, never offered to the model. tools_v5 adds them as `chat_r6` (= chat_r5 + 2).",
      "- Router records carry less than a model needs: forecast_crossing = {state,last,slope_per_h}, data_health = counts only. The twin adds `at`/`unit` and sensor lists. To train on chat_r6 the Go header must list both tools and return those fields (proposed change), otherwise train gen5_forecast_crossing / gen5_data_health with chat_r5 and drop them.",
      "- Tools with 0 pool rows before gen5: sensor_faults, domain_health, get_action_history, compare_periods, what_if, faulty_sensors; < 150: search_knowledge (3), recent_incidents (13), fog_status (13), recurring_issues (16), open_incidents (49), get_site_tree (45), nodes_under (61)."]
open(H + "/../TOOLS_DIFF.md", "w", newline="\n").write("\n".join(L) + "\n")
print("ok")
