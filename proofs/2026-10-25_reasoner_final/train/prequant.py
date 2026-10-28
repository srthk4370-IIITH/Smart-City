"""One-off: save the NF4 double-quant 4-bit base (same BitsAndBytesConfig as train_rsn.py) so training loads ~3 GB, not 7-8 GB."""
import os, torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
M = os.path.expanduser("~/models/qwen3.5-4b"); O = os.path.expanduser("~/models/qwen3.5-4b-nf4")
q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
m = AutoModelForCausalLM.from_pretrained(M, dtype=torch.bfloat16, device_map={"": 0}, quantization_config=q)
m.save_pretrained(O + ".part", max_shard_size="1GB"); AutoTokenizer.from_pretrained(M).save_pretrained(O + ".part")
os.rename(O + ".part", O); print("saved", O, sum(os.path.getsize(os.path.join(O, f)) for f in os.listdir(O)) // 2**20, "MiB")
