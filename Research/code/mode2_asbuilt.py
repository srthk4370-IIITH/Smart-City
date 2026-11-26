"""mode2_asbuilt.py (item 3): Mode 2 AS BUILT = the NPU agent model (agt3_s0450_q4_0, Llama-3 template) + the app's singlePrompt (reason.go: reasonerSystem + SENSORS block with the rule view and evidence
lines, ReportPrefill), one call per incident, on Set B + D (218 cases). Python port of singlePrompt/sensorBlock from the real prompt builders (render_reasoner's sensor dicts); the report has NO
severity key in this mode, so severity = ruleSeverity (worst rule status of the flagged sensors; the Go reasonerSeverity guard is not ported). Policy gate approximated: label must be in ReportLabels,
JSON must parse, else fallbackReport from rule findings (as Go does). Host Q4_0 on the laptop GPU, greedy. Output runs/full/mode2_asbuilt.jsonl; run once, resumable.
  python mode2_asbuilt.py [--limit N]"""
import json, os, re, subprocess, sys, time, urllib.request, hashlib
import env_setup as ES
import pdata as D, pcase as P, pcore as C
from env_setup import Q

LOCK = Q + "/proofs/2026-10-29_rsn_v3/GPU_LOCK"
AGT = os.path.expanduser("~/smartcity_runs/agt_topup_k2b/post/s0450/agt3_s0450_q4_0.gguf")
LC = os.path.expanduser("~/llama-cuda-b11815"); PORT = 18397
OUT = D.PAPER + "/runs/full/mode2_asbuilt.jsonl"
LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
SEVR = {"normal": 0, "warning": 1, "critical": 2, "sensor_fault": 3}
LABELS = P.REPORT_LABELS
J = lambda o: json.dumps(o, ensure_ascii=False)


def go_const():
    t = open(Q + "/Code/smart-city-edge-agent/app/backend/reason.go", encoding="utf-8").read()
    i = t.index("const reasonerSystem ="); j = t.index("\n\n", i)
    parts = re.findall(r'`([^`]*)`|"((?:[^"\\]|\\.)*)"', t[i + len("const reasonerSystem ="):j])
    return "".join(a if a else b for a, b in parts)


SYS = go_const().replace("%s", "|".join(LABELS), 1)
assert "JSON keys:" in SYS and "Format:" in SYS


def informative(f):
    return C.informative(f)


def single_prompt(sens):
    b = ["SENSORS (4-hour windows, 5-min samples). FLAGGED = anomaly detected; related = context from causally linked domains:\n"]
    for d in sens:
        tag = "FLAGGED" if d["flagged"] else "related: " + (d["why"] or "")
        b.append("%s [%s]: %s %s at %s (%s), rule view pattern=%s status=%s\n" % (d["ref"], tag, d["node"], d["metric"], d["loc"], d["role"], d["rule"][0], d["rule"][1]))
        n = len(d["ev"]) if d["flagged"] else (3 if informative(d["rulef"]) else 1)
        for e in d["ev"][:n]:
            b.append("%s.%s %s\n" % (d["ref"], e[0], e[1]))
    b.append("Find the cross-domain root cause.")
    return "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n" + SYS + "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n" + "".join(b) + "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"


def build(c):
    a = P.assemble(c)
    user, sens, ctx = P.render_reasoner(c, a, {})
    for d, s in zip(sens, a["sensors"]):
        d["rulef"] = s["rule"]
    return a, sens, single_prompt(sens)


def main():
    cases = []
    for n in "BD":
        cases += [json.loads(l) for l in open("%s/sets/%s.jsonl" % (D.PAPER, n))]
    if LIMIT:
        cases = cases[:LIMIT]
    done = {json.loads(l)["id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [c for c in cases if c["id"] not in done]
    print("todo", len(todo), flush=True)
    if not todo:
        return
    old = open(LOCK).read() if os.path.exists(LOCK) else None
    for _ in range(720):
        used = int(subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]).decode().split()[0])
        live = subprocess.run("pgrep -f '[l]lama-server|[l]lama-(imatrix|quantize|perplexity)|[t]rain' | wc -l", shell=True, capture_output=True, text=True).stdout.strip()
        if used < 800 and live == "0":
            break
        time.sleep(60)
    open(LOCK, "w").write("paper_run mode2_asbuilt %s pid=%d\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), os.getpid()))
    env = dict(os.environ, LD_LIBRARY_PATH=LC + "/bin")
    log = open(D.PAPER + "/runs/full/server_mode2.log", "a")
    srv = subprocess.Popen(["nice", LC + "/bin/llama-server", "-m", AGT, "-ngl", "99", "-c", "8192", "-np", "1", "-t", "2", "-tb", "2", "--host", "127.0.0.1", "--port", str(PORT), "--no-webui"],
                           stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=3); break
            except Exception:
                time.sleep(3)
        prefill = '{"root_cause": "'
        for c in todo:
            a, sens, prompt = build(c)
            body = json.dumps(dict(prompt=prompt + prefill, n_predict=320, temperature=0, cache_prompt=True, stop=["<|eot_id|>"])).encode()
            t0 = time.time()
            r = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/completion" % PORT, body, {"Content-Type": "application/json"}), timeout=300))
            txt = prefill + r["content"]
            tm = r.get("timings", {})
            open(OUT, "a").write(J(dict(id=c["id"], prompt_tokens=r.get("tokens_evaluated"), text=txt, wall_s=round(time.time() - t0, 2), prompt_ms=tm.get("prompt_ms"), predicted_ms=tm.get("predicted_ms"),
                                       predicted_n=tm.get("predicted_n"), prompt_sha=hashlib.md5(prompt.encode()).hexdigest())) + "\n")
    finally:
        srv.terminate()
        try:
            srv.wait(30)
        except subprocess.TimeoutExpired:
            srv.kill()
        if old is not None:
            open(LOCK, "w").write(old)
        else:
            try:
                os.remove(LOCK)
            except OSError:
                pass


if __name__ == "__main__":
    main()
