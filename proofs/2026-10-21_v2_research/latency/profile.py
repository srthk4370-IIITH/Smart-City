"""Paper profile of v2 vs v1 agent latency on htpd, from logs already on the laptop (no device access).

Run (WSL, tokenizers venv):
  ~/venvs/train/bin/python profile.py > profile_out.txt
Reads:
  proofs/2026-10-20_v2_post/device/{test_all,host400}/samples.jsonl  (v2: prefill_ms, batch_s, tokens per batch of 8)
  proofs/2026-10-20_v2_post/device/placement_v2/{prompts,samples}.jsonl (v2 prompts at n=48/96/144)
  proofs/2026-10-16_window_study/{prompts,samples}.jsonl               (v1 on htpd: prompt_tokens, prefill_ms)
Writes profile.json next to this script.
"""
import json, os, statistics as st, collections, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
P = lambda *a: os.path.join(ROOT, "proofs", *a)
from tokenizers import Tokenizer
tok = Tokenizer.from_file(os.path.expanduser("~/models/llama-3.2-3b-instruct/tokenizer.json"))
ntok = lambda s: len(tok.encode(s, add_special_tokens=False).ids)
EOT = "<|eot_id|>"

def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]

def batches(rows):
    b = collections.OrderedDict()
    for r in rows:
        b.setdefault((r.get("batch_s"), r.get("prefill_ms"), r.get("batch")), []).append(r)
    return list(b.values())

out = {}

# ---- v2 prefill/decode split by window length (test_all + host400 carry prefill_ms)
split = collections.defaultdict(list)
for f in ["test_all", "host400"]:
    for rs in batches(jl(P("2026-10-20_v2_post", "device", f, "samples.jsonl"))):
        if rs[0].get("prefill_ms") is None:
            continue
        bs, pf = rs[0]["batch_s"], rs[0]["prefill_ms"] / 1000
        n = max(r["n"] for r in rs)
        bucket = "<=48" if n <= 48 else "<=96" if n <= 96 else "<=144"
        split[bucket].append(dict(bs=bs, pf=pf, dec=bs - pf, size=len(rs), maxtok=max(r["tokens"] for r in rs),
                                  meantok=st.mean(r["tokens"] for r in rs)))
out["v2_split"] = {}
for k, v in sorted(split.items()):
    v8 = [x for x in v if x["size"] == 8] or v
    d = dict(batches=len(v8), batch_s=st.median(x["bs"] for x in v8), prefill_s=st.median(x["pf"] for x in v8),
             decode_s=st.median(x["dec"] for x in v8), max_tokens=st.median(x["maxtok"] for x in v8),
             mean_tokens=round(st.mean(x["meantok"] for x in v8), 1))
    d["decode_ms_per_step"] = round(1000 * d["decode_s"] / d["max_tokens"], 1)
    d["prefill_share"] = round(d["prefill_s"] / d["batch_s"], 3)
    out["v2_split"][k] = d

# ---- v2 prompt token counts and shared-prefix structure (placement prompts)
pr = jl(P("2026-10-20_v2_post", "device", "placement_v2", "prompts.jsonl"))
by_n = collections.defaultdict(list)
sys_len = collections.defaultdict(set)
role_of = {c["id"]: c["role"] for c in jl(P("2026-10-20_v2_post", "device", "placement_v2", "cases.jsonl"))}
seen = set()
sample_prompt = {}
for r in pr:
    key = (r["id"], r["n"], r.get("d"))
    if key in seen:
        continue
    seen.add(key)
    p = r["prompt"]
    t = tok.encode(p, add_special_tokens=False).ids
    by_n[r["n"]].append(len(t))
    i = p.find(EOT)
    sys_len[role_of.get(r["id"], "?")].add(ntok(p[: i + len(EOT)]))
    sample_prompt.setdefault(r["n"], p)
out["v2_prompt_tokens"] = {n: dict(count=len(v), median=st.median(v), max=max(v), min=min(v)) for n, v in sorted(by_n.items())}
out["v2_system_turn_tokens_by_role"] = {k: sorted(v) for k, v in sys_len.items()}

# section sizes of one prompt per n (where the tokens go)
def sections(p):
    i = p.find(EOT)
    user = p[i + len(EOT):]
    res = {"system_turn": ntok(p[: i + len(EOT)])}
    lines = user.split("\n")
    buckets = collections.OrderedDict()
    for ln in lines:
        m = re.match(r"^\s*([A-Za-z0-9_.#]+)\s*[:=]", ln)
        k = m.group(1)[:24] if m else (ln[:18] or "<blank>")
        buckets[k] = buckets.get(k, 0) + ntok(ln + "\n")
    res["user_lines"] = dict(sorted(buckets.items(), key=lambda kv: -kv[1])[:12])
    res["total"] = ntok(p)
    return res
out["v2_prompt_sections"] = {n: sections(p) for n, p in sorted(sample_prompt.items())}
with open(os.path.join(os.path.dirname(__file__), "v2_prompt_example_n144.txt"), "w", encoding="utf-8") as fh:
    fh.write(sample_prompt.get(144, ""))

# ---- v2 output: which tokens are forced (identical across all outputs at that position in the scaffold)
smp = jl(P("2026-10-20_v2_post", "device", "placement_v2", "samples.jsonl"))
texts = [s["text"] for s in smp]
keys_re = re.compile(r'"(pattern|status|observations|likely_cause|confidence|event_active|onset|fault_kind|recommended_action|action)"')
scaffold_tok = []
for t in texts:
    total = ntok(t)
    # tokens of the fixed key strings + punctuation between values ("{\"pattern\": \"", "\", \"status\": \"", ...)
    skel = re.sub(r'(:\s*)"(?:[^"\\]|\\.)*"', r'\1""', t)            # blank string values
    skel = re.sub(r'(:\s*)\[[^\]]*\]', r'\1[]', skel)                   # blank arrays
    skel = re.sub(r'(:\s*)(-?[0-9.]+|true|false|null)', r'\1', skel)  # blank scalars
    scaffold_tok.append((total, ntok(skel)))
out["v2_output_tokens"] = dict(mean=round(st.mean(a for a, _ in scaffold_tok), 1),
                               scaffold_mean=round(st.mean(b for _, b in scaffold_tok), 1),
                               scaffold_share=round(st.mean(b / a for a, b in scaffold_tok), 3))
order = collections.Counter(tuple(keys_re.findall(t)) for t in texts)
out["v2_key_orders_top"] = [[list(k), c] for k, c in order.most_common(6)]

# ---- v1 baseline from the window study (htpd, v1 model)
w = jl(P("2026-10-16_window_study", "samples.jsonl"))
v1 = collections.defaultdict(list)
for rs in batches(w):
    n = rs[0]["n"]
    v1[n].append(dict(bs=rs[0]["batch_s"], pf=rs[0]["prefill_ms"] / 1000, pt=st.mean(r.get("prompt_tokens", 0) for r in rs),
                      size=len(rs), maxtok=max(r["tokens"] for r in rs), meantok=st.mean(r["tokens"] for r in rs)))
out["v1_window_study"] = {}
for n, v in sorted(v1.items()):
    v8 = [x for x in v if x["size"] == 8] or v
    out["v1_window_study"][n] = dict(batches=len(v8), batch_s=st.median(x["bs"] for x in v8), prefill_s=st.median(x["pf"] for x in v8),
                                     decode_s=round(st.median(x["bs"] - x["pf"] for x in v8), 2),
                                     prompt_tokens=round(st.median(x["pt"] for x in v8)), max_tokens=st.median(x["maxtok"] for x in v8),
                                     mean_tokens=round(st.mean(x["meantok"] for x in v8), 1))

json.dump(out, open(os.path.join(os.path.dirname(__file__), "profile.json"), "w"), indent=1)
print(json.dumps(out, indent=1))
