"""Python -> Go parity fixtures for the v2 agent prompt (app/backend/features_v2.go, hvac_v2.go).

Writes app/backend/testdata/v2_prompt_fixtures.json: ~300 prompts built by features_v2.agent_prompt (all v1 roles,
many window lengths N, 12 h history of every length incl. under 8 h, water level nodes with a TANK line) and by
the HVAC path of hvac_adapter.make_examples (real units from data/series/hvac_units, some with an injected pattern,
some with a room occupancy sequence attached), plus the HVAC teacher rule (pattern/onset/active/status/cause) that
the Go Mode-1 HVAC rule mirrors. The Go test (features_v2_test.go) asserts byte-identical prompts.

Inputs are read-only: data/sft_v2/{test,dev}.jsonl (window histories), node_limits.json, data/series/hvac_units.

  python3 training/v2/make_go_fixtures.py [--n 300] [--seed 11]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import features_v2 as V  # noqa: E402
import hvac_adapter as HA  # noqa: E402
import generate_dataset as G  # noqa: E402

ROOT = HERE.parents[1]
SFT = ROOT / "data" / "sft_v2"
OUT = ROOT / "app" / "backend" / "testdata" / "v2_prompt_fixtures.json"
V1_ROLES = ("air_quality", "water", "power", "occupancy", "weather")


def load_rows(paths, roles):
    rows = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r["role"] in roles:
                    rows.append({k: r[k] for k in ("role", "node", "metric", "end_epoch", "n", "hist", "prompt")})
    return rows


def v1_fixture(r, hist, n, tag):
    loc = G.describe(r["node"])
    prompt, _, _, info = V.agent_prompt(r["role"], r["node"], loc, r["metric"], hist, n, r["end_epoch"])
    return {"kind": "v1role", "tag": tag, "role": r["role"], "node": r["node"], "location": loc, "metric": r["metric"],
            "n": n, "end": r["end_epoch"], "hist": hist, "prompt": prompt,
            "exc_count": info.get("exc_count"), "long_view": [f["kind"] for f in (info.get("long_view") or [])]}


def v1_fixtures(rng, want):
    rows = load_rows([SFT / "test.jsonl", SFT / "dev.jsonl"], V1_ROLES)
    by = {}
    for r in rows:
        by.setdefault(r["role"], []).append(r)
    out = []
    # stratified: every role, many N
    per = want // len(V1_ROLES)
    for role in V1_ROLES:
        pool = by.get(role, [])
        rng.shuffle(pool)
        seen_n = {}
        for r in pool:
            if sum(1 for f in out if f["role"] == role) >= per:
                break
            if seen_n.get(r["n"], 0) >= max(2, per // 10):
                continue
            seen_n[r["n"]] = seen_n.get(r["n"], 0) + 1
            out.append(v1_fixture(r, r["hist"], r["n"], "row"))
    # special coverage: water level with a TANK line, E9 findings, many excursions, odd history lengths
    tank = [r for r in by.get("water", []) if r["metric"] == "level" and r["node"] in V.NODE_LIMITS]
    for r in rng.sample(tank, min(12, len(tank))):
        out.append(v1_fixture(r, r["hist"], r["n"], "tank"))
    for key, cnt in (("level shift", 10), ("slow drift", 10), ("excursions beyond", 10), ("under 8 h", 6)):
        cand = [r for r in rows if key in r["prompt"] and r["role"] != "occupancy"]
        for r in rng.sample(cand, min(cnt, len(cand))):
            out.append(v1_fixture(r, r["hist"], r["n"], key.replace(" ", "_")))
    full = [r for r in rows if len(r["hist"]) == 144]
    for L in (24, 48, 60, 95, 96, 97, 101, 120, 143):
        for r in rng.sample(full, 3):
            n = min(r["n"], L - L % 2)
            n = max(V.MIN_N, n - n % 6)
            if n > L:
                continue
            out.append(v1_fixture(r, r["hist"][-L:], n, f"hist{L}"))
    return out


def hvac_fixtures(rng, want):
    U = HA.units()
    nodes = sorted(U)
    months = tuple(range(1, 13))
    out, tries = [], 0
    pats = list(HA.H.INJECTABLE)
    while len(out) < want and tries < want * 80:
        tries += 1
        node = rng.choice(nodes)
        pairs = HA.H.window_ends(U[node], months, stride_off=97, stride_on=53)
        if not pairs:
            continue
        end, _ = rng.choice(pairs)
        w = HA.window_at(U[node], node, end, 144)
        if w is None:
            continue
        xs144, c144 = w
        n = rng.choice(HA.HVAC_LENGTHS)
        xs, c = xs144[-n:], HA.slice_ctx(c144, n)
        tag = "real"
        if rng.random() < 0.6:
            p = rng.choice(pats)
            r = HA.H.make_case(p, xs, c, rng)
            if r is None:
                continue
            ys, c2, _ = r
            tag = "inject:" + p
        else:
            ys, c2 = list(xs), HA.H._copy_ctx(c)
        if c2.get("occ") is None and rng.random() < 0.3:
            k = rng.randint(0, n)
            c2["occ"] = [1] * (n - k) + [0] * k if rng.random() < 0.5 else [rng.randint(0, 1) for _ in range(n)]
            tag += "+occ"
        hist = (xs144[:-n] + ys) if c2["end"] == c144["end"] else list(ys)
        if rng.random() < 0.15:
            hist = hist[-rng.choice([n, max(n, 60), max(n, 100)]):]
        loc = HA.H.describe(node)
        user, st, ev = HA.H.user_prompt(node, loc, ys, c2)
        hv, info = V.history_items("hvac", "room_temp", hist[-V.HIST:], c2["end"], 1, "C")
        user = user + "\n" + "\n".join(f"{e} {t}" for e, _, t in hv)
        system = HA.H.SYSTEM_PROMPT + V.system_rules(n) + " " + V.output_schema_hint("hvac")
        prompt = V.F.llama3_prompt(system, user)
        pat, onset, active = HA.H.classify_hvac(ys, c2, st)
        status = HA.H.status_of(pat, ys, c2, st, onset)
        cause = HA.H.cause_of(pat, st)
        for k_ in ("on", "alarm"):
            assert all(isinstance(v, int) for v in c2[k_]), (k_, c2[k_][:5])
        ctx = {k: c2.get(k) for k in ("sp", "on", "thermo", "mode", "alarm", "malf", "missing", "occ", "duty", "hour_on")}
        ctx["missing"] = [bool(v) for v in ctx["missing"]]
        out.append({"kind": "hvac", "tag": tag, "role": "hvac", "node": node, "location": loc, "metric": "room_temp",
                    "n": n, "end": c2["end"], "hist": hist, "xs": ys, "ctx": ctx, "prompt": prompt,
                    "rule": {"pattern": pat, "onset": onset, "active": bool(active), "status": status, "cause": cause,
                             "action": HA.H.action_of(cause, status)},
                    "exc_count": info.get("exc_count"), "long_view": [f["kind"] for f in (info.get("long_view") or [])]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    HA.register()
    V.NODE_LIMITS.update(json.loads((SFT / "node_limits.json").read_text()))
    rng = random.Random(a.seed)
    n_hvac = a.n // 4
    fx = v1_fixtures(rng, a.n - n_hvac - 100) + hvac_fixtures(rng, n_hvac)
    meta = {"source": "training/v2/make_go_fixtures.py", "seed": a.seed, "count": len(fx),
            "roles": {r: sum(1 for f in fx if f["role"] == r) for r in V.ROLES},
            "lengths": sorted({f["n"] for f in fx}), "hist_lengths": sorted({len(f["hist"]) for f in fx}),
            "tank_lines": sum(1 for f in fx if "\nTANK: " in f["prompt"]),
            "e9": {k: sum(1 for f in fx if k in f["long_view"]) for k in ("level_shift", "slow_drift")},
            "e9_short_history": sum(1 for f in fx if "under 8 h of history" in f["prompt"]),
            "e10_counts": sorted({f["exc_count"] for f in fx if f["exc_count"] is not None}),
            "hvac_patterns": sorted({f["rule"]["pattern"] for f in fx if f["kind"] == "hvac"}),
            "node_limits": V.NODE_LIMITS, "e10_count_thresholds": json.loads((SFT / "kthr.json").read_text())}
    Path(a.out).write_text(json.dumps({"meta": meta, "fixtures": fx}, separators=(",", ":")))
    print(json.dumps({k: v for k, v in meta.items() if k not in ("node_limits", "e10_count_thresholds")}, indent=1))


if __name__ == "__main__":
    main()
