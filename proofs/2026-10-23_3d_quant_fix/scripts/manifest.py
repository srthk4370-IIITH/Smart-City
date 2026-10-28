import collections, hashlib, json, os, sys
sys.path.insert(0, os.path.expanduser("~/gpu_work/llama.cpp/gguf-py"))
import gguf
out = sys.argv[1]; res = {}
for f in sys.argv[2:]:
    r = gguf.GGUFReader(f); t = {x.name: x.tensor_type.name for x in r.tensors}
    m = hashlib.md5()
    with open(f, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 24), b""): m.update(b)
    res[os.path.basename(f)] = {"path": f, "bytes": os.path.getsize(f), "md5": m.hexdigest(), "types": dict(collections.Counter(t.values())),
        "by_kind": {k: dict(collections.Counter(v for n, v in t.items() if f".{k}." in n)) for k in ("attn_q", "attn_k", "attn_v", "attn_output", "ffn_gate", "ffn_up", "ffn_down")},
        "non_block": {n: v for n, v in t.items() if not n.startswith("blk.")}}
json.dump(res, open(out, "w"), indent=1); print(json.dumps({k: (v["md5"], v["bytes"], v["types"]) for k, v in res.items()}, indent=1))
