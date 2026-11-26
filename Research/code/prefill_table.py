"""prefill_table.py (item 2): token counts of REAL prompt builders (pcase.assemble/render_reasoner, agent prompts, Mode 2-fair filter) for N = 1/2/4/8/12 flagged sensors.
N flagged sensors drawn from the 18-sensor campus network on 6 real windows (set-B end times); rule findings stand in for agent findings (same line shape).
Tokenizer = the GGUF's own (llama-server /tokenize, CPU, vocab of the Q4_0 models). Output results/prefill_table.json. Run in WSL venv rsn."""
import json, os, subprocess, time, urllib.request, statistics as S
import env_setup as ES
import pdata as D, pcase as P, pcore as C
from env_setup import Q
LC = os.path.expanduser("~/llama-cuda-b11815")
AGT = os.path.expanduser("~/smartcity_runs/agt_topup_k2b/post/s0450/agt3_s0450_q4_0.gguf")
RSN = Q + "/Code/models_stage/rsn_v3_4b_v5_q4_0.gguf"
ends = sorted({json.loads(l)["end"] for l in open(D.PAPER + "/sets/B.jsonl")})[::25][:6]
def real_series(T):
    out = {}
    for s in D.SENSORS:
        w = D.window(s["node"], s["metric"], T, 144)
        if w is not None: out[s["key"]] = C.rnd(w, s["role"], s["metric"])
    return out
order = sorted([s for s in D.SENSORS if s["role"] != "hvac"], key=lambda s: (s["role"], s["key"]))
# interleave roles so N sensors span domains
by = {}
for s in order: by.setdefault(s["role"], []).append(s["key"])
mix = []
while any(by.values()):
    for r in sorted(by):
        if by[r]: mix.append(by[r].pop(0))
rows = []
for T in ends:
    ser = real_series(T)
    avail = [k for k in mix if k in ser]
    for N in (1, 2, 4, 8, 12):
        if len(avail) < N: continue
        case = dict(id="PT-%d-%d" % (T, N), end=T, series=ser, flagged=avail[:N])
        a = P.assemble(case)
        fnd = {s["ref"]: (s["rule"], True) for s in a["sensors"] if s["flagged"] and s["prompt"]}
        user, sens, ctx = P.render_reasoner(case, a, fnd)
        m2 = chr(10).join(l for l in user.split(chr(10)) if not (l.startswith("  agent") or l.startswith("  - ")))
        rows.append(dict(N=N, end=T, n_sensors_in_prompt=len(a["sensors"]), n_agent_calls=len(P.agent_requests(a)), agent_prompts=[r["prompt"] for r in P.agent_requests(a)],
                         system=P.system_prompt(), user=user, user_m2=m2))
print("built", len(rows), flush=True)
def serve(model, port):
    env = dict(os.environ, LD_LIBRARY_PATH=LC + "/bin")
    p = subprocess.Popen(["nice", LC + "/bin/llama-server", "-m", model, "-ngl", "0", "-c", "512", "-np", "1", "-t", "2", "--jinja", "--host", "127.0.0.1", "--port", str(port), "--no-webui"],
                         stdout=open("/tmp/pt_%d.log" % port, "w"), stderr=subprocess.STDOUT, env=env)
    for _ in range(200):
        try: urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=3); return p
        except Exception: time.sleep(3)
    p.kill(); raise SystemExit("server failed")
def post(port, path, d):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), json.dumps(d).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=120))
def ntok(port, text): return len(post(port, "/tokenize", dict(content=text, add_special=False, parse_special=True))["tokens"])
p = serve(RSN, 18411)
try:
    for r in rows:
        for k, u in (("rsn_full_tokens", r["user"]), ("rsn_m2_tokens", r["user_m2"])):
            pr = post(18411, "/apply-template", dict(messages=[{"role": "system", "content": r["system"]}, {"role": "user", "content": u}]))["prompt"]
            r[k] = ntok(18411, pr)
finally:
    p.terminate(); p.wait()
p = serve(AGT, 18412)
try:
    for r in rows: r["agent_tokens"] = [ntok(18412, t) for t in r["agent_prompts"]]
finally:
    p.terminate(); p.wait()
tab = {}
for N in (1, 2, 4, 8, 12):
    rr = [r for r in rows if r["N"] == N]
    if not rr: continue
    at = [x for r in rr for x in r["agent_tokens"]]
    tab[N] = dict(windows=len(rr), agent_calls=round(S.mean(r["n_agent_calls"] for r in rr), 1), agent_tok_per_call=round(S.mean(at)) if at else None, agent_tok_total=round(S.mean(sum(r["agent_tokens"]) for r in rr)),
                  rsn_full_tok=round(S.mean(r["rsn_full_tokens"] for r in rr)), rsn_full_max=max(r["rsn_full_tokens"] for r in rr), rsn_m2_tok=round(S.mean(r["rsn_m2_tokens"] for r in rr)),
                  rsn_m2_max=max(r["rsn_m2_tokens"] for r in rr), sensors_in_prompt=round(S.mean(r["n_sensors_in_prompt"] for r in rr), 1))
json.dump(dict(table=tab, rows=[{k: v for k, v in r.items() if k not in ("agent_prompts", "system", "user", "user_m2")} for r in rows]), open(D.PAPER + "/results/prefill_table.json", "w"), indent=1)
print(json.dumps(tab, indent=1))
