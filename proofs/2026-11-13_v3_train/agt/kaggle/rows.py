"""rows.py: agt_v3 row handling shared by the Kaggle trainer, the laptop push checks, the dev selection and the gate.

Row schema (V3_DESIGN.md §2.2 / §4.2; the data builder in proofs/2026-11-13_v3_data/ owns the exact bytes). Accepted forms:
  A) {"id", "prompt": <full device text, Llama-3 template, starts with <|begin_of_text|>, ends with the assistant header>,
      "completion": <gold JSON text>[<|eot_id|>], ...}            (same as the v2 SFT rows)
  B) {"id", "system", "user", "gold": {...} | "completion": "..."}  (rendered here with the device's plain Llama-3 template,
      no "Cutting Knowledge" preamble: byte-equal to today's agent prompts)
Optional keys used for slices / quotas: family, role|domain, split, stage, variant, base_id, slices (list), synthetic, source.
Gold JSON keys (v3): pattern, status, data_quality{verdict,...}, severity_reason, evidence, observations, likely_cause,
confidence, event_active, onset, fault_kind?, action (last: the htpd stop rule cuts at '"action"').
"""
import json
import math
import re

BOS = "<|begin_of_text|>"
EOT = "<|eot_id|>"
JSON_SEP = (", ", ": ")      # used only when a row carries a gold dict (form B without completion text)


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def render(system, user):
    return (BOS + "<|start_header_id|>system<|end_header_id|>\n\n" + system + EOT +
            "<|start_header_id|>user<|end_header_id|>\n\n" + user + EOT +
            "<|start_header_id|>assistant<|end_header_id|>\n\n")


def norm(r):
    """-> dict(id, prompt, completion (ends with <|eot_id|>), gold (dict), family, role, slices)"""
    if "prompt" in r:
        prompt = r["prompt"]
    elif "system" in r and "user" in r:
        prompt = render(r["system"], r["user"])
    elif "messages" in r:
        m = {x["role"]: x["content"] for x in r["messages"]}
        prompt = render(m["system"], m["user"])
        r = dict(r, completion=r.get("completion", m.get("assistant")))
    else:
        raise ValueError("row %s: no prompt / system+user / messages" % r.get("id"))
    comp = r.get("completion")
    if comp is None:
        g = r.get("gold") or r.get("output")
        if g is None:
            raise ValueError("row %s: no completion / gold" % r.get("id"))
        comp = g if isinstance(g, str) else json.dumps(g, separators=JSON_SEP, ensure_ascii=False)
    if not comp.endswith(EOT):
        comp += EOT
    gold = r.get("gold") if isinstance(r.get("gold"), dict) else parse(comp[:-len(EOT)])
    if gold is None:
        raise ValueError("row %s: gold completion is not valid JSON" % r.get("id"))
    role = r.get("role") or r.get("domain") or (r.get("card") or {}).get("domain") or "unknown"
    return {"id": str(r["id"]), "prompt": prompt, "completion": comp, "gold": gold, "family": r.get("family", "none"),
            "role": role, "stage": r.get("stage"), "variant": r.get("variant"), "base_id": r.get("base_id"),
            "slices": list(r.get("slices") or r.get("slices_all") or []), "raw": r}


def prefill(completion):
    """the forced JSON prefix the device sends, e.g. '{"pattern": "' (taken from the gold so it matches the trained bytes)"""
    m = re.match(r'\{\s*"pattern"\s*:\s*"', completion)
    return m.group(0) if m else '{"pattern": "'


def cut_at_action(text):
    i = text.find('"action"')
    return text if i < 0 else text[:i]


def parse(text):
    """model text (prefill + continuation, maybe cut at '"action"') -> dict or None"""
    t = text.replace(EOT, "").strip()
    for cand in (t, None):
        if cand is None:
            c = cut_at_action(t).rstrip().rstrip(",").rstrip()
            cand = c + "}"
        try:
            d = json.loads(cand)
            return d if isinstance(d, dict) else None
        except Exception:     # noqa: BLE001
            pass
    return None


def fields(d):
    d = d or {}
    dq = d.get("data_quality")
    return {"pattern": d.get("pattern"), "status": d.get("status"), "cause": d.get("likely_cause"),
            "dq": dq.get("verdict") if isinstance(dq, dict) else None, "fault_kind": d.get("fault_kind")}


def score(gold, text):
    """per-row booleans; json = parse ok. dq is None when the gold has no data_quality (v2 / B50 rows)."""
    p = parse(text)
    g, q = fields(gold), fields(p)
    s = {"json": p is not None}
    for k in ("pattern", "status", "cause"):
        s[k] = p is not None and q[k] == g[k]
    s["dq"] = None if g["dq"] is None else (p is not None and q["dq"] == g["dq"])
    s["gold_status"], s["pred_status"] = g["status"], q["status"]
    s["gold_pattern"], s["pred_pattern"] = g["pattern"], q["pattern"]
    return s


def gen_score(scored):
    """composite dev score used for early stop / selection (status first: the measured B50 holes are severity)"""
    if not scored:
        return 0.0
    w = {"status": 0.4, "pattern": 0.3, "cause": 0.15, "dq": 0.15}
    tot = 0.0
    for s in scored:
        ww = {k: v for k, v in w.items() if s.get(k) is not None}
        tot += sum(v * bool(s[k]) for k, v in ww.items()) / sum(ww.values())
    return tot / len(scored)


def binom_two_sided(w, l):
    n = w + l
    if n == 0:
        return 1.0
    k = min(w, l)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def holm(pvals, alpha=0.05):
    """{name: p} -> set of names rejected by Holm-Bonferroni"""
    order = sorted(pvals.items(), key=lambda kv: kv[1])
    m, rej = len(order), set()
    for i, (k, p) in enumerate(order):
        if p <= alpha / (m - i):
            rej.add(k)
        else:
            break
    return rej


def provenance_problem(r, name):
    """None if the row may leave the laptop (synthetic only); else the reason"""
    src = str(r.get("source", "synthetic")).lower()
    if r.get("synthetic") is False or src.startswith("real") or "heldout" in src or "campus" in src:
        return "%s row %s: source=%s synthetic=%s" % (name, r.get("id"), r.get("source"), r.get("synthetic"))
    return None
