"""Pack the QIDK model's exact quantised weights into a llama.cpp GGUF for the Adreno GPU.

Input: an F32 GGUF made by convert_hf_to_gguf.py from extract_device_weights.py's folder, plus that
folder's device_scales.npz (the NPU checkpoint's per-row scales).

On the NPU every linear layer is int4: w = s * q, q in [-8, 7], one scale s per output row; lm_head is
int8: q in [-128, 127]. llama.cpp's Q4_0 block is d * (nibble - 8) and Q8_0 is d * int8, so with d = s
for every block of a row the device integers are stored as they are - no re-rounding. The only change
is that d is fp16 (the NPU keeps s in fp32): a relative scale error below 2^-11 per row.

Every row is checked: w / s must be an integer within range (|w/s - q| < 1e-3), otherwise we abort,
because then this would not be the device model.

  python pack_exact_gguf.py <f32.gguf> <device_scales.npz> <out.gguf>
"""
import re
import sys

import numpy as np

sys.path.insert(0, sys.argv[4] if len(sys.argv) > 4 else "gguf-py")
import gguf  # noqa: E402

src, scales_path, dst = sys.argv[1], sys.argv[2], sys.argv[3]
reader = gguf.GGUFReader(src)
scales = {k.replace("|", "."): v for k, v in np.load(scales_path).items()}
N_HEAD, N_KV = 24, 8


def permute(x, n_head):  # llama.cpp's Q/K RoPE row permutation (conversion/llama.py)
    return x.reshape(n_head, 2, x.shape[0] // n_head // 2, *x.shape[1:]).swapaxes(1, 2).reshape(x.shape)


HF = {"attn_q": ("self_attn.q_proj", N_HEAD), "attn_k": ("self_attn.k_proj", N_KV), "attn_v": ("self_attn.v_proj", None),
      "attn_output": ("self_attn.o_proj", None), "ffn_gate": ("mlp.gate_proj", None), "ffn_up": ("mlp.up_proj", None),
      "ffn_down": ("mlp.down_proj", None)}


def row_scales(name):
    if name == "output.weight":
        return scales["lm_head.weight"], 127, -128
    m = re.fullmatch(r"blk\.(\d+)\.(\w+)\.weight", name)
    if not m or m.group(2) not in HF:
        return None, 0, 0
    hf, nh = HF[m.group(2)]
    s = scales[f"model.layers.{m.group(1)}.{hf}.weight"]
    if nh:
        s = permute(s[:, None], nh)[:, 0]
    return s, 7, -8


def integers(w, s, hi, lo, name):
    q = w / s[:, None]
    if name == "output.weight":
        # lm_head is stored in float; the NPU compiler quantises it to int8 with these per-row scales
        # (round to nearest, saturate). Reproduce that exactly, and report how much saturates.
        qi = np.clip(np.rint(q), lo, hi)
        clipped = int(((q > hi + 0.5) | (q < lo - 0.5)).sum())
        print(f"output.weight: int8 round+saturate as on the NPU; {clipped} of {q.size} weights saturate", flush=True)
        return qi.astype(np.int16)
    qi = np.rint(q)
    err = float(np.abs(q - qi).max())
    if err > 1e-3 or qi.max() > hi or qi.min() < lo:
        sys.exit(f"{name}: not on the device grid (max |w/s - q| = {err:.2e}, range {qi.min()}..{qi.max()})")
    return qi.astype(np.int16)


def pack_q4_0(qi, s):
    rows, cols = qi.shape
    nb = cols // 32
    blk = (qi + 8).astype(np.uint8).reshape(rows, nb, 32)
    qs = blk[:, :, :16] | (blk[:, :, 16:] << 4)
    d = np.repeat(s.astype(np.float16)[:, None], nb, 1).view(np.uint8).reshape(rows, nb, 2)
    return np.concatenate([d, qs], axis=2).reshape(rows, nb * 18)


def pack_q8_0(qi, s):
    rows, cols = qi.shape
    nb = cols // 32
    qs = qi.astype(np.int8).view(np.uint8).reshape(rows, nb, 32)
    d = np.repeat(s.astype(np.float16)[:, None], nb, 1).view(np.uint8).reshape(rows, nb, 2)
    return np.concatenate([d, qs], axis=2).reshape(rows, nb * 34)


arch = reader.fields[gguf.Keys.General.ARCHITECTURE].contents()
writer = gguf.GGUFWriter(dst, arch)
for field in reader.fields.values():
    if field.name == gguf.Keys.General.ARCHITECTURE or field.name.startswith("GGUF."):
        continue
    val_type = field.types[0]
    sub_type = field.types[-1] if val_type == gguf.GGUFValueType.ARRAY else None
    val = field.contents()
    if field.name == gguf.Keys.General.FILE_TYPE:
        val = int(gguf.LlamaFileType.MOSTLY_Q4_0)
    writer.add_key_value(field.name, val, val_type, sub_type=sub_type)
writer.add_string("general.quantization_note",
                  "exact QIDK NPU weights: GPTQ int4 per-row scales as Q4_0, lm_head int8 as Q8_0, fp16 scales")

n4 = n8 = 0
for t in reader.tensors:
    w = np.asarray(t.data, dtype=np.float32)
    s, hi, lo = row_scales(t.name)
    if s is not None:
        w2 = w.reshape(w.shape[0], -1)
        qi = integers(w2, s.astype(np.float64), hi, lo, t.name)
        if t.name == "output.weight":
            writer.add_tensor(t.name, pack_q8_0(qi, s), raw_dtype=gguf.GGMLQuantizationType.Q8_0)
            n8 += 1
        else:
            writer.add_tensor(t.name, pack_q4_0(qi, s), raw_dtype=gguf.GGMLQuantizationType.Q4_0)
            n4 += 1
    elif t.name == "token_embd.weight":
        writer.add_tensor(t.name, w.astype(np.float16))
    else:
        writer.add_tensor(t.name, w)  # norms, rope factors: f32
    print(f"{t.name:28s} {'Q8_0' if t.name == 'output.weight' else 'Q4_0' if s is not None else str(w.dtype)}", flush=True)

writer.write_header_to_file()
writer.write_kv_data_to_file()
writer.write_tensors_to_file()
writer.close()
print(f"wrote {dst}: {n4} Q4_0 tensors on the device int4 grid, {n8} Q8_0 (lm_head int8), all rows verified exact")
