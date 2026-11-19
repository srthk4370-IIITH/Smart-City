"""make_synth.py OUT_DIR BASE_TOKENIZER_DIR: tiny SYNTHETIC agt_v3 sample in the design schema (V3_DESIGN.md §2.2) + a tiny random
Llama (same tokenizer) for the offline dry run / CPU smoke. Not training data: shapes only.
-> OUT/data/agt_v3/{train,dev}.jsonl, OUT/data/calib_stats.json, OUT/data/agt_v3/gate/*.jsonl, OUT/tiny_llama/"""
import json
import os
import random
import shutil
import sys

out, tokdir = sys.argv[1], sys.argv[2]
rng = random.Random(0)
D = os.path.join(out, "data", "agt_v3")
os.makedirs(os.path.join(D, "gate"), exist_ok=True)
SYS = ("You are the {d} agent of a smart-campus edge monitor. You receive one sensor's CARD and a 4-hour window with evidence "
       "E1..E10. Judge the data first. Reply with one JSON object only.")
ROLES = ["power", "water", "air_quality", "weather", "hvac"]
FAMS = ["existing", "b50_holes", "calm", "unseen_metric", "dq_edge"]
ST = ["normal", "normal", "warning", "critical", "sensor_fault"]
PAT = ["stable", "gradual_increase", "spike", "flatline", "gradual_decrease"]
STAGES = ["40min", "1.5h", "3h"]


def row(i, split, fam=None, role=None, extra=None):
    role = role or ROLES[i % len(ROLES)]
    fam = fam or FAMS[i % len(FAMS)]
    st, pat = ST[i % len(ST)], PAT[(i // 2) % len(PAT)]
    v = round(400 + rng.random() * 1200)
    user = ("CARD: CO2 concentration [ppm], continuous, indoor room\n  normal 400-1000 | warning above 1000 | critical above 1500\n"
            "NODE: SYN-%s-%03d\nWINDOW: Thu 22 Oct 10:40 -> 14:35 IST, 48 x 5 min\nSERIES (10-min means): %s\nEVIDENCE:\nE1 last = %d ppm\n"
            "E4 trend = +%d ppm/h" % (role[:2].upper(), i, " ".join(str(v + 7 * k) for k in range(24)), v, rng.randint(1, 400)))
    gold = {"pattern": pat, "status": st,
            "data_quality": {"verdict": "fault" if st == "sensor_fault" else "ok", "why": "noise normal", "src": ["E8"]},
            "severity_reason": "E1 %d ppm vs card limits" % v, "evidence": ["E1", "E4"], "observations": ["CO2 at %d ppm [E1]" % v],
            "likely_cause": "occupancy_load", "confidence": 0.8, "event_active": st != "normal", "onset": "11:10"}
    if st == "sensor_fault":
        gold["fault_kind"] = "stuck"
    gold["action"] = "monitor"
    r = {"id": "%s-%05d" % (split, i), "family": fam, "role": role, "split": split, "synthetic": True, "source": "synthetic",
         "stage": STAGES[i % 3], "system": SYS.format(d=role), "user": user, "gold": gold,
         "slices": (["calm_or_routine"] if fam == "calm" else []) + (["young_k"] if i % 7 == 0 else [])}
    r.update(extra or {})
    return r


def v2(r):
    """the same window as a B50-style v2 row (prompt/completion, compact gold without data_quality)"""
    g = {k: r["gold"][k] for k in ("pattern", "status", "observations", "likely_cause", "confidence", "event_active", "onset", "action")}
    if g["status"] == "sensor_fault":
        g["status"] = "warning"
    return {"id": r["id"] + "-v2", "pair_id": r["id"], "role": r["role"], "family": r["family"], "stage": r["stage"], "slices": r["slices"],
            "system": "You are the %s agent (v2 prompt)." % r["role"], "user": r["user"].split("\n", 2)[2],
            "completion": json.dumps(g)}


def dump(name, rows):
    with open(os.path.join(D, name), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


dump("train.jsonl", [row(i, "train") for i in range(48)])
dump("dev.jsonl", [row(i, "dev") for i in range(12)])
json.dump({"co2": {"noise_sigma": 6.1, "diurnal_profile_5min": [round(420 + 3 * k, 1) for k in range(288)],
                   "jump_quantiles": {"p50": 3, "p99": 60}}}, open(os.path.join(out, "data", "calib_stats.json"), "w"))
G = os.path.join(D, "gate")
gd = [row(i, "g", role=["power", "water"][i % 2] if i % 3 else None, extra={"pair_id": "g-%05d" % i}) for i in range(40)]
for nm, rows_ in (("dev3f", gd), ("e1", [row(i, "e1", extra={"safety": i < 16}) for i in range(20)]),
                  ("test_campus", [row(i, "c") for i in range(10)]), ("test_unseen_layout", [row(i, "ul") for i in range(10)])):
    with open(os.path.join(G, nm + "_v3.jsonl" if nm in ("dev3f", "e1", "test_campus") else os.path.join(G, nm + ".jsonl")), "w") as f:
        for r in rows_:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(G, nm + "_b50.jsonl"), "w") as f:
        for r in rows_:
            f.write(json.dumps(v2(r)) + "\n")
dump("gate/test_unseen_metric.jsonl", [row(i, "um", fam="unseen_metric") for i in range(10)])
dump("gate/calm_fault_v3.jsonl", [row(i, "cf") for i in range(10)])
ren = []
for i in range(10):
    b = row(i, "rn")
    for var in ("orig", "ren", "rep"):
        r = dict(b, id="%s-%s" % (b["id"], var), base_id=b["id"], variant=var)
        if var == "ren":
            r["user"] = r["user"].replace("SYN-", "BX-")
        ren.append(r)
dump("gate/rename_v3.jsonl", ren)

# tiny random Llama with the real Llama-3.2 tokenizer (CPU smoke only)
import torch  # noqa: E402
from transformers import LlamaConfig, LlamaForCausalLM  # noqa: E402
tdir = os.path.join(out, "tiny_llama")
cfg = LlamaConfig(vocab_size=128256, hidden_size=64, intermediate_size=128, num_hidden_layers=2, num_attention_heads=4,
                  num_key_value_heads=2, max_position_embeddings=2048, tie_word_embeddings=True, bos_token_id=128000,
                  eos_token_id=[128001, 128009])
torch.manual_seed(0)
LlamaForCausalLM(cfg).to(torch.bfloat16).save_pretrained(tdir)
for f in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"):
    shutil.copy(os.path.join(tokdir, f), tdir)
print("synthetic sample + tiny llama ->", out)
