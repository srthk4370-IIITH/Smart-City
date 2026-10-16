import json, socket, time, sys
W = r"C:\Users\hp\Desktop\qidk\proofs\2026-10-16_hw_grid"
tag = sys.argv[1]; base = sys.argv[2] if len(sys.argv) > 2 else None
OUT = r"C:\Users\hp\AppData\Local\Temp\claude\C--Users-hp-Desktop-qidk\125df7ac-c9eb-46de-b63b-ce87f4c7e8ce\scratchpad\ab_%s.json"
def call(req):
    s = socket.create_connection(("127.0.0.1", 8091), timeout=300); s.sendall((json.dumps(req)+"\n").encode()); b=b""
    while not b.endswith(b"\n"):
        d=s.recv(1<<20)
        if not d: break
        b+=d
    s.close(); return json.loads(b)
res = {}; tot = 0
for rep in range(2):
    for iid in ["INC-0384","INC-0116","INC-0401"]:
        d = json.load(open(W + rf"\workload_{iid}.json", encoding="utf-8"))
        ags=[a for a in d["agents"] if a.get("prompt")]
        r = call({"kind":"agents","prompts":[a["prompt"] for a in ags]})
        if rep == 1:
            res[iid] = [o["text"] for o in r["outputs"]]; tot += r["total_ms"]
            print(f"{tag} {iid}: {len(ags)} agents {r['total_ms']/1e3:.1f}s prefill {r['prefill_ms']/1e3:.1f}s")
json.dump(res, open(OUT % tag, "w"))
print(f"{tag} total (rep2) {tot/1e3:.1f}s")
if base:
    b = json.load(open(OUT % base)); n = sum(len(v) for v in res.values())
    same = sum(x == y for k in res for x, y in zip(res[k], b[k]))
    print(f"{tag}: identical to {base}: {same}/{n}")
