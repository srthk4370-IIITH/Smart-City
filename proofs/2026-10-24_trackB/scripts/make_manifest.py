"""MANIFEST.json: md5 + size of every file in the Track B proof folder, plus the inputs it was computed from."""
import hashlib
import json
import time
from pathlib import Path

D = Path(__file__).resolve().parent.parent
H = Path.home() / "smartcity_runs"
files = {}
for p in sorted(D.rglob("*")):
    if p.is_file() and p.name != "MANIFEST.json" and "__pycache__" not in p.parts:
        files[str(p.relative_to(D))] = {"md5": hashlib.md5(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
inputs = {}
for s in ("eval_test", "eval_rw5test", "eval_dev", "eval_rw5dev"):
    for f in (H / "agents_v2_topup3f" / s / "eval3e.jsonl", H / "agents_v2_topup3f" / s / "eval" / "v2cuda" / "samples.jsonl"):
        inputs[str(f)] = hashlib.md5(f.read_bytes()).hexdigest()
m = H / "agents_v2/post/gguf/ft_v2_q4_0.gguf"
inputs[str(m)] = {"bytes": m.stat().st_size}
(D / "MANIFEST.json").write_text(json.dumps({"created": time.strftime("%Y-%m-%d %H:%M"), "llama_cpp": "620d2225c (host CPU build-host)",
                                             "inputs": inputs, "files": files}, indent=1))
print(len(files), "files")
