"""Every tool call in the r3 training/test/dev chat rows against tools_r3.json["chat"]: known tool, required args present,
no unknown args, enum values valid, integer bounds. Also: fog-state sentence matches the row's fog field.
  python3 check_schema_r3.py  -> ../data/final/schema_check.json"""
import collections, json, os
HERE = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(HERE, "..", "data", "final")
tools = {t["function"]["name"]: t["function"]["parameters"] for t in json.load(open(os.path.join(F, "tools_r3.json")))["chat"]}

def check(name, args):
    p = tools.get(name)
    if p is None:
        return "unknown_tool"
    props = p.get("properties", {})
    for k in p.get("required", []):
        if k not in args:
            return "missing_required:" + k
    for k, v in args.items():
        if k not in props:
            return "unknown_arg:%s.%s" % (name, k)
        s = props[k]
        if "enum" in s and v not in s["enum"]:
            return "enum:%s.%s=%s" % (name, k, v)
        if s.get("type") == "array" and "enum" in s.get("items", {}):
            vs = v if isinstance(v, list) else [v]
            if any(x not in s["items"]["enum"] for x in vs):
                return "enum:%s.%s" % (name, k)
        if s.get("type") == "integer" and isinstance(v, (int, float)) and not (s.get("minimum", -1e9) <= v <= s.get("maximum", 1e9)):
            return "bounds:%s.%s" % (name, k)
        if s.get("type") == "object" and "properties" in s and isinstance(v, dict):
            if any(kk not in s["properties"] for kk in v):
                return "unknown_subarg:%s.%s" % (name, k)
            pr = v.get("preset")
            if pr is not None and pr not in s["properties"]["preset"]["enum"]:
                return "preset:%s" % pr
    return None

def row_ok(r):
    for m in r["messages"]:
        for tc in m.get("tool_calls") or []:
            a = tc["function"]["arguments"]
            if check(tc["function"]["name"], a if isinstance(a, dict) else json.loads(a)):
                return False
    return True


out = {}
for fn in (("chat_train_r3.jsonl", "dev_r3.jsonl", "chat_test_r3.jsonl") if __name__ == "__main__" else ()):
    c = collections.Counter()
    for l in open(os.path.join(F, fn), encoding="utf-8"):
        r = json.loads(l)
        if r.get("tools") != "chat":
            continue
        c["rows"] += 1
        calls = [(tc["function"]["name"], tc["function"]["arguments"]) for m in r["messages"] for tc in (m.get("tool_calls") or [])]
        calls += [(g["name"], g["args"]) for g in r.get("gold_calls", [])]
        for n, a in calls:
            c["calls"] += 1
            e = check(n, a if isinstance(a, dict) else json.loads(a))
            if e:
                c["bad:" + e] += 1
        s = r["messages"][0]["content"] if r["messages"][0]["role"] == "system" else ""
        if r.get("fog"):
            want = "fog server is reachable" if r["fog"] in ("online", "timeout") else "fog server is unreachable"
            c["fog_line_ok" if want in s else "fog_line_bad"] += 1
    out[fn] = dict(c)
    print(fn, dict(c))
if __name__ == "__main__":
    json.dump(out, open(os.path.join(F, "schema_check.json"), "w"), indent=1)
