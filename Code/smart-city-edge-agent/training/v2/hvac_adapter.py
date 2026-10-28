"""Bridge between generate_v2 and the HVAC role module (training/v2/hvac.py, written separately).

Contract used from hvac.py (and nothing else):
  HVAC_ROLE / METRICS / PATTERNS / CAUSES / SYSTEM_PROMPT / EXPECTED_LABEL / INJECTABLE
  load_hvac_series(series_dir) -> {unit: {...}}, hvac_windows(unit, node, n, stride, months=...)
  split_units({unit: duty}, frac, seed) -> held-out units
  make_case(pattern, xs, ctx, rng) -> (ys, ctx2, label) | None   (inject_hvac + label_hvac + agreement)
  user_prompt(node, location, xs, ctx) -> (user text with E1..E8, stats, evidence)   describe(node)
The adapter adds the v2 history lines E9/E10 (features_v2.history_items on the room temperature history) and
the v2 system rules / schema hint. When hvac.py is missing the role is stubbed (no rows, status "stubbed").
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import features_v2 as V  # noqa: E402

try:
    import hvac as H  # noqa: E402
    _ERR = None
except Exception as e:  # noqa: BLE001
    H = None
    _ERR = repr(e)

SERIES = HERE.parents[1] / "data" / "series"
MONTHS = {"train": tuple(range(1, 9)), "dev": (9, 10), "test": (11, 12)}
def _lengths():
    """All v2 lengths (24..144 step 6) once hvac.series_lines prints N/2 10-min means for any N; only multiples
    of 24 while it still prints 24 fixed buckets (its old `k=24` signature)."""
    import inspect as _insp
    if H is None:
        return V.LENGTHS
    k = _insp.signature(H.series_lines).parameters.get("k")
    return tuple(n for n in V.LENGTHS if n % 24 == 0) if (k is not None and k.default == 24) else tuple(V.LENGTHS)


HVAC_LENGTHS = _lengths()
HELDOUT_SEED = 7
UNSEEN_SHARE = 0.35
_UNITS = None


def status():
    if H is None:
        return {"status": "stubbed", "reason": _ERR, "todo": "add training/v2/hvac.py and rerun generate_v2.py"}
    import hashlib
    sha = hashlib.sha256((HERE / "hvac.py").read_bytes()).hexdigest()[:16]
    return {"status": "ok", "module": "training/v2/hvac.py", "hvac_py_sha256_16": sha, "lengths": HVAC_LENGTHS}


def register():
    if H is None:
        return
    V.F.METRICS.update(H.METRICS)  # longrange.noise_scale reads the v1 registry (runtime only, file untouched)
    acts = tuple(getattr(H, "ACTIONS", ())) + tuple(getattr(H, "NEW_ACTIONS", ()))
    V.register_role("hvac", H.METRICS, H.CAUSES, H.PATTERNS, H.SYSTEM_PROMPT, actions=acts)
    V.F.CAUSES.setdefault("hvac", tuple(H.CAUSES))
    V.F.SYSTEM_PROMPTS.setdefault("hvac", H.SYSTEM_PROMPT)


def load_series():
    """generate_v2 keeps its own loader for v1 roles; HVAC units are loaded inside the HVAC task."""
    return {}


def units():
    global _UNITS
    if _UNITS is None:
        _UNITS = H.load_hvac_series(SERIES)
    return _UNITS


def heldout_units():
    U = units()
    return sorted(H.split_units({k: v["duty"] for k, v in U.items()}, 0.15, HELDOUT_SEED))


def window_at(unit, node, end, n):
    rows = unit["rows"]
    sub = dict(unit)
    sub["rows"] = {b: rows[b] for b in range(end - (n - 1) * 300, end + 1, 300) if b in rows}
    for xs, ctx in H.hvac_windows(sub, node, n=n, stride=1):
        if ctx["end"] == end:
            return xs, ctx
    return None


def candidate_ends(unit, months, n=144, stride=12):
    """Window ends (every `stride` readings) whose 12 h span has >= n-3 real temperatures and whose first and
    last points are real (the hvac_windows acceptance rule), within `months`; found with a prefix sum."""
    rows = unit["rows"]
    if not rows:
        return []
    b0 = min(rows)
    b1 = max(rows)
    L = (b1 - b0) // 300 + 1
    have = [0] * (L + 1)
    for i in range(L):
        r = rows.get(b0 + i * 300)
        have[i + 1] = have[i] + (1 if r is not None and r[2] is not None else 0)
    out = []
    for i in range(n - 1, L, stride):
        b = b0 + i * 300
        if (V.datetime.fromtimestamp(b, V.IST).month not in months
                or V.datetime.fromtimestamp(b - (n - 1) * 300, V.IST).month not in months):
            continue
        if have[i + 1] - have[i + 1 - n] >= n - 3 and have[i + 1] - have[i] == 1 and have[i - n + 2] - have[i - n + 1] == 1:
            out.append(b)
    return out


NUM = re.compile(r"(?<![A-Za-z0-9.:])[-+]?\d+(?:\.\d+)?(?![\d:])")
TIME = re.compile(r"\b\d\d:\d\d\b")


def numbers_not_in(obs, user):
    """Numbers / HH:MM in observations that do not appear in the prompt (same rule as checks_v2)."""
    bad = []
    for o in obs:
        body = o[: o.rindex("[")] if "[" in o else o
        bad += [t for t in TIME.findall(body) if t not in user]
        for nm in NUM.findall(TIME.sub(" ", body)):
            if not re.search(r"(?<![\d.])[-+]?" + re.escape(nm.lstrip("+-")) + r"(?![\d])", user):
                bad.append(nm)
    return bad


def slice_ctx(ctx, n):
    c = dict(ctx)
    for k in ("sp", "on", "thermo", "alarm", "missing", "occ"):
        if c.get(k) is not None:
            c[k] = list(c[k][-n:])
    return c


def make_examples(ctx, quota, sample_n, sample_d, validate):
    """HVAC rows for one split. ctx: generate_v2.Ctx (split, rng). Returns (rows, stats)."""
    if H is None or quota <= 0:
        return [], {"hvac": status()}
    rng = ctx.rng
    U = units()
    held = set(heldout_units())
    months = MONTHS[ctx.split]
    cand = {}
    for node in sorted(U):
        if U[node].get("faulty") and ctx.split != "test":
            pass  # faulty units are real data too; keep them
        if node in held and ctx.split != "test":
            continue
        # D12: dense ends while the unit runs (10 min stride), sparse while off; kept as (running, off) lists
        # so running and off windows can be drawn 50/50 below
        pairs = H.window_ends(U[node], months) if hasattr(H, "window_ends") else [(e, False) for e in candidate_ends(U[node], months)]
        on = [e for e, r in pairs if r]
        off = [e for e, r in pairs if not r]
        if on or off:
            cand[node] = (on, off)
    seen = [k for k in cand if k not in held]
    unseen = [k for k in cand if k in held]
    pats = list(H.INJECTABLE)
    per = {p: quota // len(pats) for p in pats}
    for p in pats[: quota - sum(per.values())]:
        per[p] += 1
    made, tries, rows = {p: 0 for p in pats}, 0, []
    rejected, rej_examples = {"validate": 0, "history_outside_split": 0, "obs_number_not_in_evidence": 0}, []
    while sum(made.values()) < quota and tries < quota * 60:
        tries += 1
        todo = [p for p in pats if made[p] < per[p]]
        p = rng.choice(todo)
        pool, tag = (unseen, "unseen") if unseen and ctx.split == "test" and rng.random() < UNSEEN_SHARE else (seen, "seen")
        if not pool:
            break
        node = rng.choice(pool)
        on, off = cand[node]
        end = rng.choice(on if on and (not off or rng.random() < 0.5) else off)
        w = window_at(U[node], node, end, 144)
        if w is None:
            continue
        xs144, c144 = w
        n = sample_n(rng)
        n = min(HVAC_LENGTHS, key=lambda L: abs(L - n))
        n = max(n, min((L for L in HVAC_LENGTHS if L >= getattr(H, "MIN_LEN", {}).get(p, 0)), default=n))  # e.g. drift needs >= 2 h 40 min
        xs, c = xs144[-n:], slice_ctx(c144, n)
        r = H.make_case(p, xs, c, rng)
        if r is None:
            continue
        ys, c2, lab = r
        meta = lab.pop("_meta", {})
        lab.pop("_agrees", None)
        hist = (xs144[:-n] + ys) if c2["end"] == c144["end"] else list(ys)
        user, st, ev = H.user_prompt(node, H.describe(node), ys, c2)
        hv, info = V.history_items("hvac", "room_temp", hist[-V.HIST:], c2["end"], 1, "C")
        user = user + "\n" + "\n".join(f"{e} {t}" for e, _, t in hv)
        ev = list(ev) + hv
        system = H.SYSTEM_PROMPT + V.system_rules(n) + " " + V.output_schema_hint("hvac")
        prompt = V.F.llama3_prompt(system, user)
        try:
            validate("hvac", lab, [e[0] for e in ev])
        except AssertionError:
            rejected["validate"] += 1
            continue
        if V.datetime.fromtimestamp(c2["end"] - (len(hist[-V.HIST:]) - 1) * 300, V.IST).month not in months:
            rejected["history_outside_split"] += 1  # inject_hvac may move the end inside the month
            continue
        bad = numbers_not_in(lab["observations"], user)
        if bad:
            rejected["obs_number_not_in_evidence"] += 1
            if len(rej_examples) < 5:
                rej_examples.append({"pattern": lab["pattern"], "missing": bad, "obs": lab["observations"]})
            continue
        made[p] += 1
        rows.append({"role": "hvac", "node": node, "metric": "room_temp", "split": ctx.split, "seen": tag,
                     "end_epoch": c2["end"], "n": n, "hist_len": len(hist[-V.HIST:]), "family": "hvac", "sub": p,
                     "pattern": lab["pattern"], "status": lab["status"], "likely_cause": lab["likely_cause"],
                     "fault_kind": lab.get("fault_kind"), "event_active": lab["event_active"], "onset": lab["onset"],
                     "confidence": lab["confidence"], "size": round(meta.get("size"), 2) if meta.get("size") else None,
                     "d": n - meta["onset"] if meta.get("onset") is not None else None, "small": False,
                     "routine": p if p in H.EXPECTED_LABEL else None, "hist": [round(v, 4) for v in hist[-V.HIST:]],
                     "ac_on": c2["on"], "setpoint": c2["sp"], "prompt": prompt,
                     "completion": json.dumps(lab, ensure_ascii=False) + "<|eot_id|>"})
    return rows, {"hvac": status(), "tries": tries, "made": made, "heldout_units": sorted(held),
                  "rejected": rejected, "rejected_examples": rej_examples,
                  "units_with_windows": len(cand)}
