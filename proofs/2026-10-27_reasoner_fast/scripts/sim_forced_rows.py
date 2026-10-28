"""Row-cost model of the forced JSON skeleton: every forced separator chunk (keys + punctuation between values) rides
in the step of the model token before it (rows = 1 + forced tokens - 1, the last one is left to the model). Step
cost by rows from llama-bench on the board (1:66, 2:82, 3:113, 4:133, 5+:106-121 ms, HMX at > 4 rows).
Compares the current keyed layout with compact keys and a positional (keyless) layout. Model-chosen tokens are
the same in all three, so the number of steps is the same; only the row cost changes."""
import json, glob, re, sys
from tokenizers import Tokenizer
tk = Tokenizer.from_file(sys.argv[1])
COST = {1: 66, 2: 82, 3: 113, 4: 133}
cost = lambda r: COST.get(r, 106 + 1.0 * (r - 5))
KEYS = ["title","severity","label","root_cause","causal_chain","observations","agent_checks","affected_domains","suspect_sensors","evidence","confidence","checklist","monitor_next","needs_more_data","needs_deeper","explanation"]
SHORT = {k: k[:2] for k in KEYS} | {"text": "t", "src": "s", "ref": "r", "claim": "c", "verdict": "v", "fact": "f", "action": "a", "target": "g", "why": "w"}
def chunks(j, keyed=True, short=False):
    """the forced separator strings of a serialized answer (between values)"""
    def k(x): return json.dumps(SHORT[x] if short else x) + ": " if keyed else ""
    out = []; first = True
    def val(v):
        if isinstance(v, list): out.append("["); [ (out.append(", ") if i else None, val(e)) for i, e in enumerate(v)]; out.append("]")
        elif isinstance(v, dict):
            out.append("{" if keyed else "[")
            for i, (kk, vv) in enumerate(v.items()):
                out.append((", " if i else "") + k(kk)); val(vv)
            out.append("}" if keyed else "]")
    out.append("{" if keyed else "[")
    for i, kk in enumerate(KEYS):
        out.append((", " if i else "") + k(kk)); val(j[kk])
    out.append("}" if keyed else "]")
    # merge consecutive punctuation into chunks
    s = "".join(out); return [c for c in re.split(r"\x00", s) if c]
def model_cost(j, keyed, short):
    # forced chunk sizes: tokens of each separator run; estimate by tokenizing the joined separators between values
    seps = []
    def walk(v, prefix):
        pass
    txt_sep = []
    def ser(v):
        if isinstance(v, str): txt_sep.append(("V", json.dumps(v)[1:-1])); return
        if isinstance(v, (int, float, bool)) or v is None: txt_sep.append(("V", json.dumps(v))); return
        if isinstance(v, list):
            txt_sep.append(("S", "[")) 
            for i, e in enumerate(v):
                if i: txt_sep.append(("S", ", "))
                ser(e)
            txt_sep.append(("S", "]")); return
        txt_sep.append(("S", "{" if keyed else "["))
        for i, (kk, vv) in enumerate(v.items()):
            txt_sep.append(("S", (", " if i else "") + (json.dumps(SHORT[kk] if short else kk) + ": " if keyed else "")))
            ser(vv)
        txt_sep.append(("S", "}" if keyed else "]"))
    txt_sep.append(("S", "{" if keyed else "["))
    for i, kk in enumerate(KEYS):
        txt_sep.append(("S", (", " if i else "") + (json.dumps(SHORT[kk] if short else kk) + ": " if keyed else "")))
        ser(j[kk])
    txt_sep.append(("S", "}" if keyed else "]"))
    # string values carry their quotes as separators
    runs = []; cur = ""
    for t, x in txt_sep:
        if t == "S": cur += x
        else:
            if x.startswith('"') is False and isinstance(x, str) and not x[:1].isdigit() and x not in ("true", "false", "null"):
                cur += '"'; runs.append(cur); cur = ""; runs.append(("V", x)); cur = '"'
            else:
                runs.append(cur); cur = ""; runs.append(("V", x))
    runs.append(cur)
    t_ms = 0.0; steps = 0
    for r in runs:
        if isinstance(r, tuple):
            n = len(tk.encode(r[1], add_special_tokens=False).ids); steps += n; t_ms += n * COST[1]
        elif r:
            f = len(tk.encode(r, add_special_tokens=False).ids)
            # the model token before the chunk carries f-1 forced rows (1 + f - 1 = f rows)
            t_ms += cost(max(1, f)) - COST[1]
    return t_ms / 1000, steps
files = [p for p in glob.glob(sys.argv[2]) if not p.endswith("_0.json")]
tot = {"keyed": 0, "short": 0, "positional": 0}; n = 0
for p in files:
    o = next(json.loads(l) for l in open(p, encoding="utf-8") if '"outputs"' in l); j = json.loads(o["outputs"][0]["text"])
    tot["keyed"] += model_cost(j, True, False)[0]; tot["short"] += model_cost(j, True, True)[0]; tot["positional"] += model_cost(j, False, False)[0]; n += 1
print({k: round(v / n, 1) for k, v in tot.items()}, "s decode per report (model), n =", n)
