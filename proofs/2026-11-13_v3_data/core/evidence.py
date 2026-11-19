"""Evidence lines E1-E10 and the agt_v3 prompt (V3_DESIGN §2.2).

The E-line text is produced by the SAME Python reference code the app's Go builder is byte-checked against today
(training/v2/features_v2.py + features.py + window_study/longrange.py; Go: features_v2.go EvidenceItemsV2 /
HistoryItemsV2, parity test features_v2_test.go TestPromptParityV2). Synthetic cards are registered under the key
("card", card_id) with the card's decimals / unit / floor, so the same functions render them.

API:
  register(card)                                   make the card known to the E-line code (idempotent)
  agent_system(card, n)                            v3 generic system text
  agent_user(card, node, location, hist, n, end, place=None, missing=None, hvac_ctx=None)
        -> (user_text, stats, evidence[(id, stat, text)], info)
  agent_prompt(...) -> (llama3 prompt, stats, evidence, info)
  evidence_lines(card, hist, n, end) -> [(id, text)]  E1..E10 only
  verify_fixtures() -> dict                         re-render today's Go parity fixtures, compare E-lines byte for byte
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TRAIN = ROOT / "Code" / "smart-city-edge-agent" / "training"
for p in (TRAIN, TRAIN / "v2", TRAIN / "window_study"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
sys.path.insert(0, str(HERE))

import features as F  # noqa: E402
import features_v2 as V  # noqa: E402
import hvac as HV  # noqa: E402
import cards as CD  # noqa: E402

# HVAC metrics in the v1 registry (as hvac_adapter.register does at run time)
F.METRICS.update(HV.METRICS)
V.METRICS.update(HV.METRICS)

GAPS_FMT = "GAPS: {k} of {n} readings missing (filled with the last value), longest gap {m} min"


def register(card):
    key = CD.metric_key(card)
    if key[0] == "card" and key not in F.METRICS:
        imp = card.get("impossible") or {}
        lo = imp.get("below") if imp.get("below") is not None else -1e18
        hi = imp.get("above") if imp.get("above") is not None else 1e18
        d = dict(unit=card["unit"], dec=card["decimals"], warn=None, crit=None, dir="high",
                 floor=float(card.get("floor") or 0.0), lo=lo, hi=hi)
        F.METRICS[key] = d
        V.METRICS[key] = d
    return key


def agent_system(card, n):
    kinds = "|".join(CD.patterns_for(card))
    return ("You are the " + CD.DOMAIN_NAMES[card["domain"]] + " agent of a smart-campus edge monitor. You receive one "
            "sensor's CARD (what it measures, its limits and normal behaviour) and a " + V.hours_str(n) + "-hour window "
            "(5-minute samples) with precomputed evidence E1..E10. Judge the data first: values the CARD calls "
            "impossible, stuck, biased or missing are a data-quality problem, not an event. Then name the pattern, set "
            "status from the CARD limits or rate rules, and give the reason with evidence ids. Use only the given numbers. "
            "Never order physical actuation. Reply with one JSON object only. JSON keys: pattern (" + kinds + "), status "
            "(normal|warning|critical|sensor_fault), data_quality {verdict (ok|suspect|fault|insufficient), why, src}, "
            "severity_reason, evidence (ids), observations (1-2 short strings ending with ids like [E1,E4]), likely_cause ("
            + "|".join(card["causes"]) + "), confidence (0-1), event_active (true|false), onset (HH:MM), fault_kind ("
            + "|".join(card["faults"]) + ", only if sensor_fault), action (" + "|".join(card["actions"]) + ").")


def gaps_line(missing, n):
    """missing: per-point bools for the window (True = no reading, value held). None/[] -> no line."""
    if not missing or not any(missing):
        return None
    k = sum(1 for m in missing if m)
    best = cur = 0
    for m in missing:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return GAPS_FMT.format(k=k, n=n, m=best * 5)


def evidence_lines(card, hist, n, end):
    key = register(card)
    role, metric = key
    m = F.METRICS[key]
    xs = hist[-n:]
    st = V.compute_window_stats(role, metric, xs)
    ev = V.evidence_items(role, metric, st, end, m["dec"], m["unit"], n)
    hv, info = V.history_items(role, metric, hist[-V.HIST:], end, m["dec"], m["unit"])
    return st, ev + hv, info


def agent_user(card, node, location, hist, n, end, place=None, missing=None, hvac_ctx=None):
    """The v3 user turn. hist: <= 144 values ending at the window end (oldest first); window = hist[-n:].
    hvac_ctx: for kind hvac_unit, the hvac.py ctx of the window (sp/on/... sliced to n)."""
    key = register(card)
    role, metric = key
    m = F.METRICS[key]
    dec = m["dec"]
    xs = hist[-n:]
    assert len(xs) == n and n % 2 == 0
    e = datetime.fromtimestamp(end, V.IST)
    s = e - timedelta(minutes=5 * (n - 1))
    lines = [CD.render_full(card, place), f"NODE: {node} ({location})",
             f"WINDOW: {s:%a %d %b %H:%M} -> {e:%H:%M} IST, {n} x 5 min"]
    g = gaps_line(missing, n)
    if g:
        lines.append(g)
    if card["kind"] == "hvac_unit":
        st = HV.hvac_stats(xs, hvac_ctx)
        lines += HV.series_lines(xs, hvac_ctx)
        ev = HV.evidence_items(xs, hvac_ctx, st)
        hv, info = V.history_items("hvac", "room_temp", hist[-V.HIST:], end, 1, "C")
        ev = list(ev) + hv
    elif card["kind"] == "binary_state":
        st = F.occ_stats(xs)
        lines.append("STATES (1=occupied): " + "".join(str(int(v)) for v in xs))
        ev = V.evidence_items("occupancy", "occ", st, end, 0, "0/1", n)
        hv, info = V.history_items("occupancy", "occ", hist[-V.HIST:], end, 0, "0/1")
        ev = ev + hv
    else:
        st = F.compute_stats(xs, dec)
        lines.append("SERIES (10-min means): " + " ".join(F.fmt(v, dec) for v in F.downsample(xs, n // 2)))
        ev = V.evidence_items(role, metric, st, end, dec, m["unit"], n)
        hv, info = V.history_items(role, metric, hist[-V.HIST:], end, dec, m["unit"])
        ev = ev + hv
    lines.append("EVIDENCE:")
    lines += [f"{i} {t}" for i, _, t in ev]
    return "\n".join(lines), st, ev, info


def agent_prompt(card, node, location, hist, n, end, **kw):
    user, st, ev, info = agent_user(card, node, location, hist, n, end, **kw)
    return F.llama3_prompt(agent_system(card, n), user), st, ev, info


# --------------------------------------------------------------------------------------------- parity check
FIXTURES = ROOT / "Code" / "smart-city-edge-agent" / "app" / "backend" / "testdata" / "v2_prompt_fixtures.json"


def _elines(text):
    u = V.user_text(text) if "<|start_header_id|>user" in text else text
    out = []
    for ln in u.split("\n"):
        if len(ln) > 2 and ln[0] == "E" and ln[1].isdigit():
            out.append(ln)
    return out


def verify_fixtures():
    """Re-render every Go parity fixture (today's app prompts; Go == these bytes per TestPromptParityV2) through the v3
    path with the matching existing card, and compare the E1-E10 lines (and SERIES / STATES / HVAC series lines)."""
    d = json.loads(FIXTURES.read_text())
    meta = d["meta"]
    EC = CD.existing_cards()
    res = {"fixtures": 0, "elines_equal": 0, "series_equal": 0, "mismatch": []}
    for fx in d["fixtures"]:
        role, metric, node = fx["role"], fx["metric"], fx["node"]
        n, end = int(fx["n"]), int(fx["end"])
        hist = json.loads(fx["hist"]) if isinstance(fx["hist"], str) else fx["hist"]
        card = EC[CD.metric_to_card(role, metric, node, fx.get("location", ""))]
        hctx = None
        if role == "hvac":
            import ast
            c0 = fx["ctx"]
            hctx = ast.literal_eval(c0) if isinstance(c0, str) else dict(c0)
            hctx["end"] = end
            if hctx.get("missing") is None:
                hctx["missing"] = [False] * n
            if hctx.get("alarm") is None:
                hctx["alarm"] = [0] * n
        try:
            user, st, ev, info = agent_user(card, node, fx.get("location", ""), hist, n, end, hvac_ctx=hctx)
        except Exception as ex:  # noqa: BLE001
            res["mismatch"].append({"node": node, "metric": metric, "err": repr(ex)[:200]})
            res["fixtures"] += 1
            continue
        a, b = _elines(fx["prompt"]), _elines(user)
        res["fixtures"] += 1
        if a == b:
            res["elines_equal"] += 1
        else:
            res["mismatch"].append({"node": node, "metric": metric, "want": a[:3], "got": b[:3]})
        sa = [ln for ln in V.user_text(fx["prompt"]).split("\n") if ln.startswith(("SERIES", "STATES", "ROOM TEMP", "AC STATE"))]
        sb = [ln for ln in user.split("\n") if ln.startswith(("SERIES", "STATES", "ROOM TEMP", "AC STATE"))]
        res["series_equal"] += sa == sb
    res["fixture_meta_source"] = meta.get("source")
    return res


if __name__ == "__main__":
    r = verify_fixtures()
    print(json.dumps({k: v for k, v in r.items() if k != "mismatch"}, indent=1))
    for m in r["mismatch"][:5]:
        print(m)
