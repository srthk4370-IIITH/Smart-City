#!/usr/bin/env python3
"""Host-side probe for htpd v8 on the board (through `adb forward tcp:8091 tcp:8091`). Stdlib only.

  python3 -I probe_v8.py <out.jsonl> [--agents agents_requests.jsonl] [--fixtures reasoner_v3_fixtures.json]
                          [--schema reasoner_v3_force_schema.json] [--port 8091] [--v7 1]

Sends, one request at a time (htpd serves one connection at a time):
  1. caps                         -> must list "reason"
  2. each line of --agents        (e.g. the app's htpd_warmup.jsonl) - the v7 regression set: compare the outputs
                                  with the same file run against htpd_v7 (compare_outputs below)
  3. reason, keep=true, no schema, per fixture case  (first one = swap + prefix state "saved", later = "mem")
  4. the same with the schema     (forced keys/enums; text must parse as JSON)
  5. release                      -> agents' model back
  6. the agents set again         (outputs must equal step 2: the reload changes nothing)
Every response line (with timings) is appended to out.jsonl; nothing else is written.
"""
import json, socket, sys, time

def call(port, req, timeout=600):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while True:
        ch = s.recv(1 << 16)
        if not ch:
            break
        buf += ch
        lines = buf.split(b"\n")
        for ln in lines[:-1]:
            if ln.strip():
                o = json.loads(ln)
                if o.get("kind") not in ("toks", "tok"):
                    s.close()
                    return o
        buf = lines[-1]
    s.close()
    raise RuntimeError("connection closed without a result line")

def main():
    a = sys.argv[1:]
    out = a[0]
    opt = {a[i]: a[i + 1] for i in range(1, len(a) - 1, 2)}
    port = int(opt.get("--port", 8091))
    log = open(out, "a", encoding="utf-8")
    def rec(step, req, resp, t):
        r = {k: v for k, v in req.items() if k not in ("prompt", "prompts", "schema", "prefix")}
        log.write(json.dumps({"step": step, "req": r, "wall_ms": round(t * 1000, 1), "resp": resp}) + "\n")
        log.flush()
        return resp
    def run(step, req):
        t = time.time()
        return rec(step, req, call(port, req), time.time() - t)

    if opt.get("--v7") == "1":  # reference run against htpd_v7: the agents set only
        agents = [json.loads(l) for l in open(opt["--agents"], encoding="utf-8") if l.strip()]
        for r in agents:
            run("agents_before", r)
        return
    caps = run("caps", {"kind": "caps"})
    assert "reason" in caps.get("caps", []), caps
    agents = []
    if "--agents" in opt:
        agents = [json.loads(l) for l in open(opt["--agents"], encoding="utf-8") if l.strip()]
    first = [run("agents_before", r)["outputs"] for r in agents]
    fx = json.load(open(opt.get("--fixtures", "reasoner_v3_fixtures.json"), encoding="utf-8"))
    schema = json.load(open(opt.get("--schema", "reasoner_v3_force_schema.json"), encoding="utf-8"))
    for use_schema in (False, True):
        for i, c in enumerate(fx["cases"]):
            p = c["chat"]
            k = p.index("<|im_start|>user\n") + len("<|im_start|>user\n")
            req = {"kind": "reason", "prompt": p, "prefix": p[:k], "keep": True, "max_new": 700, "id": i}
            if use_schema:
                req["schema"] = schema
            r = run("reason_schema" if use_schema else "reason_free", req)
            o = r["outputs"][0]
            ok = None
            if o["text"].lstrip().startswith("{"):
                try:
                    json.loads(o["text"]); ok = True
                except Exception:
                    ok = False
            print(f"reason case {i} schema={use_schema}: stop {o['stop']} tokens {o['tokens']} forced {o['forced']} "
                  f"{o['ms']:.0f} ms json_ok={ok} cache={r['reason']['cache']} swapped={r['reason']['swapped']}")
    run("release", {"kind": "release"})
    again = [run("agents_after", r)["outputs"] for r in agents]
    same = all([x["text"] for x in a1] == [x["text"] for x in a2] for a1, a2 in zip(first, again))
    print(f"agents outputs identical before/after the swap: {same} ({len(agents)} requests)")

def compare_outputs(a_jsonl, b_jsonl, step="agents_before"):
    """texts of `step` in two out.jsonl files (htpd_v7 vs htpd_v8r on the same requests): identical?"""
    get = lambda f: [l["resp"]["outputs"] for l in map(json.loads, open(f, encoding="utf-8")) if l["step"] == step]
    A, B = get(a_jsonl), get(b_jsonl)
    return len(A) == len(B) and all([x["text"] for x in a] == [x["text"] for x in b] for a, b in zip(A, B))

if __name__ == "__main__":
    main()
