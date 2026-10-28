"""Host Q4_0 greedy eval for 3e (llama-server CPU build 620d222 = htpd's ggml; same request/prefill/stop/scoring as
eval_htpd_v2 via host_eval_v2.gen_gguf + common_v2.score_one).

  build : python host_eval3e.py build --out DIR            # DIR/eval3e.jsonl = host400 + eval_weak (+ realworld*.jsonl)
  run   : python host_eval3e.py run --out DIR --model X.gguf --tag T [--threads 8 --np 4]
  table : python host_eval3e.py table --out DIR --ref v2 --cand T1 T2 ...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "post"))
import common_v2 as C  # noqa: E402
import host_eval_v2 as H  # noqa: E402

RUN = Path.home() / "smartcity_runs" / "agents_v2_topup3e"


def slices(r):
    s = {"ALL", "set_" + r.get("evalset", "?"), "role_" + r["role"], "seen_" + str(r.get("seen", "seen"))}
    d = r.get("d")
    if r.get("stage") in ("early", "1.5h", "3h"):
        s.add("stage_" + r["stage"])
    elif d:
        s.add("stage_early" if 3 <= d <= 9 else "stage_1.5h" if 15 <= d <= 21 else "stage_3h" if 33 <= d <= 39 else "age_other")
    if r.get("family") == "compound":
        s.add("compound")
    if C.is_negative(r):
        s.add("calm_or_routine")
    if C.gold_of(r)["status"] == "sensor_fault":
        s.add("sensor_fault")
    for x in r.get("slices", []):
        s.add(x)
    return sorted(s)


def cmd_build(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ids = json.loads((Path.home() / "smartcity_runs/agents_v2/post/eval_set.json").read_text())["ids"]
    by = {r["id"]: r for r in C.read_jsonl(C.DATA / "test.jsonl")}
    rows = []
    for i in ids:
        r = dict(by[i]); r["evalset"] = "host400"; rows.append(r)
    for r in C.read_jsonl(RUN / "data" / "eval_weak.jsonl"):
        r["evalset"] = "weak"; rows.append(r)
    for p in sorted((RUN / "data").glob("realworld_eval*.jsonl")):
        for r in C.read_jsonl(p):
            r["evalset"] = "realworld"; rows.append(r)
    for r in rows:
        r["slices_all"] = slices(r)
    with open(out / "eval3e.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    cnt = defaultdict(int)
    for r in rows:
        for s in r["slices_all"]:
            cnt[s] += 1
    (out / "eval3e_manifest.json").write_text(json.dumps({"n": len(rows), "slices": dict(sorted(cnt.items()))}, indent=1))
    print(len(rows), dict(sorted(cnt.items())))


def use_cuda():
    """GPU llama-server (prebuilt b11815 CUDA, ~/llama-cuda-b11815) in place of the CPU 620d222 build; -ngl 99.
    Fidelity vs the CPU build is measured on v2 (same rows) before it is used for screening."""
    import subprocess
    shim = Path.home() / "llama-cuda-shim"
    (shim / "build-host").mkdir(parents=True, exist_ok=True)
    b = shim / "build-host" / "bin"
    if not b.exists():
        b.symlink_to(Path.home() / "llama-cuda-b11815" / "bin")
    H.LLAMA = shim
    P0 = subprocess.Popen

    def P(args, *k, **kw):
        args = list(args)
        if "-ngl" in args:
            args[args.index("-ngl") + 1] = "99"
            args += ["--cache-ram", "0"]   # b11815 keeps a host-RAM prompt cache (default 8 GiB): off
            if os.environ.get("LORA_SCALED"):  # 3f/3g screening: runtime LoRAs "a.gguf:0.5,b.gguf:0.5" on the base Q4_0
                args += ["--lora-scaled", os.environ["LORA_SCALED"]]
            for f in ("-t", "-tb"):        # 3f: owner on the laptop -> at most 2 CPU threads (full GPU offload)
                if f in args:
                    args[args.index(f) + 1] = str(min(2, int(args[args.index(f) + 1])))
        return P0(args, *k, **kw)
    H.subprocess.Popen = P


def cmd_run(a):
    if a.cuda:
        use_cuda()
    out = Path(a.out)
    rows = C.read_jsonl(out / "eval3e.jsonl")
    ev = out / "eval" / a.tag
    ev.mkdir(parents=True, exist_ok=True)
    sp = ev / "samples.jsonl"
    done = {json.loads(l)["id"] for l in open(sp, encoding="utf-8")} if sp.exists() else set()
    todo = [r for r in rows if r["id"] not in done]
    print(f"{a.tag}: {len(todo)}/{len(rows)} to run", flush=True)
    fh = open(sp, "a", encoding="utf-8")

    def cb(r, text, meta):
        s = C.score_one(r, text)
        s.update(text=text, slices=r["slices_all"], **meta)
        fh.write(json.dumps(s, default=str) + "\n"); fh.flush()

    t0 = time.time()
    if todo:
        H.gen_gguf(todo, a, cb, ev)
    fh.close()
    (ev / "run.json").write_text(json.dumps({"model": a.model, "llama": str(H.LLAMA), "wall_s": round(time.time() - t0),
                                             "threads": a.threads, "np": a.np}))


def load(out, tag):
    return {s["id"]: s for s in map(json.loads, open(Path(out) / "eval" / tag / "samples.jsonl", encoding="utf-8"))}


def cmd_table(a):
    out = Path(a.out)
    ref = load(out, a.ref)
    res, md = {}, []
    keys = ("json", "pattern", "status", "cause", "false_alarm")
    for c in a.cand:
        cand = load(out, c)
        ids = [i for i in ref if i in cand]
        sl = defaultdict(list)
        for i in ids:
            for s in ref[i]["slices"]:
                sl[s].append(i)
        row = {}
        for s, ii in sorted(sl.items()):
            row[s] = {"n": len(ii)}
            for k in keys:
                pr = [(ref[i].get(k), cand[i].get(k)) for i in ii if ref[i].get(k) is not None and cand[i].get(k) is not None]
                if not pr:
                    continue
                x, y = [bool(p) for p, _ in pr], [bool(q) for _, q in pr]
                row[s][k] = {"n": len(pr), "ref": sum(x), "cand": sum(y), "wins": sum(1 for p, q in zip(x, y) if q and not p),
                             "losses": sum(1 for p, q in zip(x, y) if p and not q), "p": C.mcnemar(x, y)["p"]}
        res[c] = row
        md.append(f"\n## {a.ref} -> {c} (paired, n={len(ids)})\n\n| slice | n | pattern ref | pattern cand | W/L | p | status ref | status cand | W/L | cause ref->cand | false alarm ref->cand | json cand |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s, v in row.items():
            f = lambda k, j: v.get(k, {}).get(j, "")
            pc = lambda k, j: f"{v[k][j]}/{v[k]['n']} ({100 * v[k][j] / v[k]['n']:.1f})" if k in v else ""
            md.append(f"| {s} | {v['n']} | {pc('pattern', 'ref')} | {pc('pattern', 'cand')} | {f('pattern', 'wins')}/{f('pattern', 'losses')} | {f('pattern', 'p')} "
                      f"| {pc('status', 'ref')} | {pc('status', 'cand')} | {f('status', 'wins')}/{f('status', 'losses')} | "
                      f"{f('cause', 'ref')}->{f('cause', 'cand')} | {f('false_alarm', 'ref')}->{f('false_alarm', 'cand')} | {f('json', 'cand')}/{v.get('json', {}).get('n', '')} |")
    (out / "tables.json").write_text(json.dumps(res, indent=1))
    (out / "tables.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--out", required=True)
    r = sub.add_parser("run")
    for k, v in (("--out", None), ("--model", None), ("--tag", None)):
        r.add_argument(k, required=True)
    r.add_argument("--threads", type=int, default=8)
    r.add_argument("--np", type=int, default=4)
    r.add_argument("--slot-ctx", type=int, default=1536)
    r.add_argument("--max-new", type=int, default=160)
    r.add_argument("--cuda", action="store_true")
    t = sub.add_parser("table"); t.add_argument("--out", required=True); t.add_argument("--ref", required=True); t.add_argument("--cand", nargs="+", required=True)
    a = ap.parse_args()
    {"build": cmd_build, "run": cmd_run, "table": cmd_table}[a.cmd](a)


if __name__ == "__main__":
    main()
