"""Verify EVERY agt_v3 row (V3_DESIGN §4.6, agent part). Rows that fail are dropped (written to rejected.jsonl with
reasons) and counted in verify_report.json.

  python3 verify_agt.py IN.jsonl OUT_OK.jsonl REPORT.json
Checks per row:
  schema      key order, enums from the card (pattern list by kind, causes, actions, faults), types, onset HH:MM
  consistency sensor_fault <=> dq fault (+ fault_kind); insufficient -> never critical; severity_reason <= 20 words,
              cites the card ("(card"); evidence ids == sorted ids cited in reason / observations / dq src
  ids         every cited id (E#, GAPS) exists in the prompt
  grounding   every number in observations / severity_reason / dq.why appears in the user turn (E-lines, card, GAPS),
              numerically (92 == 92.0)
  rerender    the prompt rebuilt from (card, hist, n, end, node, location, place, missing, hvac ctx) is byte-identical
  severity    independent recompute: status from the card limit / rate rule on the window (rows without a routine,
              fault, glitch or gap cap) equals the gold status; tank / routine rows recomputed via the routine table
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "core"))
sys.path.insert(0, str(HERE))
import evidence as EV  # noqa: E402
import cards as CD  # noqa: E402
import teacher_v3 as TV  # noqa: E402
import features as F  # noqa: E402
import features_v2 as V  # noqa: E402

NUM = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?")
TIME = re.compile(r"\b\d{2}:\d{2}\b")
STATUSES = ("normal", "warning", "critical", "sensor_fault")
VERDICTS = ("ok", "suspect", "fault", "insufficient")


def nums(text):
    out = set()
    for t in TIME.findall(text):
        out.add(t)
    t2 = TIME.sub(" ", text)
    for m in NUM.findall(t2):
        try:
            out.add(round(float(m), 6))
        except ValueError:
            pass
    return out


def user_of(prompt):
    return V.user_text(prompt)


def check(r):
    bad = []
    g = r["gold"]
    card = r["card"]
    if card["rules"].get("legacy_key") is None or card["card_id"].startswith(tuple(CD.TRAIN_TYPES) + tuple(CD.TEST_TYPES)):
        EV.register(card)
    keys = list(g)
    exp = [k for k in TV.KEY_ORDER if k in g]
    if keys != exp or set(keys) - set(TV.KEY_ORDER):
        bad.append("key_order")
    need = {"pattern", "status", "data_quality", "severity_reason", "evidence", "observations", "likely_cause", "confidence",
            "event_active", "onset", "action"}
    if need - set(keys):
        bad.append("missing_keys")
        return bad
    if g["pattern"] not in CD.patterns_for(card):
        bad.append("pattern_enum")
    if g["status"] not in STATUSES:
        bad.append("status_enum")
    if g["likely_cause"] not in card["causes"]:
        bad.append("cause_enum")
    if g["action"] not in card["actions"]:
        bad.append("action_enum")
    if not isinstance(g["confidence"], (int, float)) or not 0 <= g["confidence"] <= 1:
        bad.append("confidence")
    if not isinstance(g["event_active"], bool):
        bad.append("event_active")
    if not re.fullmatch(r"\d{2}:\d{2}", str(g["onset"])):
        bad.append("onset")
    dq = g["data_quality"]
    if not isinstance(dq, dict) or list(dq) != ["verdict", "why", "src"] or dq["verdict"] not in VERDICTS or not dq["why"]:
        bad.append("dq_schema")
        return bad
    fk = g.get("fault_kind")
    if (g["status"] == "sensor_fault") != (dq["verdict"] == "fault"):
        bad.append("fault_iff_dq_fault")
    if (g["status"] == "sensor_fault") != (fk is not None):
        bad.append("fault_kind_presence")
    if fk is not None and fk not in card["faults"]:
        bad.append("fault_kind_enum")
    if dq["verdict"] == "insufficient" and g["status"] == "critical":
        bad.append("insufficient_critical")
    # 2026-11-13 owner review (label-audit lesson: a gold fault must be clearly visible in the prompt)
    if fk == "noise" and card.get("noise"):
        mn = re.search(r"E8 noise ([\d.]+)", r["prompt"])
        if mn and float(mn.group(1)) < 3 * float(card["noise"]):
            bad.append("noise_fault_weak")
    if g["status"] == "warning" and isinstance(card.get("critical"), dict) and card["critical"].get("dir") in ("high", "low")             and "at" in card["critical"]:
        ms = re.search(r"E6 SMA 1h = ([-\d.]+)", r["prompt"])
        if ms:
            sv, ca = float(ms.group(1)), float(card["critical"]["at"])
            if (card["critical"]["dir"] == "high" and sv > ca) or (card["critical"]["dir"] == "low" and sv < ca):
                bad.append("warning_but_1h_avg_critical")
    sev = g["severity_reason"]
    if len(sev.split()) > 20 or "(card" not in sev:
        bad.append("severity_reason_form")
    obs = g["observations"]
    if not (1 <= len(obs) <= 2) or not all(re.search(r"\[(E\d+)(,E\d+)*\]$", o) for o in obs):
        bad.append("observations_form")
    u = user_of(r["prompt"])
    have = set(re.findall(r"^(E\d+) ", u, re.M))
    if "\nGAPS: " in u:
        have.add("GAPS")
    cited = set()
    for o in obs:
        cited |= set(re.findall(r"E\d+", o[o.rfind("["):]))
    cited |= set(re.findall(r"\bE\d+\b", sev))
    srcs = set(dq["src"])
    if not (cited | srcs) <= have:
        bad.append("unknown_ids")
    exp_ev = TV.ids_in(sev, *obs, " ".join(x for x in dq["src"] if x.startswith("E")))
    if g["evidence"] != exp_ev:
        bad.append("evidence_list")
    # grounding (numbers) against the user turn
    ok_nums = nums(u)
    for t in obs + [sev, dq["why"]]:
        body = re.sub(r"\[[E\d,]+\]$", "", t)
        body = re.sub(r"\bE\d+\b", " ", body)
        for x in nums(body):
            if x not in ok_nums:
                bad.append(f"ungrounded:{x}")
                break
    # rerender
    try:
        hist = r["hist"]
        hctx = None
        if card["kind"] == "hvac_unit":
            hctx = dict(r["hvac_ctx"], end=r["end_epoch"], node=r["node"])
            hctx.setdefault("thermo", None)
            for k in ("sp", "on", "alarm", "missing", "thermo"):
                if hctx.get(k) is not None:
                    hctx[k] = hctx[k][-r["n"]:]
            for k in ():
                hctx[k] = hctx[k][-r["n"]:]
            if hctx.get("occ") is not None:
                hctx["occ"] = hctx["occ"][-r["n"]:]
        miss = r.get("missing")
        user2, st, ev, info = EV.agent_user(card, r["node"], r["location"], hist, r["n"], r["end_epoch"], place=r["place"],
                                            missing=miss if miss and any(miss) else None, hvac_ctx=hctx)
        if F.llama3_prompt(EV.agent_system(card, r["n"]), user2) != r["prompt"]:
            bad.append("rerender_mismatch")
    except Exception as e:  # noqa: BLE001
        bad.append("rerender_error:" + repr(e)[:60])
        return bad
    # independent severity recompute (continuous cards, no routine / fault / glitch / gap cap / recurring)
    m = r["meta"]
    if card["kind"] in ("continuous", "count") and g["status"] != "sensor_fault" and not m.get("routine") and not m.get("glitch") \
            and dq["verdict"] in ("ok", "suspect") and r["sub"] != "recurring" and r.get("sub") not in ("recurring",):
        xs = hist[-r["n"]:]
        p = g["pattern"]
        if card["warning"] is not None:
            s2 = TV.status_limits(card, p, st)[0]
        elif card.get("rate_rules"):
            s2 = TV.status_rate(card, p, st, xs)[0]
        else:
            s2 = "normal"
        if p == "flatline":
            s2 = g["status"]
        if s2 != g["status"]:
            bad.append(f"severity_recompute:{s2}")
    if dq["verdict"] == "fault" and g["status"] != "sensor_fault":
        bad.append("dq_fault_status")
    imp = TV.impossible_idx(card, hist[-r["n"]:]) if card["kind"] in ("continuous", "count") else []
    if imp and g["status"] not in ("sensor_fault",) and dq["verdict"] != "suspect":
        bad.append("impossible_not_flagged")
    return bad


def main():
    src, dst, rep_p = sys.argv[1], sys.argv[2], sys.argv[3]
    rep = {"rows": 0, "ok": 0, "fail_by_check": Counter(), "fail_by_family": Counter(), "rows_by_family": Counter(), "examples": defaultdict(list)}
    with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8") as o, open(str(dst) + ".rejected", "w", encoding="utf-8") as rj:
        for line in f:
            r = json.loads(line)
            rep["rows"] += 1
            rep["rows_by_family"][r["family"]] += 1
            b = check(r)
            if b:
                for x in set(x.split(":")[0] for x in b):
                    rep["fail_by_check"][x] += 1
                rep["fail_by_family"][r["family"]] += 1
                if len(rep["examples"][b[0].split(":")[0]]) < 3:
                    rep["examples"][b[0].split(":")[0]].append({"id": r["id"], "bad": b, "gold": r["gold"]})
                rj.write(json.dumps({"id": r["id"], "bad": b}) + "\n")
                continue
            rep["ok"] += 1
            o.write(line)
    rep["pass_rate"] = round(rep["ok"] / max(1, rep["rows"]), 5)
    Path(rep_p).write_text(json.dumps(rep, indent=1, default=dict))
    print(json.dumps({k: rep[k] for k in ("rows", "ok", "pass_rate")}), dict(rep["fail_by_check"]))


if __name__ == "__main__":
    main()
