"""selftest_tree.py QIDK STAGE_TREE: the staged data tree alone must run train_rsn3.py's r3 chat gen-eval verification exactly
like the repo does (gold transcripts of gen_chat_r3 / gen_train_chat_r3). Runs each side in its own `python -I` process; the
staged run must import every module from inside the staged copy and must not create files there (sqlite opened read-only).
CPU only. Exit 1 on any difference."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

CODE = r'''
import json, os, sys
root = sys.argv[1]
sys.path.insert(0, os.path.join(root, "proofs", "2026-10-29_rsn_v3", "kaggle"))
import train_rsn3 as T
import chatloop as CL
F = os.path.join(root, "proofs", "2026-11-06_4b_local", "data", "final")
res = {}
for fn in ("gen_chat_r3.jsonl", "gen_train_chat_r3.jsonl"):
    recs = [json.loads(l) for l in open(os.path.join(F, fn), encoding="utf-8")]
    g = T.verify_chat_recs(recs, [CL.gold_messages(r)[len(CL.prompt_messages(r)):] for r in recs], "auto",
                           os.path.join(root, "proofs", "2026-11-06_4b_local", "tools"))
    res[fn] = [len(recs), sum(g)]
mods = {m: getattr(sys.modules.get(m), "__file__", None) for m in ("chatloop", "verify_chat", "tools_r3_impl", "tools_v3_impl", "tools_impl", "common")}
print(json.dumps({"res": res, "mods": mods}))
'''


def run(root):
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="")
    r = subprocess.run([sys.executable, "-I", "-c", CODE, root], capture_output=True, text=True, env=env, cwd=tempfile.gettempdir())
    if r.returncode:
        sys.exit("FAILED in %s:\n%s" % (root, r.stderr[-2000:]))
    return json.loads(r.stdout.strip().splitlines()[-1])


qidk, tree = sys.argv[1:3]
tmp = tempfile.mkdtemp(prefix="r3tree_")
try:
    t = os.path.join(tmp, "tree")
    shutil.copytree(tree, t)
    shutil.copy(os.path.join(qidk, "proofs", "2026-10-29_rsn_v3", "kaggle", "train_rsn3.py"), os.path.join(t, "proofs", "2026-10-29_rsn_v3", "kaggle"))
    before = sorted(os.path.relpath(os.path.join(a, f), t) for a, _, fs in os.walk(t) for f in fs)
    repo, staged = run(qidk), run(t)
    after = sorted(os.path.relpath(os.path.join(a, f), t) for a, _, fs in os.walk(t) for f in fs if "__pycache__" not in a)
    outside = {m: p for m, p in staged["mods"].items() if p and not os.path.abspath(p).startswith(t)}
    created = sorted(set(after) - set(before))
    ok = repo["res"] == staged["res"] and not outside and not created and all(v[1] > 0 for v in staged["res"].values())
    print(json.dumps({"repo": repo["res"], "staged": staged["res"], "imported_outside_stage": outside, "files_created": created, "ok": ok}, indent=1))
    sys.exit(0 if ok else 1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
