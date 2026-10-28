"""Host (laptop) accuracy of the merged v2 agent, and the quantisation loss of the GGUF candidates.

The eval set is a stratified ~400 rows of data/sft_v2/test.jsonl (test months Nov-Dec, incl. the held-out
"unseen" sensors), picked once by common_v2.select_rows and frozen in <post>/eval_set.json so every backend
(and the QIDK, device_eval_v2/) answers exactly the same prompts. Every backend gets the device prompt +
the JSON prefill '{"pattern": "', greedy decoding, and the app's stop rule (cut where "action" starts).

Backends
  hf     the merged HF model on the laptop GPU. --load bf16 (default) keeps the weights in bf16: what does not
         fit the 6 GB GPU is offloaded to the CPU by accelerate (slow but exact); --load int8 / nf4 for speed.
  gguf   a GGUF through llama-server (CPU build of ~/gpu_work/llama.cpp, the same ggml graph as htpd), N
         parallel slots; the leading <|begin_of_text|> text is dropped because the server adds BOS itself
         (checked once via /tokenize: exactly one BOS, identical tokens to htpd's parse_special tokenisation).

  python host_eval_v2.py select  --post P                         # writes P/eval_set.json (once)
  python host_eval_v2.py run     --post P --backend hf   --model MERGED_DIR --tag hf_bf16
  python host_eval_v2.py run     --post P --backend gguf --model X.gguf     --tag gguf_q4_0
  python host_eval_v2.py compare --post P --ref hf_bf16 --cand gguf_q4_0 gguf_q4_k_m
Outputs: P/eval/<tag>/{samples.jsonl, summary.json, tables.md}; compare -> P/eval/quant_loss.{json,md}.
Runs are resumable (rows already in samples.jsonl are skipped).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common_v2 as C  # noqa: E402

BOS_TEXT = "<|begin_of_text|>"
LLAMA = Path(os.environ.get("LLAMA_CPP", str(Path.home() / "gpu_work" / "llama.cpp")))


def load_eval_set(post):
    ids = json.loads((post / "eval_set.json").read_text())["ids"]
    by = {r["id"]: r for r in C.read_jsonl(C.DATA / "test.jsonl")}
    return [by[i] for i in ids]


def cmd_select(a):
    post = Path(a.post)
    post.mkdir(parents=True, exist_ok=True)
    p = post / "eval_set.json"
    if p.exists() and not a.force:
        print("eval set exists:", p)
        return
    rows = C.read_jsonl(C.DATA / "test.jsonl")
    pick = C.select_rows(rows, a.n, a.seed)
    from collections import Counter
    man = {"n": len(pick), "seed": a.seed, "source": "data/sft_v2/test.jsonl",
           "by_role": Counter(r["role"] for r in pick), "by_seen": Counter(r.get("seen") for r in pick),
           "by_role_seen": Counter(f"{r['role']}/{r.get('seen')}" for r in pick),
           "by_family": Counter(r.get("family") for r in pick), "by_age": Counter(C._age(r.get("d")) for r in pick),
           "by_window": Counter(C.win_bucket(r) for r in pick), "negatives": sum(C.is_negative(r) for r in pick),
           "sensor_fault": sum(C.gold_of(r)["status"] == "sensor_fault" for r in pick),
           "ids": [r["id"] for r in pick]}
    p.write_text(json.dumps(man, indent=1))
    print(json.dumps({k: v for k, v in man.items() if k != "ids"}, indent=1))


# ------------------------------------------------------------------ backends
def gen_hf(rows, a, done_cb):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    tok = AutoTokenizer.from_pretrained(a.model, local_files_only=True)
    tok.pad_token = "<|finetune_right_pad_id|>"
    tok.padding_side = "left"
    kw = dict(local_files_only=True, torch_dtype=torch.bfloat16, attn_implementation="sdpa")
    if a.load == "bf16":
        kw.update(device_map="auto", max_memory={0: a.gpu_mem, "cpu": "10GiB"})
    elif a.load == "int8":
        kw.update(device_map={"": 0}, quantization_config=BitsAndBytesConfig(load_in_8bit=True))
    else:
        kw.update(device_map={"": 0}, quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16))
    model = AutoModelForCausalLM.from_pretrained(a.model, **kw)
    model.eval()
    print("hf device map:", sorted(set(map(str, getattr(model, "hf_device_map", {"": "cuda:0"}).values()))), flush=True)
    rows = sorted(rows, key=lambda r: len(r["prompt"]))   # less padding per batch
    dev = "cuda"
    for i in range(0, len(rows), a.bs):
        chunk = rows[i:i + a.bs]
        t = gpu_temp()
        if t is not None and t >= a.hot:   # the laptop thermal-slept at 81 C once (HANDBOOK 2.40)
            print(f"GPU {t} C: pausing until {a.cool} C", flush=True)
            while (gpu_temp() or 0) > a.cool:
                time.sleep(10)
        enc = tok([r["prompt"] + C.PREFILL for r in chunk], add_special_tokens=False, return_tensors="pt",
                  padding=True).to(dev)
        t0 = time.time()
        with torch.no_grad():
            g = model.generate(**enc, max_new_tokens=a.max_new, do_sample=False, temperature=None, top_p=None,
                               eos_token_id=[128001, 128008, 128009], pad_token_id=tok.pad_token_id)
        dt = time.time() - t0
        for j, r in enumerate(chunk):
            new = g[j, enc["input_ids"].shape[1]:]
            new = new[new != tok.pad_token_id]
            text = C.PREFILL + tok.decode(new, skip_special_tokens=True)
            done_cb(r, text, {"tokens": int(len(new)), "batch_s": round(dt, 2), "batch_size": len(chunk)})
        print(f"  {min(i + a.bs, len(rows))}/{len(rows)} batch {dt:.1f}s", flush=True)


def gpu_temp():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15).stdout
        return int(o.strip().split()[0])
    except Exception:  # noqa: BLE001
        return None


def _post(url, body, timeout=1800):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return json.loads(f.read().decode("utf-8", errors="replace"))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def gen_gguf(rows, a, done_cb, out):
    port = _free_port()
    srv = LLAMA / "build-host" / "bin" / "llama-server"
    args = [str(srv), "-m", a.model, "-t", str(a.threads), "-tb", str(a.threads), "-c", str(a.slot_ctx * a.np),
            "-np", str(a.np), "--port", str(port), "--host", "127.0.0.1", "-ngl", "0", "-fa", "auto",
            "--temp", "0"]
    log = open(out / "server.log", "a", encoding="utf-8")
    print("starting", " ".join(args), flush=True)
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(600):
            try:
                with urllib.request.urlopen(base + "/health", timeout=5) as f:
                    if json.loads(f.read()).get("status") == "ok":
                        break
            except Exception:  # noqa: BLE001
                pass
            if proc.poll() is not None:
                raise SystemExit("llama-server exited, see server.log")
            time.sleep(1)
        # tokenisation check (once): server tokens == htpd's (parse_special, no add_special) on the full prompt
        r0 = rows[0]
        t_srv = _post(base + "/tokenize", {"content": r0["prompt"][len(BOS_TEXT):], "add_special": True})["tokens"]
        t_raw = _post(base + "/tokenize", {"content": r0["prompt"], "add_special": False})["tokens"]
        tokcheck = {"bos_count": t_srv.count(128000), "equal_to_htpd_tokens": t_srv == t_raw, "n": len(t_srv)}
        (out / "tokenize_check.json").write_text(json.dumps(tokcheck))
        print("tokenize check", tokcheck, flush=True)
        if not tokcheck["equal_to_htpd_tokens"] or tokcheck["bos_count"] != 1:
            raise SystemExit("tokenisation differs from the device path")

        def one(r):
            t0 = time.time()
            p = r["prompt"][len(BOS_TEXT):] if r["prompt"].startswith(BOS_TEXT) else r["prompt"]
            res = _post(base + "/completion", {"prompt": p + C.PREFILL, "n_predict": a.max_new, "temperature": 0,
                                               "top_k": 1, "cache_prompt": True, "stop": ['"action"', "<|eot_id|>"]})
            text = C.PREFILL + res.get("content", "")
            if res.get("stop_type") == "word" and res.get("stopping_word") == '"action"':
                text += '"action"'
            tm = res.get("timings", {})
            return r, text, {"tokens": res.get("tokens_predicted"), "prompt_ms": tm.get("prompt_ms"),
                             "predicted_ms": tm.get("predicted_ms"), "cached": res.get("tokens_cached"),
                             "wall_s": round(time.time() - t0, 2)}

        rows = sorted(rows, key=lambda r: (r["role"], len(r["prompt"])))  # same role together: prefix cache hits
        n = 0
        with ThreadPoolExecutor(a.np) as ex:
            for r, text, meta in ex.map(one, rows):
                done_cb(r, text, meta)
                n += 1
                if n % 10 == 0:
                    print(f"  {n}/{len(rows)}", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def cmd_run(a):
    post = Path(a.post)
    out = post / "eval" / a.tag
    out.mkdir(parents=True, exist_ok=True)
    rows = load_eval_set(post)
    if a.subset and a.subset < len(rows):
        # stratified sub-sample of the frozen eval set (same rule, so roles/seen/families stay balanced);
        # the device runs the full set, comparisons pair by id
        rows = C.select_rows(rows, a.subset, 2026)
    if a.limit:
        rows = rows[:a.limit]
    sp = out / "samples.jsonl"
    done = set()
    if sp.exists():
        done = {json.loads(l)["id"] for l in open(sp, encoding="utf-8") if l.strip()}
    todo = [r for r in rows if r["id"] not in done]
    print(f"{a.tag}: {len(todo)} of {len(rows)} rows to run ({a.backend}, {a.model})", flush=True)
    fh = open(sp, "a", encoding="utf-8")

    def done_cb(r, text, meta):
        s = C.score_one(r, text)
        s.update(text=text, cut=C.cut_at_action(text)[1], **meta)
        fh.write(json.dumps(s, default=str) + "\n")
        fh.flush()

    t0 = time.time()
    if todo:
        if a.backend == "hf":
            gen_hf(todo, a, done_cb)
        else:
            gen_gguf(todo, a, done_cb, out)
    fh.close()
    summarize(out, a, time.time() - t0, {r["id"] for r in rows})


def summarize(out, a=None, wall=None, ids=None):
    scored = [json.loads(l) for l in open(out / "samples.jsonl", encoding="utf-8") if l.strip()]
    if ids:
        scored = [s for s in scored if s["id"] in ids]   # only the rows of this run's (sub)set
    agg = C.aggregate(scored)
    summ = {"tag": out.name, "n": len(scored), "metrics": agg,
            "backend": getattr(a, "backend", None), "model": getattr(a, "model", None),
            "load": getattr(a, "load", None), "wall_s_this_run": round(wall, 1) if wall else None,
            "mean_out_tokens": round(sum(s.get("tokens") or 0 for s in scored) / max(1, len(scored)), 1)}
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
    md = f"# Host eval {out.name} ({summ['backend']}, {summ['model']})\n\n" + C.table_md(out.name, agg, C.headline_keys(agg))
    (out / "tables.md").write_text(md, encoding="utf-8")
    a_ = agg["ALL"]
    print(f"{out.name}: n={len(scored)} " + " ".join(f"{k}={a_[k]['rate']}" for k in C.METRICS if k in a_), flush=True)


def cmd_compare(a):
    post = Path(a.post)
    ev = post / "eval"
    load = lambda t: {s["id"]: s for s in map(json.loads, open(ev / t / "samples.jsonl", encoding="utf-8"))}
    ref = load(a.ref)
    res, md = {}, [f"# Quantisation loss vs {a.ref} (same {len(ref)} test rows, paired)\n"]
    keys = ("json", "pattern", "status", "cause", "action", "event_active", "onset_15", "evidence", "policy")
    for c in a.cand:
        if not (ev / c / "samples.jsonl").exists():
            continue
        cand = load(c)
        ids = [i for i in ref if i in cand]
        row = {"n_paired": len(ids)}
        for k in keys + ("fault_kind", "false_alarm"):
            pr = [(ref[i][k], cand[i][k]) for i in ids if ref[i].get(k) is not None and cand[i].get(k) is not None]
            if not pr:
                continue
            ra = sum(1 for x, _ in pr if x) / len(pr)
            ca = sum(1 for _, y in pr if y) / len(pr)
            row[k] = {"ref": round(ra, 3), "cand": round(ca, 3), "delta_pts": round(100 * (ca - ra), 1), "n": len(pr),
                      "mcnemar": C.mcnemar([x for x, _ in pr], [y for _, y in pr])}
        same = [ref[i]["pred"] and cand[i]["pred"] and all(ref[i]["pred"][k] == cand[i]["pred"][k]
                for k in ("pattern", "status", "likely_cause")) for i in ids]
        row["same_pattern_status_cause"] = round(sum(map(bool, same)) / max(1, len(ids)), 3)
        per_role = {}
        for role in sorted({ref[i]["role"] for i in ids}):
            rid = [i for i in ids if ref[i]["role"] == role]
            per_role[role] = {"n": len(rid), "pattern_ref": round(sum(ref[i]["pattern"] for i in rid) / len(rid), 3),
                              "pattern_cand": round(sum(cand[i]["pattern"] for i in rid) / len(rid), 3)}
        row["per_role_pattern"] = per_role
        res[c] = row
        md.append(f"\n## {c}\n\nsame (pattern, status, cause) as {a.ref}: {100 * row['same_pattern_status_cause']:.1f}%\n\n"
                  "| metric | n | " + a.ref + " | " + c + " | delta (pts) | McNemar p |\n|---|---|---|---|---|---|")
        for k in keys + ("fault_kind", "false_alarm"):
            if k in row:
                v = row[k]
                md.append(f"| {k} | {v['n']} | {100 * v['ref']:.1f} | {100 * v['cand']:.1f} | {v['delta_pts']:+.1f} | {v['mcnemar']['p']} |")
        md.append("\n| role | n | pattern " + a.ref + " | pattern " + c + " |\n|---|---|---|---|")
        for role, v in per_role.items():
            md.append(f"| {role} | {v['n']} | {100 * v['pattern_ref']:.1f} | {100 * v['pattern_cand']:.1f} |")
    (ev / "quant_loss.json").write_text(json.dumps(res, indent=1))
    (ev / "quant_loss.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--post", required=True)
    s.add_argument("--n", type=int, default=400)
    s.add_argument("--seed", type=int, default=2026)
    s.add_argument("--force", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--post", required=True)
    r.add_argument("--backend", choices=["hf", "gguf"], required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--tag", required=True)
    r.add_argument("--load", choices=["bf16", "int8", "nf4"], default="bf16")
    r.add_argument("--gpu-mem", default="4200MiB", help="hf bf16: GPU share of the weights (rest offloaded to CPU)")
    r.add_argument("--bs", type=int, default=8)
    r.add_argument("--max-new", type=int, default=160)
    r.add_argument("--np", type=int, default=4)
    r.add_argument("--slot-ctx", type=int, default=1536)
    r.add_argument("--threads", type=int, default=8)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--subset", type=int, default=0, help="stratified sub-sample of the eval set (0 = all)")
    r.add_argument("--hot", type=int, default=76)
    r.add_argument("--cool", type=int, default=68)
    c = sub.add_parser("compare")
    c.add_argument("--post", required=True)
    c.add_argument("--ref", required=True)
    c.add_argument("--cand", nargs="+", required=True)
    a = ap.parse_args()
    {"select": cmd_select, "run": cmd_run, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    main()
