"""Build a LADE (lookahead decoding) Genie config from the live agent config.

LADE is draft-free speculative decoding: no draft model, no trained head, no forecast prefix. It
needs only a token graph with AR-N > 1, which is why the bundle is exported with
--sequence-lengths 128,64,1.

Qualcomm's documented constraints:
    lade.window == lade.gcap
    (lade.window + lade.gcap) * (lade.ngram - 1) <= AR-N
With window = gcap = 8 and ngram = 5:  (8 + 8) * 4 = 64, so AR-N must be >= 64. Ours is 64.

Everything else is copied from the live config so the tuned knobs survive: greedy sampler,
n-threads 4, cpu-mask 0xf0, allow-async-init, max-num-tokens, rope settings.

!! DO NOT SHIP THE OUTPUT OF THIS SCRIPT. Kept for reproducing the experiment only. !!

The original note here said "speculative decoding verifies every drafted token against the full
model, so output is identical to plain decoding by construction". That is the theory. Measured on
device 2026-10-14, it is NOT what Genie 1.20 does: over 24 role/pattern prompts the answers
diverged and degraded - "spike" decoded as "sp.peak", "oscillation" as "osc strings", PM10 swapped
for PM2.5, and a flatline sensor_fault reported as normal. Turning speculation down to the minimum
(window=gcap=4, ngram=3) still gave only 4/13 identical, and was slower than no LADE.

It is genuinely faster (decode -24%, end to end -14%), which is exactly why it is dangerous: a
single repeated prompt reproduces byte-identically and looks like a free win. See HANDBOOK 2.14.

  python make_lade_config.py <live_config.json> <out_config.json> [ar_n]
"""
import json
import sys

src, dst = sys.argv[1], sys.argv[2]
ar_n = int(sys.argv[3]) if len(sys.argv) > 3 else 64

cfg = json.load(open(src, encoding="utf-8"))
d = cfg["dialog"]

window = gcap = 8
ngram = 5
need = (window + gcap) * (ngram - 1)
if need > ar_n:
    # fall back to the largest ngram that fits the compiled AR-N
    ngram = ar_n // (window + gcap) + 1
    need = (window + gcap) * (ngram - 1)
    print(f"adjusted ngram to {ngram} so {need} <= AR-N {ar_n}")
assert need <= ar_n, f"LADE constraint violated: {need} > {ar_n}"

d["type"] = "lade"
d["lade"] = {
    "version": 1,
    "update-mode": "ALWAYS_FWD_ONE",
    "window": window,
    "ngram": ngram,
    "gcap": gcap,
}

json.dump(cfg, open(dst, "w", encoding="utf-8"), indent=2)
print(f"wrote {dst}")
print(f"  dialog.type = {d['type']}")
print(f"  lade        = window {window}, gcap {gcap}, ngram {ngram}  -> needs AR-N >= {need}")
print(f"  sampler     = {d.get('sampler')}")
print(f"  ctx size    = {d.get('context', {}).get('size')}")
