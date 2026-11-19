"""item 3b: the real trainer main() on CPU (tiny random Qwen3.5 saved as a model dir, real tokenizer, 24 real r3 rows, accum 8,
LoRA dropout 0): optimizer steps + checkpoint save/load with the flags switched across the resume.
  A: baseline 3 steps | B: --shared-prefix 2 steps, resume baseline to 3 | C: baseline 2 steps, resume --shared-prefix to 3
  D: --shared-prefix 3 steps. Final adapters (and optimizer states) compared with A. usage: resume_test.py <trainer> <out.json>"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import eqlib as E

TR, OUT = sys.argv[1], sys.argv[2]
W = os.path.expanduser("~/sp_resume_test")       # scratch (deleted at the end)
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)
import torch  # noqa: E402

# tiny base model dir (LoRA stripped) + the real tokenizer files
pm = E.tiny_model()
plain = pm.unload()
MD = os.path.join(W, "tiny")
plain.save_pretrained(MD)
for f in os.listdir(E.BASE):
    if f.startswith("tokenizer") or f.endswith(".jinja") or f in ("special_tokens_map.json", "vocab.json", "merges.txt"):
        shutil.copy(os.path.join(E.BASE, f), MD)
del pm, plain
# data: the 24 pretokenized real rows (rows.pt: 14 incident + 10 chat, compact ids); jsonl files written from the same lines and
# the trainer's token caches pre-seeded in each run dir (prep() finds them by the jsonl md5), so main() never re-tokenizes
spec = importlib.util.spec_from_file_location("tr", TR)
TT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TT)
R = torch.load(E.ROWS)["rows"]
os.makedirs(os.path.join(W, "data"))
CACHES = {}
for kind, name, dst in (("incident", "inc", "inc.jsonl"), ("chat", "chat", "chat.jsonl")):
    rs = [r for r in R if r["kind"] == kind]
    path = os.path.join(W, "data", dst)
    with open(path, "w", encoding="utf-8") as g:
        for r in rs:
            g.write(r["line"])
    CACHES["%s_%s_seg_tok.pt" % (name, TT.md5(path))] = [{"id": r["id"], "kind": r["kind"], "family": "", "hard": False,
                                                          "ids": r["ids"], "labels": r["labels"]} for r in rs]
RUNPY = ("import sys, runpy; sys.modules['fla'] = None; sys.modules['causal_conv1d'] = None; sys.argv = [%r] + sys.argv[1:]; "
         "runpy.run_path(%r, run_name='__main__')") % (TR, TR)
COMMON = ["--base", MD, "--tools", os.path.join(E.DATA, "tools_r3.json"), "--inc", os.path.join(W, "data", "inc.jsonl"),
          "--chat", os.path.join(W, "data", "chat.jsonl"), "--accum", "8", "--max-len", "8192", "--micro-tokens", "7424",
          "--lora-dropout", "0", "--hours", "5", "--gen-every", "100000", "--eval-every", "100000", "--save-every", "100000", "--step-log"]
log = {}


def run(name, out, steps, extra):
    E.mem_guard(name)
    cmd = [sys.executable, "-c", RUNPY] + COMMON + ["--out", out, "--max-steps", str(steps)] + extra
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = [l for l in (r.stdout + r.stderr).splitlines() if "Warning" not in l and "falling back" not in l][-4:]
    log.setdefault(name, []).append({"steps_to": steps, "flags": extra, "rc": r.returncode, "tail": tail})
    print(name, steps, extra, "rc", r.returncode, tail[-1:] if r.returncode != 3 else "", flush=True)
    assert r.returncode == 3, "\n".join(tail)


def prime(dst):
    os.makedirs(dst, exist_ok=True)
    for f, d in CACHES.items():
        torch.save(d, os.path.join(dst, f))


SP = ["--shared-prefix"]
for n in "ABCD":
    prime(os.path.join(W, n))
run("A", os.path.join(W, "A"), 3, [])
run("B", os.path.join(W, "B"), 2, SP)
run("B", os.path.join(W, "B"), 3, [])
run("C", os.path.join(W, "C"), 2, [])
run("C", os.path.join(W, "C"), 3, SP)
run("D", os.path.join(W, "D"), 3, SP)
from safetensors.torch import load_file  # noqa: E402


def ad(n):
    return load_file(os.path.join(W, n, "ckpt_latest", "adapter_model.safetensors"))


def st(n):
    return torch.load(os.path.join(W, n, "ckpt_latest", "state.pt"), weights_only=False)


def steps(n):
    return [json.loads(l) for l in open(os.path.join(W, n, "steps.jsonl"))]


res = {"runs": log, "steps": {n: [(r["step"], r["loss"]) for r in steps(n)] for n in "ABCD"}}
a0 = ad("A")
for n in "BCD":
    a1 = ad(n)
    assert a1.keys() == a0.keys()
    num = sum(float(((a0[k].double() - a1[k].double()) ** 2).sum()) for k in a0)
    den = sum(float(((a0[k].double()) ** 2).sum()) for k in a0)
    s0, s1 = st("A"), st(n)
    ex = [float((x - y).abs().max()) for k in s0["opt"]["state"] for x, y in
          [(s0["opt"]["state"][k]["exp_avg"], s1["opt"]["state"][k]["exp_avg"])]]
    res[n + "_vs_A"] = {"adapter_tensors": len(a0), "adapter_max_abs": max(float((a0[k] - a1[k]).abs().max()) for k in a0),
                        "adapter_rel_l2": (num / den) ** 0.5, "step": s1["step"], "sched_equal": s0["sched"] == s1["sched"],
                        "opt_exp_avg_max_abs_diff": max(ex), "opt_state_tensors": len(s0["opt"]["state"])}
    print(n, json.dumps(res[n + "_vs_A"]), flush=True)
json.dump(res, open(OUT, "w"), indent=1)
shutil.rmtree(W, ignore_errors=True)
