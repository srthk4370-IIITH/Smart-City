"""Compact tool schemas (same names, arguments and enums as P0 tools.json; descriptions cut to one short sentence,
property descriptions dropped). Training and evaluation both use these. -> tools_v3.json"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "2026-10-23_reasoner_research", "P0", "host_bench"))
from tools_impl import openai_tools, CHAT_TOOLS, INCIDENT_TOOLS


def strip(o, depth=0):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k == "description" and depth > 0:
                continue
            if k in ("examples", "default", "title"):
                continue
            out[k] = strip(v, depth + 1)
        return out
    if isinstance(o, list):
        return [strip(x, depth + 1) for x in o]
    return o


def compact(tools):
    out = []
    for t in tools:
        f = t["function"]
        d = re.split(r"(?<=\.)\s", f.get("description", ""))[0][:160]
        out.append({"type": "function", "function": {"name": f["name"], "description": d, "parameters": strip(f["parameters"], 1)}})
    return out


res = {"incident": compact(openai_tools(INCIDENT_TOOLS)), "chat": compact(openai_tools(CHAT_TOOLS))}
json.dump(res, open(os.path.join(HERE, "tools_v3.json"), "w"), indent=1)
print({k: len(json.dumps(v)) for k, v in res.items()}, "chars")
