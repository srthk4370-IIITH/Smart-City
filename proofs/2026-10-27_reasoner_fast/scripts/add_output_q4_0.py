"""Copy a tied-embedding GGUF and add an untied output.weight (lm_head) = Q4_0 requantization of token_embd.
The input embedding (token_embd, Q6_K, CPU get_rows) is unchanged; only the lm_head the HTP reads per token shrinks
(497 MB Q6_K -> 357 MB Q4_0). usage: python add_output_q4_0.py SRC DST   (PYTHONPATH=<llama.cpp>/gguf-py)"""
import sys, numpy as np, gguf
from gguf.scripts.gguf_new_metadata import MetadataDetails  # noqa: F401  (same package as the copy routine)
from gguf import GGMLQuantizationType as Q, quants
src, dst = sys.argv[1], sys.argv[2]
r = gguf.GGUFReader(src, "r")
arch = r.fields[gguf.Keys.General.ARCHITECTURE].contents()
w = gguf.GGUFWriter(dst, arch=arch, endianess=r.endianess)
for f in r.fields.values():
    if f.name == gguf.Keys.General.ARCHITECTURE or f.name.startswith("GGUF."):
        continue
    vt = f.types[0]; st = f.types[-1] if vt == gguf.GGUFValueType.ARRAY else None
    w.add_key_value(f.name, f.contents(), vt, sub_type=st)
emb = next(t for t in r.tensors if t.name == "token_embd.weight")
assert emb.tensor_type == Q.Q6_K, emb.tensor_type
assert not any(t.name == "output.weight" for t in r.tensors)
n_vocab, n_embd = int(emb.shape[1]), int(emb.shape[0])
print("token_embd", emb.shape, emb.tensor_type.name, "->", n_vocab, n_embd)
out = np.empty((n_vocab, n_embd // 32 * 18), dtype=np.uint8)
CH = 8192
for a in range(0, n_vocab, CH):
    rows = quants.dequantize(np.asarray(emb.data[a:a + CH]), Q.Q6_K).astype(np.float32)
    out[a:a + CH] = quants.quantize(rows, Q.Q4_0)
    if a % (CH * 8) == 0:
        print("rows", a, flush=True)
for t in r.tensors:
    w.add_tensor_info(t.name, t.data.shape, t.data.dtype, t.data.nbytes, t.tensor_type)
    if t.name == "token_embd.weight":
        w.add_tensor_info("output.weight", out.shape, out.dtype, out.nbytes, Q.Q4_0)
w.write_header_to_file(); w.write_kv_data_to_file(); w.write_ti_data_to_file()
for t in r.tensors:
    w.write_tensor_data(t.data, tensor_endianess=r.endianess)
    if t.name == "token_embd.weight":
        w.write_tensor_data(out, tensor_endianess=r.endianess)
w.close()
print("done", dst)
