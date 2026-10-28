"""Add a vocabulary-pruned lm_head to the tied-embedding reasoner GGUF (for libllama_p / htpd_v8p).
output.weight = the token_embd rows (Q6_K, bit-exact copies) of the kept tokens; qwen35.output_keep_ids = their ids.
token_embd (input) stays full. Keep set = every token in the reasoner corpora (train/dev/RWH/RW6/chat, all roles, tool
schemas, backend prompt files, board prompts) + all ASCII tokens of <= 4 characters + all special tokens, filled up with the
lowest ids to N. usage (WSL): PYTHONPATH=<llama.cpp>/gguf-py python make_pruned_head.py SRC DST TOKENIZER_JSON N"""
import glob, json, os, sys
import numpy as np, gguf
from gguf import GGMLQuantizationType as Q
from tokenizers import Tokenizer
src, dst, tokf, N = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
tk = Tokenizer.from_file(tokf)
V = tk.get_vocab_size(with_added_tokens=True)
keep = set()
def add_text(t):
    if t: keep.update(tk.encode(t, add_special_tokens=False).ids)
Qd = "/mnt/c/Users/hp/Desktop/qidk"
for f in glob.glob(Qd + "/proofs/2026-10-25_reasoner_final/data/*.jsonl"):
    for l in open(f, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        for m in r.get("messages", []):
            add_text(m.get("content"))
            for c in m.get("tool_calls") or []: add_text(json.dumps(c, ensure_ascii=False))
        if r.get("tools"): add_text(json.dumps(r["tools"], ensure_ascii=False))
B = Qd + "/Code/smart-city-edge-agent/app"
for f in [B + "/backend/reasoner_v3_header.txt", B + "/backend/reasoner_v3_system.txt", Qd + "/proofs/2026-10-25_reasoner_final/pipeline/tools_v3.json"] + glob.glob(B + "/device/data/*.json"):
    add_text(open(f, encoding="utf-8").read())
for f in glob.glob(Qd + "/proofs/2026-10-27_reasoner_fast/bench/prompts.jsonl"):
    for l in open(f, encoding="utf-8"): add_text(json.loads(l)["prompt"])
n_corpus = len(keep)
for i in range(V):
    s = tk.id_to_token(i)
    d = tk.decode([i])
    if s is not None and ((d and len(d) <= 4 and all(ord(ch) < 128 for ch in d)) or i >= 248044):
        keep.add(i)
n_short = len(keep)
i = 0
while len(keep) < N and i < V:
    keep.add(i); i += 1
ids = np.array(sorted(keep), dtype=np.int32)
print(f"vocab {V}: corpus {n_corpus}, +short/special -> {n_short}, filled to {len(ids)} (lowest ids up to {i})")

r = gguf.GGUFReader(src, "r")
arch = r.fields[gguf.Keys.General.ARCHITECTURE].contents()
w = gguf.GGUFWriter(dst, arch=arch, endianess=r.endianess)
for f in r.fields.values():
    if f.name == gguf.Keys.General.ARCHITECTURE or f.name.startswith("GGUF."):
        continue
    vt = f.types[0]; st = f.types[-1] if vt == gguf.GGUFValueType.ARRAY else None
    w.add_key_value(f.name, f.contents(), vt, sub_type=st)
w.add_array(f"{arch}.output_keep_ids", ids.tolist())
emb = next(t for t in r.tensors if t.name == "token_embd.weight")
assert emb.tensor_type == Q.Q6_K and not any(t.name == "output.weight" for t in r.tensors)
assert ids.max() < emb.data.shape[0]
out = np.ascontiguousarray(np.asarray(emb.data)[ids])   # whole Q6_K rows: bit-exact
for t in r.tensors:
    w.add_tensor_info(t.name, t.data.shape, t.data.dtype, t.data.nbytes, t.tensor_type)
    if t.name == "token_embd.weight":
        w.add_tensor_info("output.weight", out.shape, out.dtype, out.nbytes, Q.Q6_K)
w.write_header_to_file(); w.write_kv_data_to_file(); w.write_ti_data_to_file()
for t in r.tensors:
    w.write_tensor_data(t.data, tensor_endianess=r.endianess)
    if t.name == "token_embd.weight":
        w.write_tensor_data(out, tensor_endianess=r.endianess)
w.close()
np.save(os.path.splitext(dst)[0] + ".keep_ids.npy", ids)
print("done", dst, out.shape)
