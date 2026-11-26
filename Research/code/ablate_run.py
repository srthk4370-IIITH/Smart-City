"""ablate_run.py (item 4): copy of run_case.py reasoner phase for Mode 3 ablations on Set B (reuses runs/full agent outputs). --phase nt = no tools (no retrieval, no more-data tool calls: tools=None);
--phase nc = no context agents (only flagged sensors in the prompt);
--phase rt = retrieval ON: a frozen past-incident store (store_build() below) feeds MEMORY (Go memoryLines) and the find_incidents / get_action_history tools (Go incidentTools). Output runs/full/reasoner_abl_<phase>_out.jsonl."""
"""run_case.py: ONE run per case = full path (domain agents on the NPU model + reasoner); the cheap arm (agents + template report, Go isolatedReport /
fallbackReport ported in pcase.py) is computed OFFLINE from the same logged agent outputs. Host (laptop GPU, Q4_0 == board, 207/208 parity).
  python3 run_case.py --tag pilot --sets B --limit 30 --stratified --phase all
Phases (each resumable, JSONL on disk under runs/<tag>/):
  agents   : deployed agent GGUF (agt3_s0450_q4_0) on every flagged sensor's app-identical prompt (v2_agent_run_gpu.py: greedy, JSON prefill, stop at "action")
  reasoner : rsn_v3_4b_v5_q4_0.gguf on the incident_v4 prompt + tools incident_v4 (tools_v5.json), think = adaptive (enable_thinking), greedy, tool loop
             (tools answer from an EMPTY frozen corpus: retrieval surface = 0, see LEAKAGE.md)
  merge    : records.jsonl, one line per case: prompts, outputs, tokens, wall times, think, trigger signals, both arms' reports
GPU: takes the GPU lock (proofs/2026-10-29_rsn_v3/GPU_LOCK, the lock every gate script uses), only when the GPU is idle; restores the previous content
on exit; never kills a process it did not start; ONE model at a time (agents phase for all cases, then reasoner phase)."""
import argparse, json, os, re, subprocess, sys, time, hashlib, urllib.request
import env_setup as ES
import pdata as D, pcase as P, pcore as C
from env_setup import Q

LOCK = Q + "/proofs/2026-10-29_rsn_v3/GPU_LOCK"
AGT_MODEL = os.path.expanduser("~/smartcity_runs/agt_topup_k2b/post/s0450/agt3_s0450_q4_0.gguf")
RSN_MODEL = Q + "/Code/models_stage/rsn_v3_4b_v5_q4_0.gguf"
TOOLS = Q + "/proofs/2026-11-21_rsn_full/data/tools_v5.json"
LC = os.path.expanduser("~/llama-cuda-b11815")
PORT = 18399
ap = argparse.ArgumentParser()
ap.add_argument("--tag", required=True)
ap.add_argument("--sets", default="B")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--stratified", action="store_true")
ap.add_argument("--phase", default="nt", choices=["nt", "nc", "rt"])
ap.add_argument("--np", type=int, default=4)
A = ap.parse_args()
RUN = "%s/runs/%s" % (D.PAPER, A.tag); os.makedirs(RUN, exist_ok=True)
J = lambda o: json.dumps(o, ensure_ascii=False)


def load_cases():
    sel = RUN + "/cases_selected.json"
    if os.path.exists(sel):
        ids = json.load(open(sel))
    else:
        rows = []
        for n in A.sets.split(","):
            rows += [json.loads(l) for l in open("%s/sets/%s.jsonl" % (D.PAPER, n))]
        if A.stratified and A.limit:
            by = {}
            for r in rows:
                by.setdefault(r.get("stratum") or "x", []).append(r)
            k = max(1, A.limit // len(by)); out = []
            for s in sorted(by):
                out += by[s][:k]
            rows = out
        elif A.limit:
            rows = rows[:A.limit]
        ids = [r["id"] for r in rows]
        json.dump(ids, open(sel, "w"))
    want = set(ids)
    allr = {}
    for n in "ABDF":
        for l in open("%s/sets/%s.jsonl" % (D.PAPER, n)):
            r = json.loads(l)
            if r["id"] in want:
                allr[r["id"]] = r
    return [allr[i] for i in ids]


# ------------------------------------------------------------------ GPU lock
class GpuLock:
    def __enter__(self):
        self.old = open(LOCK).read() if os.path.exists(LOCK) else None
        for _ in range(720):
            used = int(subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]).decode().split()[0])
            live = subprocess.run("pgrep -f '[l]lama-server|[l]lama-(imatrix|quantize|perplexity)|[t]rain' | wc -l", shell=True, capture_output=True, text=True).stdout.strip()
            stale = self.old is None or self.old.startswith("paper_run ") or not self._alive(self.old)
            if used < 800 and live == "0" and stale:
                break
            print(time.strftime("%H:%M:%S"), "waiting for the GPU: used %d MB, procs %s, lock %r" % (used, live, (self.old or "")[:60]), flush=True)
            time.sleep(60)
        else:
            raise SystemExit("GPU never became free")
        open(LOCK, "w").write("paper_run %s pid=%d\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), os.getpid()))
        return self

    @staticmethod
    def _alive(txt):
        m = re.search(r"pid=(\d+)", txt or "")
        return bool(m) and os.path.exists("/proc/%s" % m.group(1))

    def __exit__(self, *a):
        try:
            if open(LOCK).read().startswith("paper_run "):
                if self.old is None:
                    os.remove(LOCK)
                else:
                    open(LOCK, "w").write(self.old)      # leave the previous (stale) content exactly as found
        except FileNotFoundError:
            pass


def gpu_temp():
    try:
        return int(subprocess.check_output(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"]).decode().strip())
    except Exception:
        return None


def cool():
    if (gpu_temp() or 0) >= 75:
        while (gpu_temp() or 0) > 65:
            time.sleep(10)
    time.sleep(1)


# ------------------------------------------------------------------ phase 1: agents
def phase_agents(cases):
    wins = []
    for c in cases:
        a = P.assemble(c)
        for r in P.agent_requests(a):
            wins.append(dict(wid="%s:%s" % (c["id"], r["ref"]), prompt=r["prompt"], role=r["role"]))
    wf, of = RUN + "/agent_in.jsonl", RUN + "/agent_out.jsonl"
    open(wf, "w", newline="\n").write("".join(J(w) + "\n" for w in wins))
    done = {json.loads(l)["id"] for l in open(of)} if os.path.exists(of) else set()
    if len(done) >= len(wins):
        print("agents: all %d done" % len(wins)); return
    env = dict(os.environ, AGT_MODEL=AGT_MODEL, AGT_NP=str(A.np), LD_LIBRARY_PATH=LC + "/bin")
    t0 = time.time()
    with GpuLock():
        # v2_agent_run_gpu.py has its own lock handling: it waits while the lock does not start with its own name -> hand it a lock it recognises
        open(LOCK, "w").write("v2_agent_run_gpu paper_run %s pid=%d\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), os.getpid()))
        r = subprocess.run([sys.executable, Q + "/proofs/2026-11-13_v3_data/rsn/v2_agent_run_gpu.py", wf, of], env=env)
        open(LOCK, "w").write("paper_run done\n")
    json.dump(dict(wall_s=round(time.time() - t0, 1), n_requests=len(wins), np=A.np, rc=r.returncode), open(RUN + "/agent_phase.json", "w"))
    if r.returncode:
        raise SystemExit("agent run failed rc=%d" % r.returncode)


# ------------------------------------------------------------------ retrieval store (phase rt)
import datetime as _dt
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
GAP = 12 * 3600      # a past incident must end >= 12 h before the case end (no shared window / 12 h history)


def store_build():
    """Past-incident store = every frozen-set case (A, B, D, F) as the incident the full path reported for it (runs/full/records.jsonl):
    id = the app-style INC id, title / severity / label = its full-path report, sensors = flagged (non-context) + context nodes, time = window end.
    Outcome (what an operator closed it with), simulated from the gold of the injected / control cases: injected event -> fixed_by_action,
    gold sensor_fault -> sensor_repaired, gold normal -> no_action_needed. Natural cases (A, F-natural) have no gold: left open (Outcome "",
    so Go memoryLines and get_action_history skip them; find_incidents lists them)."""
    sets = {}
    for n in "ABDF":
        for l in open("%s/sets/%s.jsonl" % (D.PAPER, n)):
            r = json.loads(l); sets[r["id"]] = r
    st = []
    for l in open(D.PAPER + "/runs/full/records.jsonl"):
        r = json.loads(l); c = sets[r["id"]]
        rep = r.get("full") or r.get("cheap") or {}
        g = c.get("gold")
        out = ""
        if g:
            out = "sensor_repaired" if g["severity"] == "sensor_fault" else ("no_action_needed" if g["severity"] == "normal" else "fixed_by_action")
        st.append(dict(id="INC-%04d" % (P.case_hash_seed(c["id"]) % 9000 + 100), case=c["id"], end=c["end"], title=rep.get("title") or "",
                       severity=rep.get("severity") or "", label=rep.get("label") or "", outcome=out,
                       nodes=[k.split("/")[0] for k in c["flagged"]],
                       ctx_nodes=[x["key"].split("/")[0] for x in r.get("context_sensors") or []],
                       domains=sorted(set((r.get("triggers") or {}).get("app_domains") or []))))
    st.sort(key=lambda x: x["end"])
    return st


def past(store, case):
    return [p for p in store if p["case"] != case["id"] and p["end"] <= case["end"] - GAP]


def day(t):
    return _dt.datetime.fromtimestamp(t, IST)


def memory_lines(store, case, nodes, n=3):
    out = []
    for p in reversed(past(store, case)):
        if len(out) >= n:
            break
        if not p["outcome"]:
            continue
        hit = ""
        for x in p["nodes"]:
            if x in nodes:
                hit = x
        if hit:
            out.append("%s %s %s on %s, closed: %s" % (day(p["end"]).strftime("%Y-%m-%d"), p["id"], p["title"], hit, p["outcome"]))
    return out


class StoreExec:
    """Go incidentTools.Exec over the store (read-only; newest first; <= 10 items)."""
    def __init__(self, store, case):
        self.p = past(store, case); self.hits = 0

    def run(self, name, args):
        if name == "related_context":
            return {"related": [], "blocks": [], "note": "every related sensor is already in the prompt"}
        if name in ("get_action_history", "find_incidents"):
            node, dom = str(args.get("node") or ""), str(args.get("domain") or "")
            items = []
            for p in reversed(self.p):
                if len(items) >= 10:
                    break
                m = (node == "" and dom == "") or (node and node in p["nodes"] + p["ctx_nodes"]) or (dom and dom in p["domains"])
                if not m:
                    continue
                if name == "get_action_history":
                    if not p["outcome"]:
                        continue
                    items.append({"id": "H%d" % (len(items) + 1), "text": "%s %s: %s, outcome %s" % (day(p["end"]).strftime("%Y-%m-%d"), p["id"], p["title"], p["outcome"])})
                else:
                    items.append({"id": p["id"], "time": day(p["end"]).strftime("%Y-%m-%d %H:%M"), "title": p["title"], "severity": p["severity"], "label": p["label"]})
            self.hits += bool(items)
            return {"items": items, "coverage": {"source": "device", "complete": True}}
        if name == "get_sensor_history":
            return {"summary": [], "note": "no stored readings beyond the incident window", "coverage": {"source": "device", "complete": False}}
        return {"items": [], "note": "no matching incidents"}


# ------------------------------------------------------------------ phase 2: reasoner
def phase_reasoner(cases, mode="full"):
    cases = [c for c in cases if c["set"] == "B"]
    if mode == "nc":      # fixed stratified 60 (20 per N stratum, first 20 ids of each) because of host speed
        by = {}
        for c in sorted(cases, key=lambda c: c["id"]):
            by.setdefault(c["stratum"], []).append(c)
        cases = [c for k in sorted(by) for c in by[k][:20]]
    import rb_local as RB
    _Req = urllib.request.Request
    def _req(url, data=None, *a, **k):
        if data and ("/v1/chat/completions" in url or url.endswith("/apply-template")):
            d = json.loads(data); d.setdefault("chat_template_kwargs", {})["enable_thinking"] = True; data = json.dumps(d).encode()   # think = adaptive (the app's reasoner_think)
        return _Req(url, data, *a, **k)
    urllib.request.Request = _req
    THINKS = []
    _chat = RB.Client.chat
    def chat(self, *a, **k):
        msg, tim, dt_ = _chat(self, *a, **k)
        c = msg.get("content") or ""
        if "</think>" in c and not msg.get("tool_calls"):
            i = c.find("</think>"); th = c[:i].strip(); th = th[len("<think>"):].strip() if th.startswith("<think>") else th
            msg = dict(msg, content=c[i + len("</think>"):].lstrip(), reasoning_content=((msg.get("reasoning_content") or "") + th).strip())
        if (msg.get("reasoning_content") or "").strip():
            THINKS.append(msg["reasoning_content"].strip())
        return msg, tim, dt_
    RB.Client.chat = chat
    tools = json.load(open(TOOLS, encoding="utf-8"))["incident_v4"]
    out = RUN + "/reasoner_abl_%s_out.jsonl" % mode
    done = {json.loads(l)["id"] for l in open(out)} if os.path.exists(out) else set()
    todo = [c for c in cases if c["id"] not in done]
    if not todo:
        print("reasoner: all done"); return
    findings = load_findings()
    sysmsg = P.system_prompt()
    class ToolExec:      # EMPTY frozen corpus: retrieval surface 0 (LEAKAGE.md)
        def run(self, name, args):
            if name == "related_context":
                return {"related": [], "blocks": [], "note": "every related sensor is already in the prompt"}
            if name == "get_action_history":
                return {"items": [], "note": "no past incidents or maintenance recorded for these sensors in the last 90 days"}
            if name == "get_sensor_history":
                return {"summary": [], "note": "no stored readings beyond the incident window", "coverage": {"source": "device", "complete": False}}
            return {"items": [], "note": "no matching incidents"}
    with GpuLock():
        open(LOCK, "w").write("paper_run reasoner %s pid=%d\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), os.getpid()))
        log = open(RUN + "/server_reasoner.log", "a")
        env = dict(os.environ, LD_LIBRARY_PATH=LC + "/bin")
        srv = subprocess.Popen([LC + "/bin/llama-server", "-m", RSN_MODEL, "-ngl", "99", "-cram", "256", "-c", "12288", "-np", "1", "--jinja", "-t", "2", "-tb", "2",
                                "--host", "127.0.0.1", "--port", str(PORT), "--no-webui"], stdout=log, stderr=subprocess.STDOUT, env=env)
        try:
            for _ in range(120):
                try:
                    urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=3); break
                except Exception:
                    time.sleep(3)
            cli = RB.Client(PORT, 1500)
            first = True
            for c in todo:
                a = P.assemble(c)
                if mode == "nc":      # ablation: no context agents (only the flagged sensors reach the reasoner)
                    a["sensors"] = [s for s in a["sensors"] if s["flagged"]]
                tx = ToolExec()
                if mode == "rt":      # retrieval ON: MEMORY from the store (Go memoryLines over every sensor node in the prompt) + store-backed tools
                    c = dict(c, memory=memory_lines(STORE, c, [s["sdef"]["node"] for s in a["sensors"]]))
                    tx = StoreExec(STORE, c)
                fnd = {s["ref"]: findings.get(("%s:%s" % (c["id"], s["ref"])), (None, False)) for s in a["sensors"] if s["flagged"] and s["prompt"]}
                user, sens, ctx = P.render_reasoner(c, a, fnd)
                if False:      # Mode 2-fair: reasoner model + reasoner prompt, raw sensors only: no agent lines, no tools
                    user = chr(10).join(l for l in user.split(chr(10)) if not (l.startswith("  agent") or l.startswith("  - ")))
                cool(); temp = gpu_temp(); del THINKS[:]
                t0 = time.time()
                res = RB.run_loop(cli, tx, sysmsg, [{"role": "user", "content": user}], (None if mode == "nt" else tools), max_tokens=1500)
                rec = dict(id=c["id"], user=user, system_sha=hashlib.md5(sysmsg.encode()).hexdigest(), wall_s=round(time.time() - t0, 2), calls=res["calls"], final=res["final"],
                           turns=res["turns"], think="\n".join(THINKS), start_temp_c=temp, cold=first)
                first = False
                open(out, "a").write(J(rec) + "\n")
        finally:
            srv.terminate()
            try:
                srv.wait(30)
            except subprocess.TimeoutExpired:
                srv.kill()
            log.close()
            open(LOCK, "w").write("paper_run done\n")


def load_findings():
    f = {}
    p = RUN + "/agent_out.jsonl"
    if os.path.exists(p):
        wins = {json.loads(l)["wid"]: json.loads(l) for l in open(RUN + "/agent_in.jsonl")}
        for l in open(p):
            o = json.loads(l)
            role = wins[o["id"]]["role"] if o["id"] in wins else ""
            f[o["id"]] = C.agent_finding(o["text"], role)
    return f


# ------------------------------------------------------------------ phase 3: merge
LABELS = P.REPORT_LABELS
SEVS = {"normal", "warning", "critical", "sensor_fault"}


def parse_report(txt):
    t = (txt or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    try:
        o = json.loads(t)
        return o if isinstance(o, dict) else None
    except Exception:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except Exception:
                return None
    return None


def triggers(c, a, fnd, host):
    fl = [s for s in a["sensors"] if s["flagged"]]
    ctxs = [s for s in a["sensors"] if not s["flagged"]]
    def fin(s):
        f, ok = fnd.get(s["ref"], (None, False))
        return f if (f is not None and ok) else s["rule"]
    roles_flag = sorted({s["sdef"]["role"] for s in fl})
    app_doms = sorted({s["sdef"]["role"] for s in fl} | {s["sdef"]["role"] for s in ctxs if C.informative(fin(s))})
    agt = [(s, fnd.get(s["ref"], (None, False))) for s in fl if s["prompt"]]
    valid = [(s, f) for s, (f, ok) in agt if f is not None and ok]
    dis = [s["ref"] for s, f in valid if f["status"] != s["rule"]["status"]]
    dis_norm = [s["ref"] for s, f in valid if f["status"] == "normal" and C.SEV[s["rule"]["status"]] > 0]
    confs = [f["confidence"] for s, f in valid]
    dq = [((f.get("data_quality") or {}).get("verdict")) for s, f in valid]
    # site-tree links between flagged sensors: shared room / floor / building / link line entries
    P_ = P.place_env(c["id"]); ix = P_.ix
    def anc(node):
        h = P_.host.get(node)
        return [h] + ix.ancestors(h) if h else []
    rel = []
    for i in range(len(fl)):
        for j in range(i + 1, len(fl)):
            A_, B_ = anc(fl[i]["sdef"]["node"]), anc(fl[j]["sdef"]["node"])
            sh = [x for x in A_ if x in B_]
            kind = next((ix.nodes[x]["kind"] for x in sh if ix.nodes[x]["kind"] in ("room", "floor", "building")), None)
            lk = P_.link_of(fl[i]["sdef"]["node"], fl[i]["sdef"]["metric"], fl[j]["sdef"]["node"], fl[j]["sdef"]["metric"])
            if kind or lk:
                rel.append(dict(a=fl[i]["ref"], b=fl[j]["ref"], shared=kind, link=lk))
    return dict(n_domains_flagged=len(roles_flag), flagged_domains=roles_flag, n_flagged_sensors=len(fl), n_domains_app=len(app_doms), app_domains=app_doms,
                app_would_escalate=len(app_doms) >= 2,
                any_critical_rule=any(s["rule"]["status"] == "critical" for s in fl), any_critical_agent=any(f["status"] == "critical" for s, f in valid),
                any_critical=any(s["rule"]["status"] == "critical" for s in fl) or any(f["status"] == "critical" for s, f in valid),
                rule_agent_disagree=bool(dis), disagree_refs=dis, agent_normal_rule_flagged=bool(dis_norm), n_agents=len(agt), n_agents_valid=len(valid),
                agent_min_conf=min(confs) if confs else None, agent_low_conf=any(x < 0.6 for x in confs), agent_dq=dq, agent_asked_more=any(x == "insufficient" for x in dq),
                agent_invalid=len(agt) - len(valid), site_links=rel, site_linked=bool(rel))


def phase_merge(cases):
    findings = load_findings()
    agent_out = {}
    if os.path.exists(RUN + "/agent_out.jsonl"):
        for l in open(RUN + "/agent_out.jsonl"):
            o = json.loads(l); agent_out[o["id"]] = o
    rout = {}
    if os.path.exists(RUN + "/reasoner_out.jsonl"):
        for l in open(RUN + "/reasoner_out.jsonl"):
            o = json.loads(l); rout[o["id"]] = o
    eout = {}
    if os.path.exists(RUN + "/reasoner_e_out.jsonl"):
        for l in open(RUN + "/reasoner_e_out.jsonl"):
            o = json.loads(l); eout[o["id"]] = o
    ph = json.load(open(RUN + "/agent_phase.json")) if os.path.exists(RUN + "/agent_phase.json") else {}
    recs = []
    for c in cases:
        a = P.assemble(c)
        fnd = {s["ref"]: findings.get("%s:%s" % (c["id"], s["ref"]), (None, False)) for s in a["sensors"] if s["flagged"] and s["prompt"]}
        P_ = P.place_env(c["id"])
        sens, calls = [], []
        for s in a["sensors"]:
            sd = s["sdef"]
            sens.append(dict(ref=s["ref"], role=sd["role"], metric=sd["metric"], node=sd["node"], loc=P_.loc(P_.host.get(sd["node"], P_.room)), context=not s["flagged"], rule=s["rule"]))
            if s["flagged"] and s["prompt"]:
                calls.append(fnd.get(s["ref"], (None, False)))
            elif s["flagged"]:
                calls.append((None, False))          # hvac flagged: no LLM agent, rule finding
            else:
                calls.append((s["rule"], True))      # context agents are deterministic and valid
        cheap = P.isolated_report(sens, calls)
        cheap_x = P.fallback_report(sens, calls)
        r = rout.get(c["id"])
        full = None; raw = None; fb = False; valid = False
        if r:
            raw = (r["final"] or {}).get("content") if r.get("final") else None
            full = parse_report(raw)
            valid = bool(full) and full.get("label") in LABELS and full.get("severity") in SEVS
            if not valid:
                fb = True
        agents = []
        for s in a["sensors"]:
            if s["flagged"] and s["prompt"]:
                o = agent_out.get("%s:%s" % (c["id"], s["ref"]), {})
                agents.append(dict(ref=s["ref"], key=s["sdef"]["key"], prompt=s["prompt"], text=o.get("text"), finding=fnd[s["ref"]][0], valid=fnd[s["ref"]][1], tokens=o.get("tokens"),
                                   prompt_ms=o.get("prompt_ms"), predicted_ms=o.get("predicted_ms"), wall_s=o.get("wall_s"), rule=s["rule"]))
        tr = triggers(c, a, fnd, None)
        turns = (r or {}).get("turns") or []
        rec = dict(id=c["id"], set=c["set"], kind=c["kind"], family=c["family"], stratum=c.get("stratum"), end=c["end"], end_ist=c["end_ist"], gold=c.get("gold"),
                   mode="full+cheap (one run, cheap arm offline)", n_domains=tr["n_domains_flagged"], n_flagged_sensors=tr["n_flagged_sensors"], triggers=tr, agents=agents,
                   context_sensors=[dict(ref=s["ref"], key=s["sdef"]["key"], why=s["why"], rule=s["rule"]) for s in a["sensors"] if not s["flagged"]],
                   reasoner=dict(user=(r or {}).get("user"), raw=raw, report=full, valid=valid, fallback_fired=fb, think=(r or {}).get("think"), think_on=bool((r or {}).get("think")),
                                 tool_calls=[dict(name=x["name"], args=x["args"], result=x["result"]) for x in (r or {}).get("calls", [])],
                                 turns=turns, prefill_tokens=sum(t.get("prompt_n") or 0 for t in turns), decode_tokens=sum(t.get("predicted_n") or 0 for t in turns),
                                 prefill_ms=sum(t.get("prompt_ms") or 0 for t in turns), decode_ms=sum(t.get("predicted_ms") or 0 for t in turns), wall_s=(r or {}).get("wall_s"),
                                 start_temp_c=(r or {}).get("start_temp_c"), cold=(r or {}).get("cold"), swap_ms=None, retries=0),
                   short_circuit_fired=not tr["app_would_escalate"], retrieval_hits=sum(1 for x in (r or {}).get("calls", []) if x["name"] in ("find_incidents", "get_action_history") and x["result"].get("items")),
                   gate_rejections=0, cheap=cheap, cheap_x=cheap_x,
                   full=(full if valid else (cheap_x if r else None)),
                   agents_wall_s_total=round(sum((x.get("wall_s") or 0) for x in agents), 2),
                   agent_phase=dict(np=ph.get("np"), phase_wall_s=ph.get("wall_s"), n_requests=ph.get("n_requests")))
        e = eout.get(c["id"])
        if e:
            ep = parse_report((e["final"] or {}).get("content"))
            rec["mode2fair"] = dict(report=ep, valid=bool(ep) and ep.get("label") in LABELS and ep.get("severity") in SEVS, wall_s=e["wall_s"],
                                    prefill_tokens=sum(t.get("prompt_n") or 0 for t in e["turns"]), decode_tokens=sum(t.get("predicted_n") or 0 for t in e["turns"]), think_on=bool(e["think"]))
        recs.append(rec)
    open(RUN + "/records.jsonl", "w", newline="\n").write("".join(J(r) + "\n" for r in recs))
    print("merged", len(recs), "records ->", RUN + "/records.jsonl")


STORE = None


def main():
    global STORE
    if A.phase == "rt":
        STORE = store_build()
        json.dump(STORE, open(RUN + "/retrieval_store.json", "w"), indent=0)
    cases = load_cases()
    print("cases:", len(cases), flush=True)
    phase_reasoner(cases, A.phase)


if __name__ == "__main__":
    main()
