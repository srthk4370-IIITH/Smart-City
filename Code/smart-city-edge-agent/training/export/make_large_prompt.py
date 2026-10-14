"""Build a LARGE synthesizer prompt (chaos-scale) from a real one, for the context-window gate.

Takes a real synthesizer prompt recorded by the app and appends copies of its sensor blocks under
new refs until it is about as big as an "every sensor haywire" incident (~18 sensors), so it no
longer fits the ctx-2048 window and must run on the ctx-4096 bundle.

  python make_large_prompt.py INC-0020 large_prompt.txt [target_tokens]
"""
import json
import re
import sys
import urllib.request

iid, out = sys.argv[1], sys.argv[2]
target = int(sys.argv[3]) if len(sys.argv) > 3 else 3200
d = json.load(urllib.request.urlopen(f"http://127.0.0.1:8000/api/incidents/{iid}", timeout=20))
p = (d.get("final") or {}).get("prompt") or ""
head, rest = p.split("DOMAIN AGENT FINDINGS:\n", 1)
body, tail = rest.split("Combine these findings", 1)
blocks = re.split(r"(?m)^(?=S\d+ \[)", body)
blocks = [b for b in blocks if b.strip()]
n = len(blocks)
extra, k = [], n
while (len(head) + len(body) + sum(map(len, extra)) + len(tail)) * 100 // 310 < target:
    src = blocks[len(extra) % n]
    old = re.match(r"S(\d+)", src).group(1)
    k += 1
    extra.append(re.sub(rf"\bS{old}\b", f"S{k}", src))
prompt = head + "DOMAIN AGENT FINDINGS:\n" + body + "".join(extra) + "Combine these findings" + tail
open(out, "w", encoding="utf-8").write(prompt)
print(f"{n} real sensor blocks + {len(extra)} copies = {n + len(extra)} sensors, ~{len(prompt) * 100 // 310} tokens -> {out}")
