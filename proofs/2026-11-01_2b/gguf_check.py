#!/usr/bin/env python3
"""gguf_check.py <new.gguf> <ref.gguf>: header-only GGUF comparison (memmap, no tensor data read) for a reasoner swap.
htpd_v9f reads the speculative-draft corpora (reason_corpus_v2 / live / chat) as raw token ids, so the new model must
have the SAME tokenizer as rsn_v1. Prints one JSON line; exit 0 = compatible (same arch qwen35, same vocab + token
table md5 + eos), 1 = not. Needs numpy + llama.cpp gguf-py (GGUF_PY, default ~/gpu_work/llama.cpp/gguf-py)."""
import hashlib, json, os, sys
sys.path.insert(0, os.environ.get("GGUF_PY", os.path.expanduser("~/gpu_work/llama.cpp/gguf-py")))
from gguf import GGUFReader

def meta(p):
    r = GGUFReader(p); o = {"file": os.path.basename(p), "bytes": os.path.getsize(p)}
    for k, f in r.fields.items():
        if k == "tokenizer.ggml.tokens":
            t = [bytes(f.parts[i]) for i in f.data]; o["n_vocab"] = len(t); o["tok_md5"] = hashlib.md5(b"\0".join(t)).hexdigest()
        elif k in ("general.architecture",):
            o["arch"] = bytes(f.parts[f.data[0]]).decode()
        elif k.endswith((".block_count", ".embedding_length", ".attention.head_count_kv", ".full_attention_interval")) or k == "tokenizer.ggml.eos_token_id":
            o[k.split(".", 1)[-1] if not k.startswith("tokenizer") else "eos"] = int(f.parts[f.data[0]][0])
    return o

n, b = meta(sys.argv[1]), meta(sys.argv[2])
ok = n.get("arch") == "qwen35" and all(n.get(k) == b.get(k) for k in ("arch", "n_vocab", "tok_md5", "eos"))
print(json.dumps({"ok": ok, "new": n, "ref": b}))
sys.exit(0 if ok else 1)
