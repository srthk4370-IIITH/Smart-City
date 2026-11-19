"""CPU checks of topup_train.py (no GPU; tiny random Qwen3.5 as speed/EQUIV.md, real tokenizer, 24 real r3 rows from rows.pt).
  1 init: --init-adapter + --lr 0, 1 step -> saved adapter == start adapter bit for bit; INIT_CHECK max_abs 0 logged.
  2 resume: A = 3 steps straight; B = 2 steps, then a second process resumes to 3 -> B == A (adapter + optimizer state);
    B's resume must not re-read --init-adapter (it differs from the start after training).
  3 selection: scripted generation scores (gen_score patched) -> start scored at step 0, an r3 regression is not eligible,
    best-K only above the start, early stop after 3 evals without a better eligible score (exit 6).
  4 split_think / gold_of unit cases.
usage (WSL): ~/venvs/rsn/bin/python cpu_test.py OUT.json"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TR = os.path.abspath(os.path.join(HERE, "..", "topup_train.py"))
SPEED = os.path.abspath(os.path.join(HERE, "..", "..", "..", "2026-11-06_4b_local", "speed"))
sys.path.insert(0, SPEED)
import eqlib as E  # noqa: E402
import torch  # noqa: E402
from safetensors.torch import load_file  # noqa: E402

OUT = sys.argv[1]
W = os.path.expanduser("~/topup_r4_cputest")      # scratch, deleted at the end
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)
res = {}

# ---- 4 unit cases (no model)
sys.path.insert(0, os.path.dirname(TR))
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("topup_train", TR)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
cases = [("<think>\nA and B share a feeder {x}.\n</think>\n\n{\"title\": \"t\"}", "A and B share a feeder {x}.", "{\"title\": \"t\"}"),
         ("A and B.\n</think>\n\n{\"title\": \"t\"}", "A and B.", "{\"title\": \"t\"}"),
         ("<think>\n\n</think>\n\n{\"title\": \"t\"}", "", "{\"title\": \"t\"}"),
         ("{\"title\": \"t\"}", "", "{\"title\": \"t\"}"),
         ("{\"title\": \"says </think> inside\"}", "", "{\"title\": \"says </think> inside\"}")]
for txt, th, rest in cases:
    a, b = M.split_think(txt)
    assert (a, b.strip()) == (th, rest), (txt, a, b)
g, gth = M.gold_of({"messages": [{"role": "assistant", "content": "{\"severity\": \"warning\"}", "reasoning_content": "x"}]})
assert g == {"severity": "warning"} and gth == "x"
res["unit_split_think"] = "ok (%d cases + gold_of)" % len(cases)
print("unit ok", flush=True)

# ---- tiny model dir + start adapter (LoRA B random = a trained-looking start)
pm = E.tiny_model()
pm.save_pretrained(os.path.join(W, "start"))
plain = pm.unload()
MD = os.path.join(W, "tiny")
plain.save_pretrained(MD)
for f in os.listdir(E.BASE):
    if f.startswith("tokenizer") or f.endswith(".jinja") or f in ("special_tokens_map.json", "vocab.json", "merges.txt"):
        shutil.copy(os.path.join(E.BASE, f), MD)
del pm, plain
R = torch.load(E.ROWS)["rows"]
os.makedirs(os.path.join(W, "data"))
CACHES = {}
for kind, name in (("incident", "new"), ("chat", "replay")):
    rs = [r for r in R if r["kind"] == kind]
    path = os.path.join(W, "data", name + ".jsonl")
    with open(path, "w", encoding="utf-8") as g:
        for r in rs:
            g.write(r["line"])
    CACHES["%s_%s_seg_tok.pt" % (name, M.T.md5(path))] = [{"id": r["id"], "kind": r["kind"], "family": "", "hard": False,
                                                          "ids": r["ids"], "labels": r["labels"]} for r in rs]
GEN = os.path.join(W, "data", "gen.jsonl")
with open(GEN, "w") as g:
    for i in range(3):
        g.write(json.dumps({"id": "g%d" % i, "tools": "incident", "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                                                                              {"role": "assistant", "content": "{}"}]}) + "\n")
COMMON = ["--base", MD, "--tools", os.path.join(E.DATA, "tools_r3.json"), "--init-adapter", os.path.join(W, "start"),
          "--new", os.path.join(W, "data", "new.jsonl"), "--replay", os.path.join(W, "data", "replay.jsonl"),
          "--max-len", "8192", "--micro-tokens", "7424", "--shared-prefix", "--oom-stop", "--lora-dropout", "0", "--hours", "5",
          "--save-every", "100000", "--eval-every", "0", "--step-log"]
# runner: optional scripted gen scores (env FAKE_GEN = json list of [r4, r3] per evaluation)
RUN = r"""
import json, os, sys, importlib.util, torch
sys.modules['fla'] = None; sys.modules['causal_conv1d'] = None
spec = importlib.util.spec_from_file_location('topup_train', %r); M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
F = json.loads(os.environ.get('FAKE_GEN', '[]')); I = [0]
def f4(model, tok, tools, rows, dev):
    s = F[I[0]][0]; x = (400 * s - 100) / 3; return [100.0, 100.0, x, x, x]   # (p+s+l+t)/(4n) = s
def f3(model, tok, tools, ir, cr, dev, *a):
    s = F[I[0]][1]; I[0] += 1; return torch.tensor([100.0, 100.0, 150 * s - 50, 150 * s - 50, 0.0, 0.0])
if F:
    M.gen_score_r4_inc = f4; M.T.gen_score = f3
sys.argv = ['topup_train.py'] + sys.argv[1:]
sys.exit(M.main())
""" % TR


def run(name, out, extra, expect, env=None):
    E.mem_guard(name)
    os.makedirs(out, exist_ok=True)
    for f, d in CACHES.items():
        if not os.path.exists(os.path.join(out, f)):
            torch.save(d, os.path.join(out, f))
    r = subprocess.run([sys.executable, "-c", RUN] + COMMON + ["--out", out] + extra, capture_output=True, text=True,
                       env=dict(os.environ, **(env or {})))
    tail = [l for l in (r.stdout + r.stderr).splitlines() if "Warning" not in l and "warn" not in l][-3:]
    print(name, extra, "rc", r.returncode, tail[-1:], flush=True)
    assert r.returncode == expect, "\n".join(tail)
    return open(os.path.join(out, "train.log")).read()


def ad(p):
    return load_file(os.path.join(p, "adapter_model.safetensors"))


def cmp(a0, a1):
    assert a0.keys() == a1.keys(), (len(a0), len(a1))
    num = sum(float(((a0[k].double() - a1[k].double()) ** 2).sum()) for k in a0)
    den = sum(float((a0[k].double() ** 2).sum()) for k in a0)
    return {"tensors": len(a0), "max_abs": max(float((a0[k] - a1[k]).abs().max()) for k in a0), "rel_l2": (num / den) ** 0.5}


# ---- 1 init == start
lg = run("init", os.path.join(W, "I"), ["--accum", "8", "--lr", "0", "--max-steps", "1"], 3)
ic = [l for l in lg.splitlines() if "INIT_CHECK" in l][0]
c = cmp(ad(os.path.join(W, "start")), ad(os.path.join(W, "I", "ckpt_latest")))
assert c["max_abs"] == 0.0 and "max_abs 0" in ic, (c, ic)
res["init_equals_start"] = {"init_check_line": ic.split("] ", 1)[1], "saved_after_1_step_lr0_vs_start": c}

# ---- 2 resume
run("A", os.path.join(W, "A"), ["--accum", "8", "--lr", "1e-3", "--max-steps", "3"], 3)
run("B1", os.path.join(W, "B"), ["--accum", "8", "--lr", "1e-3", "--max-steps", "2"], 3)
lgB = run("B2", os.path.join(W, "B"), ["--accum", "8", "--lr", "1e-3", "--max-steps", "3"], 3)
assert "resumed at step 2/" in lgB and "INIT_CHECK %s" % os.path.join(W, "B", "ckpt_latest") in lgB
cA = cmp(ad(os.path.join(W, "A", "ckpt_latest")), ad(os.path.join(W, "B", "ckpt_latest")))
moved = cmp(ad(os.path.join(W, "start")), ad(os.path.join(W, "A", "ckpt_latest")))
sA = torch.load(os.path.join(W, "A", "ckpt_latest", "state.pt"), weights_only=False)
sB = torch.load(os.path.join(W, "B", "ckpt_latest", "state.pt"), weights_only=False)
ex = max(float((sA["opt"]["state"][k]["exp_avg"] - sB["opt"]["state"][k]["exp_avg"]).abs().max()) for k in sA["opt"]["state"])
assert sA["step"] == sB["step"] == 3 and sA["sched"] == sB["sched"]
assert cA["rel_l2"] < 1e-5 and moved["rel_l2"] > 1e-4, (cA, moved)
sch = json.load(open(os.path.join(W, "A", "schedule.json")))
mixes = [(sum(k.startswith("N:") for k in g), sum(k.startswith("R:") for k in g)) for g in sch["groups"]]
assert mixes == [(4, 4)] * 3 + [(2, 4)], mixes          # 14 new rows: 4 + 4 + 4 + 2; replay always 4 (cycled)
res["resume"] = {"B_resumed_vs_A_straight": cA, "opt_exp_avg_max_abs_diff": ex, "sched_equal": True,
                 "A_vs_start (training moved)": moved, "groups_new_replay": mixes}

# ---- 3 selection logic (scripted scores, accum 4 -> 7 steps, gen every step)
F = [[.50, .90], [.60, .85], [.60, .90], [.55, .90], [.52, .895], [.50, .90], [.9, .9]]
lgS = run("sel", os.path.join(W, "S"), ["--accum", "4", "--lr", "1e-4", "--gen-every", "1", "--gen-r4-inc", GEN, "--gen-inc", GEN],
          6, {"FAKE_GEN": json.dumps(F)})
b = json.load(open(os.path.join(W, "S", "best.json")))
kept = sorted(d for d in os.listdir(os.path.join(W, "S")) if d.startswith("ckpt_best_"))
assert abs(b["start"] - 0.70) < 1e-6 and [s for _, s in b["top"]] == [2, 3, 4], b
assert kept == ["ckpt_best_0002", "ckpt_best_0003", "ckpt_best_0004"], kept
assert not b["history"][0]["eligible"] and "EARLY STOP at step 5" in lgS, b["history"]
res["selection"] = {"start": b["start"], "top": b["top"], "kept": kept, "history": b["history"], "early_stop": "step 5 (exit 6)"}
json.dump(res, open(OUT, "w"), indent=1)
print("ALL OK", flush=True)
shutil.rmtree(W, ignore_errors=True)
