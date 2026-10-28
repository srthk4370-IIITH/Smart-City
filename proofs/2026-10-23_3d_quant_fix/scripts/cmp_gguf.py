"""Tensor-by-tensor comparison of two GGUFs (types, shapes, raw bytes) + metadata key diff.
  python cmp_gguf.py a.gguf b.gguf out.json"""
import json, sys, hashlib
from pathlib import Path
sys.path.insert(0, str(Path.home() / "gpu_work/llama.cpp/gguf-py"))
import gguf, numpy as np
a, b = gguf.GGUFReader(sys.argv[1]), gguf.GGUFReader(sys.argv[2])
ta, tb = {t.name: t for t in a.tensors}, {t.name: t for t in b.tensors}
res, diff = {}, []
for n in sorted(set(ta) | set(tb)):
    if n not in ta or n not in tb:
        diff.append(n); res[n] = "missing"; continue
    x, y = ta[n], tb[n]
    same_t = x.tensor_type == y.tensor_type and list(x.shape) == list(y.shape)
    bx, by = np.asarray(x.data).tobytes(), np.asarray(y.data).tobytes()
    eq = same_t and bx == by
    res[n] = {"type": [x.tensor_type.name, y.tensor_type.name], "bytes_equal": eq}
    if not eq:
        diff.append(n)
        if len(bx) == len(by):
            res[n]["frac_bytes_diff"] = float((np.frombuffer(bx, np.uint8) != np.frombuffer(by, np.uint8)).mean())
def kv(r):
    out = {}
    for f in r.fields.values():
        if f.name.startswith("tokenizer.ggml.") and f.name in ("tokenizer.ggml.tokens", "tokenizer.ggml.merges", "tokenizer.ggml.token_type"):
            out[f.name] = hashlib.md5(b"".join(bytes(p) for p in f.parts)).hexdigest(); continue
        try:
            v = f.contents()
        except Exception:
            v = hashlib.md5(b"".join(bytes(p) for p in f.parts)).hexdigest()
        out[f.name] = v if isinstance(v, (int, float, str)) or v is None else str(v)[:200]
    return out
ka, kb = kv(a), kv(b)
kvd = {k: [ka.get(k), kb.get(k)] for k in set(ka) | set(kb) if ka.get(k) != kb.get(k) and not k.startswith("GGUF.")}
summ = {"a": sys.argv[1], "b": sys.argv[2], "n_tensors": len(res), "n_bytes_equal": len(res) - len(diff), "tensors_differ": diff[:30],
        "all_tensor_bytes_equal": not diff, "metadata_differences": kvd}
Path(sys.argv[3]).write_text(json.dumps({"summary": summ, "per_tensor": res}, indent=1, default=str))
print(json.dumps(summ, indent=1, default=str))
