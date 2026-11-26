"""setc_build.py: Set C stress requests for the board harness (setc_board.sh). N = 1/2/4/8/12 flagged sensors x 10 real held-out windows
(Set B end times, every 5th, first 10 with >= 12 live sensors). Same builders as prefill_table.py (pcase.assemble / render_reasoner, rule findings stand in for agent findings,
same line shape). Requests are the exact htpd wire format of the app (htpdclient.go / reasoner_v3.go htpdReasonLLM, profile reasoner_prompt=v4,
reasoner_split=3): agents = {"kind":"agents","prompts":[..]} in batches of 10 (htpdMaxBatch), reason = {"kind":"reason","prompt":..,"keep":true,
"prefix":<v4 static prefix>,"schema":..,"split":..,"split_after":"causal_chain"}. N >= 8 labelled synthetic (no natural window has 8+ flagged).
Run in WSL venv rsn. Output sets/C/{req/*.json, MANIFEST.json}."""
import json, os, hashlib
import env_setup as ES  # noqa: F401  (paths)
import pdata as D, pcase as P, pcore as C
from env_setup import Q
BK = Q + "/Code/smart-city-edge-agent/app/backend/"
import fmt_v4 as FM
HDR = open(BK + "reasoner_v3_header.txt", encoding="utf-8").read()
SYS3 = open(BK + "reasoner_v3_system.txt", encoding="utf-8").read()
HDR4 = HDR.replace('"name": "related_context", "description": "Incident-time only."',
                   '"name": "related_context", "description": "Incident-time only. Linked sensors not yet in the prompt: walks the site links (2 hops) from sensor ref."', 1)
assert HDR4 != HDR
SYS4 = FM.system_v4(SYS3)
PREFIX = HDR4 + SYS4 + "<|im_end|>\n<|im_start|>user\n"
OPEN = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
SCHEMA = json.load(open(BK + "testdata/reasoner_v3_force_schema.json"))
SPLIT = [["observations"], ["agent_checks", "affected_domains", "suspect_sensors", "evidence", "confidence"],
         ["checklist", "monitor_next", "needs_more_data", "needs_deeper", "explanation"]]
OUT = D.PAPER + "/sets/C"; os.makedirs(OUT + "/req", exist_ok=True)
ends = sorted({json.loads(l)["end"] for l in open(D.PAPER + "/sets/B.jsonl")})[::5]


def real_series(T):
    out = {}
    for s in D.SENSORS:
        w = D.window(s["node"], s["metric"], T, 144)
        if w is not None: out[s["key"]] = C.rnd(w, s["role"], s["metric"])
    return out


order = sorted([s for s in D.SENSORS if s["role"] != "hvac"], key=lambda s: (s["role"], s["key"]))
by = {}
for s in order: by.setdefault(s["role"], []).append(s["key"])
mix = []
while any(by.values()):
    for r in sorted(by):
        if by[r]: mix.append(by[r].pop(0))
man = dict(note=__doc__, sys_matches_host=(SYS4 == P.system_prompt()), prefix_sha=hashlib.sha256(PREFIX.encode()).hexdigest()[:16], cases=[])
rep = -1
for T in ends:
    ser = real_series(T)
    avail = [k for k in mix if k in ser]
    if len(avail) < 12: continue
    rep += 1
    if rep >= 10: break
    for N in (1, 2, 4, 8, 12):
        if len(avail) < N: continue
        case = dict(id="SC-%d-%d" % (T, N), end=T, series=ser, flagged=avail[:N])
        a = P.assemble(case)
        fnd = {s["ref"]: (s["rule"], True) for s in a["sensors"] if s["flagged"] and s["prompt"]}
        user, sens, ctx = P.render_reasoner(case, a, fnd)
        ag = [r["prompt"] for r in P.agent_requests(a)]
        name = "n%02d_r%d" % (N, rep)
        for b in range(0, len(ag), 10):
            json.dump({"kind": "agents", "prompts": ag[b:b + 10], "stream": True}, open("%s/req/%s_a%d.json" % (OUT, name, b // 10), "w"))
        json.dump({"kind": "reason", "prompt": PREFIX + user + "<|im_end|>\n" + OPEN, "keep": True, "prefix": PREFIX, "schema": SCHEMA,
                   "split": SPLIT, "split_after": "causal_chain", "stream": True}, open("%s/req/%s_r.json" % (OUT, name), "w"))
        man["cases"].append(dict(name=name, N=N, rep=rep, end=T, flagged=avail[:N], agent_calls=len(ag), agent_batches=(len(ag) + 9) // 10,
                                 sensors_in_prompt=len(a["sensors"]), prompt_chars=len(PREFIX + user), synthetic=N >= 8))
json.dump(man, open(OUT + "/MANIFEST.json", "w"), indent=1)
print("cases", len(man["cases"]), "sys==host", man["sys_matches_host"], {N: sum(c["N"] == N for c in man["cases"]) for N in (1, 2, 4, 8, 12)})
import glob  # htpd reads one JSON line per request: every request file ends with a newline
for f in glob.glob(OUT + "/req/*.json"):
    b = open(f, "rb").read()
    if not b.endswith(b"\n"): open(f, "wb").write(b + b"\n")
