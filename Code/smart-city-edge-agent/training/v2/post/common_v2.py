"""Shared pieces of the v2 post-training pipeline: eval-set selection, the device stop rule, v2 scoring and
the report tables. Used by host_eval_v2.py (laptop) and device_eval_v2/*.py (QIDK, htpd) so host and device
numbers are computed by the same code on the same rows.

Scoring follows the frozen v2 schema (training/RETRAIN_V2_SPEC.md):
  json          the answer parses as one JSON object after the app's stop rule (cut where "action" starts)
  pattern / status / cause (likely_cause)        exact match with the label
  fault_kind    exact, scored only on rows whose label is sensor_fault
  event_active  exact bool
  onset         exact HH:MM, and onset_15 = within 15 min (3 readings); scored only where the label has an onset
  action        derived by the backend from (cause, status) exactly as the training targets were made
  evidence      every cited id exists in the prompt's EVIDENCE block (E1..E10) and at least one is cited
  policy        pattern/status/cause/fault_kind in the role's enums + evidence ok (the app's policy gate)
  false_alarm   on negative rows (calm / routine / small boundary events): status != normal (spec D3)
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
V2 = HERE.parent
TRAIN = V2.parent
ROOT = TRAIN.parent
DATA = ROOT / "data" / "sft_v2"
sys.path.insert(0, str(V2))
sys.path.insert(0, str(TRAIN))

PREFILL = '{"pattern": "'
NEG_FAMILIES = ("stable", "routine", "real_routine", "zero_idle")   # = checks_v2.is_negative
_ENUMS = None


def enums():
    """Role enums from the v2 registry (features_v2 + HVAC), and the backend action derivation."""
    global _ENUMS
    if _ENUMS is None:
        import features_v2 as V
        import hvac_adapter as HA
        HA.register()
        try:
            import teacher_v2 as TE
            act = TE.action_of
        except Exception:  # noqa: BLE001
            act = None
        hact = getattr(HA.H, "action_of", None) if HA.H is not None else None
        _ENUMS = {"patterns": {r: set(v) for r, v in V.PATTERNS.items()},
                  "causes": {r: set(v) for r, v in V.CAUSES.items()},
                  "actions": {r: set(v) for r, v in V.ROLE_ACTIONS.items()},
                  "statuses": set(V.STATUSES), "fault_kinds": set(V.FAULT_KINDS),
                  "action_of": act, "hvac_action_of": hact}
    return _ENUMS


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def gold_of(row):
    return json.loads(row["completion"].replace("<|eot_id|>", ""))


def _age(d):
    """d = readings since onset (5 min each), None for rows without an event."""
    if d is None:
        return "no_event"
    m = d * 5
    if m <= 40:
        return "a<=40min"
    if m <= 90:
        return "b<=1.5h"
    if m <= 180:
        return "c<=3h"
    return "d>3h"


def win_bucket(row):
    n = row.get("n") or 48
    return "w<=3h" if n <= 36 else "w4h" if n <= 48 else "w4-8h" if n <= 96 else "w8-12h"


def is_negative(r):
    return (r.get("family") in NEG_FAMILIES or bool(r.get("small")) or
            (r.get("family") == "hvac" and bool(r.get("routine"))) or
            (r.get("family") == "occupancy" and r.get("pattern") in ("vacant", "occupied")))


# ------------------------------------------------------------------ eval-set selection (paired host/device)
def select_rows(rows, n_total=400, seed=2026):
    """Stratified pick: equal quota per role; inside a role, round-robin over (seen, family, pattern) cells so
    unseen sensors, every family (incl. routines and HVAC) and every pattern appear."""
    rng = random.Random(seed)
    roles = sorted({r["role"] for r in rows})
    quota = {r: n_total // len(roles) + (1 if i < n_total % len(roles) else 0) for i, r in enumerate(roles)}
    pick = []
    for role in roles:
        cells = defaultdict(list)
        for r in rows:
            if r["role"] == role:
                cells[(r.get("seen", "seen"), r.get("family", ""), r["pattern"])].append(r)
        keys = sorted(cells)
        for k in keys:
            rng.shuffle(cells[k])
        # alternate seen/unseen first so the unseen share is not starved by many seen cells
        by_seen = defaultdict(list)
        for k in keys:
            by_seen[k[0]].append(k)
        order = []
        groups = [by_seen[s] for s in sorted(by_seen)]
        for i in range(max(len(g) for g in groups)):
            for g in groups:
                if i < len(g):
                    order.append(g[i])
        take, i = [], 0
        while len(take) < quota[role] and any(cells[k] for k in order):
            k = order[i % len(order)]
            if cells[k]:
                take.append(cells[k].pop())
            i += 1
        pick.extend(take)
    return pick


# ------------------------------------------------------------------ the app's stop rule
def cut_at_action(text):
    """Mirror of htpd / answerscan.go: stop where the top-level "action" key starts and close the object;
    also stop when the top-level object closes. `text` must start with the prefill."""
    depth, in_str, esc, key, kstart = 0, False, False, None, None
    i = 0
    while i < len(text):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
                if kstart is not None:
                    key = text[kstart:i]
                    # a key at depth 1 is followed by ':'
                    j = i + 1
                    while j < len(text) and text[j] in " \t\n":
                        j += 1
                    if depth == 1 and key == "action" and (j >= len(text) or text[j] == ":"):
                        head = text[:kstart - 1].rstrip()
                        if head.endswith(","):
                            head = head[:-1]
                        return head + "}", "action"
                    kstart = None
        else:
            if ch == '"':
                in_str = True
                kstart = i + 1
            elif ch in "{[":
                depth += 1
                kstart = None
            elif ch in "}]":
                depth -= 1
                kstart = None
                if depth == 0:
                    return text[:i + 1], "json"
            elif ch not in " \t\n":
                kstart = None
        i += 1
    return text, "open"


def parse_answer(text):
    """text = PREFILL + generated continuation (possibly already cut). Returns dict or None."""
    s = text.find("{")
    if s < 0:
        return None
    cut, _ = cut_at_action(text[s:])
    try:
        p = json.loads(cut)
        return p if isinstance(p, dict) else None
    except json.JSONDecodeError:
        return None


def _norm(v):
    return str(v).strip().lower().replace(" ", "_").replace("-", "_")


def _mins(hhmm):
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except Exception:  # noqa: BLE001
        return None


def derive_action(role, cause, status):
    E = enums()
    try:
        if role == "hvac" and E["hvac_action_of"]:
            return E["hvac_action_of"](cause, status)
        if E["action_of"]:
            return E["action_of"](cause, status)
    except Exception:  # noqa: BLE001
        return None
    return None


def score_one(row, text):
    """text = PREFILL + continuation. Returns a flat dict of booleans (None = not applicable)."""
    E = enums()
    role = row["role"]
    gold = gold_of(row)
    p = parse_answer(text)
    r = {"id": row["id"], "role": role, "seen": row.get("seen", "seen"), "family": row.get("family"),
         "age": _age(row.get("d")), "win": win_bucket(row), "n": row.get("n"), "negative": is_negative(row),
         "gold_pattern": gold["pattern"], "gold_status": gold["status"], "json": isinstance(p, dict)}
    if not r["json"]:
        r.update(pattern=False, status=False, cause=False, action=False, evidence=False, policy=False,
                 event_active=False, onset=False if gold.get("onset") else None,
                 onset_15=False if gold.get("onset") else None,
                 fault_kind=False if gold["status"] == "sensor_fault" else None,
                 false_alarm=None if not r["negative"] else None, pred=None)
        if r["negative"]:
            r["false_alarm"] = True  # an unreadable answer on a calm window is not "normal"
        return r
    pp = {k: _norm(p.get(k, "")) for k in ("pattern", "status", "likely_cause")}
    r["pattern"] = pp["pattern"] == gold["pattern"]
    r["status"] = pp["status"] == gold["status"]
    r["cause"] = pp["likely_cause"] == gold["likely_cause"]
    act = derive_action(role, pp["likely_cause"], pp["status"])
    r["action"] = act == gold.get("action") if act is not None else None
    r["event_active"] = isinstance(p.get("event_active"), bool) and p.get("event_active") == gold.get("event_active")
    if gold.get("onset"):
        r["onset"] = str(p.get("onset", "")) == gold["onset"]
        a_, b_ = _mins(p.get("onset")), _mins(gold["onset"])
        r["onset_15"] = a_ is not None and b_ is not None and min(abs(a_ - b_), 1440 - abs(a_ - b_)) <= 15
    else:
        r["onset"] = r["onset_15"] = None
    if gold["status"] == "sensor_fault":
        r["fault_kind"] = _norm(p.get("fault_kind", "")) == gold.get("fault_kind")
    else:
        r["fault_kind"] = None
    obs = p.get("observations") or []
    if not isinstance(obs, list):
        obs = [obs]
    ids = re.findall(r"\bE\d+\b", " ".join(map(str, obs)))
    have = set(re.findall(r"^(E\d+) ", row["prompt"], re.M))
    r["evidence"] = bool(ids) and all(i in have for i in ids)
    fk_ok = (pp["status"] != "sensor_fault") or (_norm(p.get("fault_kind", "")) in E["fault_kinds"])
    r["policy"] = (pp["pattern"] in E["patterns"].get(role, ()) and pp["status"] in E["statuses"]
                   and pp["likely_cause"] in E["causes"].get(role, ()) and fk_ok and r["evidence"]
                   and 1 <= len(obs) <= 2)
    r["false_alarm"] = (pp["status"] != "normal") if r["negative"] else None
    r["pred"] = {"pattern": pp["pattern"], "status": pp["status"], "likely_cause": pp["likely_cause"],
                 "fault_kind": p.get("fault_kind"), "event_active": p.get("event_active"), "onset": p.get("onset"),
                 "confidence": p.get("confidence"), "n_obs": len(obs)}
    return r


METRICS = ("json", "pattern", "status", "cause", "action", "fault_kind", "event_active", "onset", "onset_15",
           "evidence", "policy", "false_alarm")


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def aggregate(scored):
    """{group_key: {metric: {"rate","k","n","ci95"}}} for ALL and per role / seen / age / window / family."""
    groups = defaultdict(list)
    for s in scored:
        groups["ALL"].append(s)
        groups[f"role={s['role']}"].append(s)
        groups[f"seen={s['seen']}"].append(s)
        groups[f"age={s['age']}"].append(s)
        groups[f"win={s['win']}"].append(s)
        groups[f"family={s['family']}"].append(s)
        groups[f"role_seen={s['role']}/{s['seen']}"].append(s)
    out = {}
    for g, ss in sorted(groups.items()):
        m = {"n_rows": len(ss)}
        for k in METRICS:
            v = [s[k] for s in ss if s.get(k) is not None]
            if v:
                kk = sum(1 for x in v if x)
                m[k] = {"rate": round(kk / len(v), 3), "k": kk, "n": len(v), "ci95": wilson(kk, len(v))}
        out[g] = m
    return out


def mcnemar(a, b):
    """Exact two-sided McNemar on paired booleans."""
    bb = sum(1 for x, y in zip(a, b) if x and not y)
    cc = sum(1 for x, y in zip(a, b) if y and not x)
    n = bb + cc
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(min(bb, cc) + 1)) / 2 ** n) if n else 1.0
    return {"only_a": bb, "only_b": cc, "p": round(p, 4)}


def table_md(name, agg, keys=None):
    cols = ("json", "pattern", "status", "cause", "action", "fault_kind", "event_active", "onset_15", "evidence",
            "policy", "false_alarm")
    keys = keys or [k for k in agg]
    lines = [f"### {name}", "", "| group | n | " + " | ".join(cols) + " |", "|---|---|" + "---|" * len(cols)]
    for g in keys:
        if g not in agg:
            continue
        m = agg[g]
        cell = lambda c: (f"{100 * m[c]['rate']:.1f}" + (f" ({m[c]['n']})" if c in ("fault_kind", "false_alarm") else "")) if c in m else "-"
        lines.append(f"| {g} | {m['n_rows']} | " + " | ".join(cell(c) for c in cols) + " |")
    return "\n".join(lines) + "\n"


def headline_keys(agg):
    order = ["ALL"]
    for pre in ("role=", "seen=", "age=", "win=", "role_seen=", "family="):
        order += sorted(k for k in agg if k.startswith(pre))
    return order
