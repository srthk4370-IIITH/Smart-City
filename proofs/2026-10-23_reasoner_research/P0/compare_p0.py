#!/usr/bin/env python3
"""P0 device analysis: reads results/device.jsonl (p0_client.py) and writes results/summary.json + prints the gates.

Gates (REASONER_DESIGN.md P0): adapter loads on HTP with no fastrpc errors; agents identical to v7 with the adapter
loaded (within the run-to-run floor: v7 r1 vs r2); synth with "lora":false identical to v7; decode overhead of the
adapter <= 10 % per token; adapter on changes the synth text (it is a real 3d-v2 delta, so small changes) and is
compared with the host CPU reference (host/results.json, B_v8_lora) for parity.
usage: py -3 compare_p0.py [--dir results] [--host host/results.json]
"""
import argparse, difflib, json, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(HERE, "results"))
    ap.add_argument("--host", default=os.path.join(HERE, "host", "results.json"))
    a = ap.parse_args()
    toks = json.load(open(os.path.join(HERE, "device_inputs", "prompt_tokens.json")))
    rows = [json.loads(l) for l in open(os.path.join(a.dir, "device.jsonl"), encoding="utf-8")]
    R = {}
    for r in rows:
        if "resp" in r:
            R.setdefault(r["tag"], {}).setdefault(r["name"], []).append(r)
    texts = lambda tag, n, k=0: [o["text"] for o in R[tag][n][k]["resp"]["outputs"]]

    def speed(tag, n):
        out = []
        for r in R.get(tag, {}).get(n, []):
            o = r["resp"]["outputs"][0]
            dt = (o["ms"] - o["ttft_ms"]) / 1000
            pm = r["resp"].get("prefill_ms") or 0
            out.append({"decode_tok_s": (o["tokens"] - 1) / dt if dt > 0 else None, "tokens": o["tokens"],
                        "prefill_ms": pm, "prefill_tok_s": toks[n][0] / (pm / 1000) if pm else None, "ms": o["ms"],
                        "lora_scale": r["resp"].get("lora_scale")})
        return out

    S = {"phases": sorted(R)}
    agent_names = [n for n in ("agents0", "agents1", "agents2", "agents10") if n in R.get("v7_r1", {})]
    # identity of agent texts
    def same(t1, n1, t2, n2, k1=0, k2=0):
        x, y = texts(t1, n1, k1), texts(t2, n2, k2)
        return sum(p == q for p, q in zip(x, y)), len(x)
    tot = lambda pairs: (sum(p[0] for p in pairs), sum(p[1] for p in pairs))
    if "v7_r2" in R:
        S["agents_floor_v7_r1_vs_r2"] = tot([same("v7_r1", n, "v7_r2", n) for n in agent_names if n in R["v7_r2"]])
    if "v8lora" in R:
        S["agents_v8lora_vs_v7_r1"] = tot([same("v8lora", n, "v7_r1", n) for n in agent_names if n in R["v8lora"]])
        if len(R["v8lora"].get("agents0", [])) > 1:
            S["agents0_after_lora_synth_vs_v7"] = same("v8lora", "agents0", "v7_r1", "agents0", 1, 0)
        syn = [n for n in ("synth0", "synth1", "synth2") if n in R["v7_r1"]]
        S["synth_off_vs_v7"] = {n: texts("v8lora", n + "_off")[0] == texts("v7_r1", n)[0] for n in syn if n + "_off" in R["v8lora"]}
        S["synth_on_vs_off"] = {n: {"identical": texts("v8lora", n + "_on")[0] == texts("v8lora", n + "_off")[0],
                                    "similarity": round(difflib.SequenceMatcher(None, texts("v8lora", n + "_on")[0], texts("v8lora", n + "_off")[0]).ratio(), 4)}
                                for n in syn if n + "_on" in R["v8lora"]}
        on = [s["decode_tok_s"] for n in syn for s in speed("v8lora", n + "_on") if s["decode_tok_s"]]
        off = [s["decode_tok_s"] for n in syn for s in speed("v8lora", n + "_off") if s["decode_tok_s"]]
        pon = [s["prefill_tok_s"] for n in syn for s in speed("v8lora", n + "_on") if s["prefill_tok_s"]]
        poff = [s["prefill_tok_s"] for n in syn for s in speed("v8lora", n + "_off") if s["prefill_tok_s"]]
        S["speed"] = {n: {"on": speed("v8lora", n + "_on"), "off": speed("v8lora", n + "_off"), "v7": speed("v7_r1", n)} for n in syn}
        if on and off:
            S["decode_tok_s_median"] = {"off": statistics.median(off), "on": statistics.median(on),
                                        "overhead_pct": 100 * (statistics.median(off) / statistics.median(on) - 1)}
        if pon and poff:
            S["prefill_tok_s_median"] = {"off": statistics.median(poff), "on": statistics.median(pon),
                                         "overhead_pct": 100 * (statistics.median(poff) / statistics.median(pon) - 1)}
        # parity with the host CPU reference for the same model + adapter (texts are expected to be close, not
        # byte-identical: HTP and CPU numerics differ, as they already do for the base model)
        if os.path.exists(a.host):
            H = json.load(open(a.host))
            if "B_v8_lora" in H:
                par = {}
                for n in ("synth0", "synth1"):
                    for m in ("_on", "_off"):
                        hk = n + m
                        if hk in H["B_v8_lora"] and hk in R["v8lora"]:
                            h = H["B_v8_lora"][hk]["resp"]["outputs"][0]["text"]
                            d = texts("v8lora", hk)[0]
                            par[hk] = {"identical": h == d, "similarity": round(difflib.SequenceMatcher(None, h, d).ratio(), 4)}
                S["device_vs_host_cpu"] = par
    json.dump(S, open(os.path.join(a.dir, "summary.json"), "w"), indent=1)
    print(json.dumps(S, indent=1)[:5000])


if __name__ == "__main__":
    main()
