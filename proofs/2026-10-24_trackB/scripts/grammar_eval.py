"""Grammar-constrained vs unconstrained decoding of the v2 GGUF on the host CPU llama-server (620d222 = htpd's ggml),
same request as host_eval_v2.gen_gguf (prefill, greedy, stop at "action"), per row: free then grammar (2nd hits the
prompt cache, so its prompt_ms ~ 0 and predicted_ms is the decode cost). Resumable; raw lines -> OUT/raw/grammar_runs.jsonl

  python grammar_eval.py pick  [--n-test 72 --n-rw5 36]      -> OUT/raw/grammar_sample.json
  python grammar_eval.py run   [--threads 4] [--limit N]
  python grammar_eval.py report                              -> short summary + OUT/grammar_tables.md
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import trackb_lib as L
import common_v2 as C
import gbnf_v2

OUT = Path(__file__).resolve().parent.parent
RAW = OUT / "raw"
SAMPLE = RAW / "grammar_sample.json"
RUNS = RAW / "grammar_runs.jsonl"
LLAMA = Path.home() / "gpu_work/llama.cpp/build-host/bin/llama-server"
MODEL = Path.home() / "smartcity_runs/agents_v2/post/gguf/ft_v2_q4_0.gguf"
BOS = "<|begin_of_text|>"


def cmd_pick(a):
    rng = random.Random(2410)
    pick = []
    test = L.load("test")
    # weak slices first (power, unseen, 1.5 h, water cause), then fill from ALL; one row per id
    want = [("role_power", 18), ("seen_unseen_sepoct", 12), ("stage_1.5h", 12), ("water_cause", 6), ("erratic", 6),
            ("calm_or_routine", 8), ("ALL", a.n_test)]
    ids = set()
    for sl, k in want:
        pool = [r for r, s in test if sl in s["slices"] and r["id"] not in ids]
        rng.shuffle(pool)
        for r in pool[:max(0, min(k, a.n_test - len(ids)))]:
            ids.add(r["id"]); pick.append(("test", r["id"]))
    rw = L.load("rw5test")
    for sl, k in (("rw5_acidic", 6), ("rw5_glitch", 6), ("rw5_chatter", 6), ("rw5_co2_floor", 6), ("rw5_gap_recovery", 6),
                  ("rw5_holiday", 6)):
        pool = [r for r, s in rw if sl in s["slices"]]
        rng.shuffle(pool)
        pick += [("rw5test", r["id"]) for r in pool[:k]]
    pick += [("dev", s["id"]) for r, s in L.load("dev") if not s["policy"]]   # the 3 host off-label answers
    SAMPLE.parent.mkdir(exist_ok=True)
    SAMPLE.write_text(json.dumps(pick))
    print(len(pick), Counter(d for d, _ in pick))


def post(url, body, timeout=600):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return json.loads(f.read().decode("utf-8", errors="replace"))


def cmd_run(a):
    pick = json.loads(SAMPLE.read_text())
    rows = {}
    for ds in {d for d, _ in pick}:
        for r, s in L.load(ds):
            rows[(ds, r["id"])] = r
    done = set()
    if RUNS.exists():
        for l in open(RUNS):
            x = json.loads(l); done.add((x["set"], x["id"], x["mode"]))
    G = gbnf_v2.all_grammars()
    port = 18190
    log = open(RAW / "grammar_server.log", "a")
    args = [str(LLAMA), "-m", str(MODEL), "-t", str(a.threads), "-tb", str(a.threads), "-c", "2048", "-np", "1",
            "--port", str(port), "--host", "127.0.0.1", "-ngl", "0", "-fa", "auto", "--temp", "0"]
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(300):
            try:
                with urllib.request.urlopen(base + "/health", timeout=5) as f:
                    if json.loads(f.read()).get("status") == "ok":
                        break
            except Exception:  # noqa: BLE001
                pass
            if proc.poll() is not None:
                raise SystemExit("server exited")
            time.sleep(1)
        fh = open(RUNS, "a")
        k = 0
        for ds, i in pick:
            r = rows[(ds, i)]
            p = r["prompt"][len(BOS):] if r["prompt"].startswith(BOS) else r["prompt"]
            for mode in ("free", "grammar"):
                if (ds, i, mode) in done:
                    continue
                body = {"prompt": p + C.PREFILL, "n_predict": 160, "temperature": 0, "top_k": 1, "cache_prompt": True,
                        "stop": ['"action"', "<|eot_id|>"]}
                if mode == "grammar":
                    body["grammar"] = G[r["role"]]
                t0 = time.time()
                res = post(base + "/completion", body)
                text = C.PREFILL + res.get("content", "")
                if res.get("stop_type") == "word" and res.get("stopping_word") == '"action"':
                    text += '"action"'
                tm = res.get("timings", {})
                sc = C.score_one(r, text)
                fh.write(json.dumps({"set": ds, "id": i, "mode": mode, "role": r["role"], "text": text,
                                     "tokens": res.get("tokens_predicted"), "prompt_ms": tm.get("prompt_ms"),
                                     "predicted_ms": tm.get("predicted_ms"), "prompt_n": tm.get("prompt_n"),
                                     "wall_s": round(time.time() - t0, 2), "score": sc}, default=str) + "\n")
                fh.flush()
            k += 1
            if a.limit and k >= a.limit:
                break
            if k % 10 == 0:
                print(f"{k}/{len(pick)}", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            proc.kill()


def cmd_report(a):
    runs = defaultdict(dict)
    for l in open(RUNS):
        x = json.loads(l)
        runs[(x["set"], x["id"])][x["mode"]] = x
    both = {k: v for k, v in runs.items() if "free" in v and "grammar" in v}
    stored = {}
    for ds in {d for d, _ in both}:
        for r, s in L.load(ds):
            stored[(ds, r["id"])] = s
    keys = ("json", "policy", "pattern", "status", "cause", "fault_kind", "event_active", "onset_15", "evidence")
    md = ["# Grammar-constrained decoding: host CPU llama-server 620d222, v2 Q4_0, greedy (generated by grammar_eval.py report)", "",
          f"Rows: {len(both)} (each decoded free and with the role grammar).", "",
          "| metric | free | grammar | W/L (grammar vs free) |", "|---|---|---|---|"]
    for k in keys:
        pr = [(v["free"]["score"].get(k), v["grammar"]["score"].get(k)) for v in both.values()]
        pr = [(bool(x), bool(y)) for x, y in pr if x is not None and y is not None]
        if not pr:
            continue
        n = len(pr)
        md.append(f"| {k} | {sum(x for x, _ in pr)}/{n} ({100*sum(x for x, _ in pr)/n:.1f}) | {sum(y for _, y in pr)}/{n} "
                  f"({100*sum(y for _, y in pr)/n:.1f}) | {sum(1 for x, y in pr if y and not x)}/{sum(1 for x, y in pr if x and not y)} |")
    same = sum(1 for v in both.values() if v["free"]["text"] == v["grammar"]["text"])
    fid = sum(1 for k, v in both.items() if k in stored and v["free"]["text"] == stored[k]["text"])
    tf = sum(v["free"]["tokens"] for v in both.values()); tg = sum(v["grammar"]["tokens"] for v in both.values())
    mf = sum(v["free"]["predicted_ms"] for v in both.values()); mg = sum(v["grammar"]["predicted_ms"] for v in both.values())
    md += ["", f"- identical text free vs grammar: {same}/{len(both)}",
           f"- CPU free text identical to the stored CUDA v2cuda text: {fid}/{len(both)}",
           f"- decode: free {mf/tf:.1f} ms/token ({tf} tokens), grammar {mg/tg:.1f} ms/token ({tg} tokens); "
           f"grammar overhead {100*(mg/tg)/(mf/tf)-100:+.1f}% per token",
           f"- wall per answer (decode only): free {mf/len(both)/1000:.2f} s, grammar {mg/len(both)/1000:.2f} s", ""]
    diff = [(k, v) for k, v in both.items() if v["free"]["text"] != v["grammar"]["text"]]
    md += ["## Rows where the grammar changed the answer", "", "| set | id | free (pattern/status/cause) | grammar | gold |", "|---|---|---|---|---|"]
    for (ds, i), v in diff:
        f, g = v["free"]["score"], v["grammar"]["score"]
        pf = (f.get("pred") or {}); pg = (g.get("pred") or {})
        md.append(f"| {ds} | {i} | {pf.get('pattern')}/{pf.get('status')}/{pf.get('likely_cause')} json={f['json']} | "
                  f"{pg.get('pattern')}/{pg.get('status')}/{pg.get('likely_cause')} | {f['gold_pattern']}/{f['gold_status']} |")
    (OUT / "grammar_tables.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:20]))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick"); p.add_argument("--n-test", type=int, default=72)
    r = sub.add_parser("run"); r.add_argument("--threads", type=int, default=4); r.add_argument("--limit", type=int, default=0)
    sub.add_parser("report")
    a = ap.parse_args()
    {"pick": cmd_pick, "run": cmd_run, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
