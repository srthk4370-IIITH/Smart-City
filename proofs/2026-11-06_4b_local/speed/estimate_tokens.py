"""item 4 (light, no torch): prefix tokens saved by --shared-prefix on the REAL schedule of the live 4B r3 run.
Per optimizer step (16 rows of schedule.json): chat rows with the chat tools share the 21-tool header (+ the common start of the
system message), incident rows share system prompt + incident tools. Shared prefix lengths P_CHAT / P_INC are the measured LCPs
of real rows (eq_shared.log: 4637 / 1319 tokens; the header alone is 4579), mean row lengths from lengths_r3.json.
Layer tokens (forward + recompute + backward through 32 decoder layers) are the cost proxy; the vocab CE (label tokens only) and
fixed per-forward costs are unchanged by sharing. usage: estimate_tokens.py <schedule.json> <out.json>"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "..", "data", "final")
P_CHAT, P_INC = 4579, 1319          # conservative: header only for chat
L = json.load(open(os.path.join(HERE, "..", "lengths_r3.json")))
M_INC, M_CHAT = L["incidents_train.jsonl"]["mean"], L["chat_train_r3.jsonl"]["mean"]
kind = {}
for f in ("incidents_train.jsonl", "chat_train_r3.jsonl"):
    for line in open(os.path.join(D, f), encoding="utf-8"):
        ex = json.loads(line)
        kind[ex["id"]] = ex["tools"]
S = json.load(open(sys.argv[1]))
G = S["groups"]
base = new = 0.0
hist = {}
for g in G:
    ki = sum(kind[k] == "incident" for k in g)
    kc = sum(kind[k] == "chat" for k in g)
    kn = len(g) - ki - kc
    t = ki * M_INC + (kc + kn) * M_CHAT
    saved = (max(ki - 1, 0) * P_INC) + (max(kc - 1, 0) * P_CHAT)
    base += t
    new += t - saved
    hist[kc] = hist.get(kc, 0) + 1
r = {"steps": len(G), "rows_per_step": len(G[0]), "mean_layer_tokens_per_step_base": round(base / len(G)),
     "mean_layer_tokens_per_step_shared": round(new / len(G)), "layer_token_ratio": round(base / new, 3),
     "share_of_tokens_removed": round(1 - new / base, 3), "chat_rows_per_step_histogram": dict(sorted(hist.items())),
     "assumed": {"P_CHAT": P_CHAT, "P_INC": P_INC, "mean_inc": M_INC, "mean_chat": M_CHAT}}
json.dump(r, open(sys.argv[2], "w"), indent=1)
print(json.dumps(r, indent=1))
