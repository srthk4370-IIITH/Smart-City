"""CPU-only: tokenise train/dev mixes into the run folder (so the GPU job starts training immediately)."""
import os, sys
sys.argv = [sys.argv[0]] + sys.argv[1:]
import train_rsn as T
from transformers import AutoTokenizer
out = os.path.expanduser(sys.argv[1])
os.makedirs(out, exist_ok=True)
tok = AutoTokenizer.from_pretrained(T.M)
T.prep(tok, T.ROOT + "/data/train_mix.jsonl", 4096, os.path.join(out, "train_tok.pt"))
T.prep(tok, T.ROOT + "/data/dev_mix.jsonl", 4096, os.path.join(out, "dev_tok.pt"))
