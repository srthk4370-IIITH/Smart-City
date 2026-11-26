"""judge.py (item 6): root-cause text judge on Set B (n=153) by a LOCAL model that is NOT the reasoner under test: the untuned Qwen3.5-4B (q8_0, ~/models/qwen3.5-4b-gguf), thinking off, greedy.
Candidates (full / Mode 2-fair / cheap + a mismatched decoy = another case's full report with a different gold label) are scored ONE AT A TIME, anonymised (no arm name, no mode, no severity/label fields; only root_cause + causal_chain + explanation),
in shuffled order. The judge sees the gold scenario (label, affected domains, severity) in plain words and rates 0 (wrong cause) / 1 (partly right) / 2 (names the true cause and the involved domains).
Caveats written to RESULTS.md: 4B judge, same model family as the base of the reasoner, gold = injection story label, not free-text gold. Output results/judge.json + runs/full/judge_out.jsonl (resumable)."""
import json, os, random, re, subprocess, sys, time, urllib.request
import numpy as np
from scipy.stats import wilcoxon
Q = "/mnt/c/Users/hp/Desktop/qidk"; P = Q + "/proofs/2026-11-26_paper"; OUT = P + "/runs/full/judge_out.jsonl"
JM = os.path.expanduser("~/models/qwen3.5-4b-gguf/qwen3.5-4b-q8_0.gguf"); LC = os.path.expanduser("~/llama-cuda-b11815"); PORT = 18395; LOCK = Q + "/proofs/2026-10-29_rsn_v3/GPU_LOCK"
R = random.Random(2611); RNG = np.random.default_rng(3)
recs = [json.loads(l) for l in open(P + "/runs/full/records.jsonl")]
B = [r for r in recs if r["set"] == "B"]
WORD = {"hvac_or_thermal_issue": "an HVAC or thermal problem", "ventilation_issue": "a ventilation problem", "occupancy_driven_load": "occupancy-driven load", "air_pollution_event": "an air pollution event",
        "water_leak_or_overuse": "a water leak or overuse", "water_supply_issue": "a water supply problem", "water_quality_issue": "a water quality problem", "power_load_anomaly": "a power load anomaly",
        "power_quality_issue": "a power quality problem", "weather_driven": "a weather-driven effect", "sensor_fault": "a faulty sensor", "normal_operation": "normal operation", "unknown": "unknown"}
DOM = {"air_quality": "air quality", "hvac": "HVAC", "power": "power", "water": "water", "weather": "weather", "occupancy": "occupancy"}


def text(x):
    if not x: return ""
    return " ".join(str(x.get(k) or "") for k in ("root_cause", "causal_chain", "explanation")).strip()


items = []
for r in B:
    g = r["gold"]; cands = {"full": text(r["full"]), "cheap": text(r["cheap"])}
    if r.get("mode2fair") and r["mode2fair"].get("report"): cands["m2"] = text(r["mode2fair"]["report"])
    other = R.choice([o for o in B if o["gold"]["label"] != g["label"]]); cands["decoy"] = text(other["full"])
    for arm, t in cands.items():
        if t: items.append(dict(id=r["id"], arm=arm, text=t, gold=g))
R.shuffle(items)
for i, it in enumerate(items): it["cid"] = "c%04d" % i
PROMPT = ("You grade an incident explanation written for a campus operator.\nTRUE SCENARIO: the real cause is %s; the domains involved are: %s; the severity is %s.\n"
          "EXPLANATION TO GRADE:\n%s\n\nScore 2 if it names the true cause (in any wording) and the involved domains; 1 if it is partly right (right cause but misses domains, or right domains with a vague or partly wrong cause); "
          "0 if it names a different cause or is empty. Reply with only a JSON object like {\"score\": 0}.")


def serve():
    env = dict(os.environ, LD_LIBRARY_PATH=LC + "/bin")
    old = open(LOCK).read() if os.path.exists(LOCK) else None
    for _ in range(720):
        used = int(subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]).decode().split()[0])
        live = subprocess.run("pgrep -f '[l]lama-server|[l]lama-(imatrix|quantize|perplexity)|[t]rain' | wc -l", shell=True, capture_output=True, text=True).stdout.strip()
        if used < 800 and live == "0": break
        time.sleep(60)
    open(LOCK, "w").write("paper_run judge %s pid=%d\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), os.getpid()))
    p = subprocess.Popen(["nice", LC + "/bin/llama-server", "-m", JM, "-ngl", "99", "-c", "4096", "-np", "1", "-t", "2", "-tb", "2", "--jinja", "--host", "127.0.0.1", "--port", str(PORT), "--no-webui"],
                         stdout=open(P + "/runs/full/server_judge.log", "a"), stderr=subprocess.STDOUT, env=env)
    for _ in range(120):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=3); break
        except Exception:
            time.sleep(3)
    return p, old


def ask(prompt):
    body = json.dumps(dict(messages=[{"role": "user", "content": prompt}], temperature=0, max_tokens=24, chat_template_kwargs={"enable_thinking": False})).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT, body, {"Content-Type": "application/json"}), timeout=120))
    return r["choices"][0]["message"]["content"]


def main():
    done = {json.loads(l)["cid"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [i for i in items if i["cid"] not in done]
    print("items", len(items), "todo", len(todo), flush=True)
    if todo:
        p, old = serve()
        try:
            for it in todo:
                g = it["gold"]
                out = ask(PROMPT % (WORD.get(g["label"], g["label"]), ", ".join(DOM.get(d, d) for d in g["affected_domains"]) or "none", g["severity"], it["text"]))
                m = re.search(r'"?score"?\s*:\s*([012])', out)
                open(OUT, "a").write(json.dumps(dict(cid=it["cid"], id=it["id"], arm=it["arm"], score=int(m.group(1)) if m else None, raw=out)) + "\n")
        finally:
            p.terminate(); p.wait(30)
            if old is not None: open(LOCK, "w").write(old)
            else:
                try: os.remove(LOCK)
                except OSError: pass
    rows = [json.loads(l) for l in open(OUT)]
    S = {}
    for arm in ("full", "m2", "cheap", "decoy"):
        v = [r["score"] for r in rows if r["arm"] == arm and r["score"] is not None]
        if not v: continue
        bs = [np.mean(RNG.choice(v, len(v))) for _ in range(1000)]
        S[arm] = dict(n=len(v), mean=round(float(np.mean(v)), 3), ci=[round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)], pct2=round(100 * float(np.mean([x == 2 for x in v])), 1),
                      pct0=round(100 * float(np.mean([x == 0 for x in v])), 1), unparsed=sum(1 for r in rows if r["arm"] == arm and r["score"] is None))
    by = {(r["id"], r["arm"]): r["score"] for r in rows}
    W = {}
    for a, b in (("full", "m2"), ("full", "cheap"), ("m2", "cheap")):
        ids = [i for i in {r["id"] for r in rows} if by.get((i, a)) is not None and by.get((i, b)) is not None]
        x = [by[(i, a)] for i in ids]; y = [by[(i, b)] for i in ids]
        try: pv = float(wilcoxon(x, y).pvalue)
        except Exception: pv = None
        W["%s_vs_%s" % (a, b)] = dict(n=len(ids), mean_diff=round(float(np.mean(np.array(x) - np.array(y))), 3), p=pv)
    # agreement of the judge with gold labels: share of exact-label full reports scored 2 vs wrong-label scored 2
    lab = {r["id"]: r for r in B}
    ok = [by.get((i, "full")) for i in lab if lab[i]["full"] and lab[i]["full"].get("label") == lab[i]["gold"]["label"] and by.get((i, "full")) is not None]
    bad = [by.get((i, "full")) for i in lab if lab[i]["full"] and lab[i]["full"].get("label") != lab[i]["gold"]["label"] and by.get((i, "full")) is not None]
    json.dump(dict(scores=S, wilcoxon=W, sanity=dict(full_label_correct_mean=round(float(np.mean(ok)), 3), n_ok=len(ok), full_label_wrong_mean=round(float(np.mean(bad)), 3) if bad else None, n_bad=len(bad))),
              open(P + "/results/judge.json", "w"), indent=1)
    print(open(P + "/results/judge.json").read())


if __name__ == "__main__":
    main()
