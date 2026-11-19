"""oom_retry_test.py: CPU test of train_rsn3.py's OOM handling (--oom-stop, shared-prefix retry) through the real main() on a
tiny random Qwen3.5 (speed/eqlib.py: real tokenizer, the 12 shortest real r3 rows, accum 4, 2 optimizer steps; short rows keep the CPU
attention matrices small). OOMs are injected by
monkeypatching the trainer's loss functions (torch.OutOfMemoryError), nothing else changes.
  A  --shared-prefix                                  reference
  B  --shared-prefix --oom-stop, 1st shared-prefix forward OOMs  -> rows retried one per forward, rc 3, adapter == A
  C  --oom-stop (micro-batches)                        reference
  D  --oom-stop, 1st micro-batch OOMs                  -> retried one per forward, rc 3, adapter == C
  E  --shared-prefix --oom-stop, every forward of step 1 OOMs -> rc 7 "OOM STOP", ckpt_latest at step 1, nothing skipped
  F  --shared-prefix (no --oom-stop), same fault       -> rc 3, step skipped (old behaviour kept for non-baton runs)
usage: oom_retry_test.py <out.json>   (WSL venv ~/venvs/rsn, CUDA hidden)"""
import json
import os
import shutil
import subprocess
import sys

SPEED = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/speed"
W = os.path.expanduser("~/oom_retry_test")
MD = os.path.join(W, "tiny")
# RAM (laptop WSL shares ~6 GB with a live trainer): this driver never imports torch; prep, each run and the comparison are
# separate child processes, one at a time
PREP = r'''
import os, shutil, sys
sys.path.insert(0, %r)
import eqlib as E, torch
W, MD = %r, %r
pm = E.tiny_model()
plain = pm.unload()
plain.save_pretrained(MD)
for f in os.listdir(E.BASE):
    if f.startswith("tokenizer") or f.endswith(".jinja") or f in ("special_tokens_map.json", "vocab.json", "merges.txt"):
        shutil.copy(os.path.join(E.BASE, f), MD)
T = E.load_trainer()
R = sorted(torch.load(E.ROWS)["rows"], key=lambda r: len(r["ids"]))[:12]    # the 12 shortest rows: small CPU attention matrices
print("rows", len(R), "max tokens", max(len(r["ids"]) for r in R), "kinds", sorted(set(r["kind"] for r in R)))
os.makedirs(os.path.join(W, "data"))
caches = {}
for kind, name, dst in (("incident", "inc", "inc.jsonl"), ("chat", "chat", "chat.jsonl")):
    rs = [r for r in R if r["kind"] == kind]
    path = os.path.join(W, "data", dst)
    with open(path, "w", encoding="utf-8") as g:
        for r in rs:
            g.write(r["line"])
    caches["%%s_%%s_seg_tok.pt" %% (name, T.md5(path))] = [{"id": r["id"], "kind": r["kind"], "family": "", "hard": False,
                                                         "ids": r["ids"], "labels": r["labels"]} for r in rs]
torch.save(caches, os.path.join(W, "caches.pt"))
''' % (SPEED, W, MD)
# per run: seed the trainer's token caches (prep() finds them by the jsonl md5) so main() never re-tokenizes
SEED = r'''
import os, sys, torch
c = torch.load(sys.argv[1])
for f, d in c.items():
    torch.save(d, os.path.join(sys.argv[2], f))
'''
INFO = r'''
import json, os, sys, torch
p = os.path.join(sys.argv[1], "ckpt_latest", "state.pt")
print(json.dumps(torch.load(p, weights_only=False)["step"] if os.path.exists(p) else None))
'''
REL = r'''
import json, os, sys
from safetensors.torch import load_file
x, y = [load_file(os.path.join(d, "ckpt_latest", "adapter_model.safetensors")) for d in sys.argv[1:3]]
num = sum(float(((x[k].double() - y[k].double()) ** 2).sum()) for k in x)
den = sum(float((x[k].double() ** 2).sum()) for k in x)
print(json.dumps((num / den) ** 0.5))
'''
OUT = sys.argv[1]
ENV = dict(os.environ, CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", MALLOC_ARENA_MAX="2", TOKENIZERS_PARALLELISM="false")


def py(code, *args, **kw):
    return subprocess.run([sys.executable, "-c", code] + list(args), capture_output=True, text=True, env=dict(ENV, **kw))


def win_avail():
    """Windows AvailableMBytes (the WSL VM grows into it), None if not readable"""
    try:
        r = subprocess.run(["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-NoProfile", "-Command",
                            r"[int](Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue"],
                           capture_output=True, text=True, timeout=60)
        return int(r.stdout.strip())
    except Exception:
        return None


def mem_guard(tag):
    """start each child only with headroom: WSL MemAvailable >= 1500 MB and Windows AvailableMBytes >= OOMT_WIN_MB (default
    2800; one child is ~1.2 GB) - waits up to 15 min, else aborts (rc 9)"""
    need = int(os.environ.get("OOMT_WIN_MB", "2800"))
    import time
    for _ in range(90):
        av = int([l for l in open("/proc/meminfo") if l.startswith("MemAvailable")][0].split()[1]) // 1024
        w = win_avail()
        if av >= 1500 and (w is None or w >= need):
            return
        time.sleep(10)
    print("ABORT: not enough free RAM for %s (WSL %d MB, Windows %s MB)" % (tag, av, w), flush=True)
    sys.exit(9)


shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)
mem_guard("prep")
r = py(PREP)
assert r.returncode == 0, r.stderr[-1500:]
print(r.stdout.strip().splitlines()[-1], flush=True)
# child: the real trainer main() with the fault injected by monkeypatching module functions (looked up at call time)
CHILD = r'''
import os, sys
sys.path.insert(0, %r)
import eqlib as E, torch
T = E.load_trainer()
mode = os.environ["OOMTEST"]
st = {"sp_steps": 0, "sp": 0, "mb": 0}
def oom():
    raise torch.OutOfMemoryError("CUDA out of memory (injected by oom_retry_test)")
def wrap(name, key, fail):
    f = getattr(T, name)
    def g(*a, **k):
        st[key] = st.get(key, 0) + 1
        if fail():
            oom()
        return f(*a, **k)
    setattr(T, name, g)
if mode == "sp_once":
    wrap("shared_prefix_loss", "sp", lambda: st["sp"] == 1)
elif mode == "mb_once":
    wrap("loss_fn_batch", "mb", lambda: st["mb"] == 1)
elif mode == "all_step1":
    wrap("shared_prefix_step", "sp_steps", lambda: False)
    for n in ("shared_prefix_loss", "loss_fn_batch", "loss_fn"):
        wrap(n, n, lambda: st["sp_steps"] >= 2)
sys.argv = ["train_rsn3.py"] + sys.argv[1:]
sys.exit(T.main())
''' % SPEED
COMMON = ["--base", MD, "--tools", "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/data/final/tools_r3.json", "--inc", os.path.join(W, "data", "inc.jsonl"),
          "--chat", os.path.join(W, "data", "chat.jsonl"), "--accum", "4", "--max-len", "8192", "--micro-tokens", "4096",
          "--lora-dropout", "0", "--hours", "5", "--gen-every", "100000", "--eval-every", "100000", "--save-every", "100000",
          "--max-steps", "2"]
res = {}


def run(name, flags, mode):
    mem_guard(name)
    out = os.path.join(W, name)
    os.makedirs(out)
    assert py(SEED, os.path.join(W, "caches.pt"), out).returncode == 0
    r = py(CHILD, *(COMMON + ["--out", out] + flags), OOMTEST=mode)
    lg = open(os.path.join(out, "train.log")).read() if os.path.exists(os.path.join(out, "train.log")) else ""
    step = json.loads(py(INFO, out).stdout.strip() or "null")
    res[name] = {"flags": flags, "fault": mode, "rc": r.returncode, "ckpt_step": step, "retries": lg.count("retrying this rank's"),
                 "skipped": lg.count("optimizer step skipped"), "oom_stop": lg.count("OOM STOP at step 1")}
    if r.returncode not in (3, 7):
        res[name]["tail"] = (r.stdout + r.stderr)[-1500:]
    print(name, json.dumps(res[name]), flush=True)


def rel(a, b):
    return json.loads(py(REL, os.path.join(W, a), os.path.join(W, b)).stdout.strip())


SP = ["--shared-prefix"]
run("A", SP, "none")
run("B", SP + ["--oom-stop"], "sp_once")
run("C", ["--oom-stop"], "none")
run("D", ["--oom-stop"], "mb_once")
run("E", SP + ["--oom-stop"], "all_step1")
run("F", SP, "all_step1")
res["B_vs_A_rel_l2"] = rel("B", "A")
res["D_vs_C_rel_l2"] = rel("D", "C")
chk = {
    "A_ref": res["A"]["rc"] == 3 and res["A"]["ckpt_step"] == 2 and res["A"]["retries"] == 0,
    "B_sp_retry": res["B"]["rc"] == 3 and res["B"]["ckpt_step"] == 2 and res["B"]["retries"] == 1 and res["B"]["skipped"] == 0
    and res["B_vs_A_rel_l2"] < 1e-3,
    "D_mb_retry": res["D"]["rc"] == 3 and res["D"]["ckpt_step"] == 2 and res["D"]["retries"] == 1 and res["D"]["skipped"] == 0
    and res["D_vs_C_rel_l2"] < 1e-3,
    "E_oom_stop": res["E"]["rc"] == 7 and res["E"]["ckpt_step"] == 1 and res["E"]["oom_stop"] == 1 and res["E"]["skipped"] == 0,
    "F_default_skips": res["F"]["rc"] == 3 and res["F"]["skipped"] >= 1 and res["F"]["oom_stop"] == 0,
}
res["checks"] = chk
res["ok"] = all(chk.values())
json.dump(res, open(OUT, "w"), indent=1)
print(json.dumps({"ok": res["ok"], "checks": chk, "B_vs_A": res["B_vs_A_rel_l2"], "D_vs_C": res["D_vs_C_rel_l2"]}))
shutil.rmtree(W, ignore_errors=True)
