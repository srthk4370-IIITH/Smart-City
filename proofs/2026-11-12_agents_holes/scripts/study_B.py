"""Study B (CPU): does a wrong domain-agent claim survive into the 4B r3 report?
Part 1: report suites with gold agent_checks (rwh, rwh2, dev, test_r2) vs rsn_v3_4b_r3 outputs (same files the r3 gate
scored). Unit = one gold wrong/stale/unsupported agent claim (gold checks, ref S#). caught = the 4B lists that ref in
agent_checks with an allowed verdict (score_v3 rule); survived = not listed. Impact = report label/severity wrong.
Part 2: the 2,978-incident r3 training store (synthetic): agent finding vs final report vs operator outcome (proxy gold).
-> raw/B_claims.jsonl, raw/B_summary.json"""
import json, re, sqlite3, sys, collections
from pathlib import Path
P = Path("/mnt/c/Users/hp/Desktop/qidk/proofs") if Path("/mnt/c").exists() else Path("C:/Users/hp/Desktop/qidk/proofs")
RAW = Path(__file__).resolve().parent.parent / "raw"
sys.path.insert(0, str(P / "2026-10-25_reasoner_final/eval"))
import score_v3 as S
SUITES = {"rwh": P / "2026-10-25_reasoner_final/data/incidents_rwh.jsonl",
          "rwh2": P / "2026-10-29_rsn_v3/kaggle/build/r1/heldout/incidents_rwh2.jsonl",
          "dev": P / "2026-10-25_reasoner_final/data/incidents_dev.jsonl",
          "test_r2": P / "2026-11-06_4b_local/data/final/incidents_test_r2.jsonl"}
RES = P / "2026-10-25_reasoner_final/eval/results/rsn_v3_4b_r3"
SEN = re.compile(r"^(S\d+) \[([A-Z]+)\]: (\S+) (\S+) .* \((\w+)\)\s*$")
AG = re.compile(r"agent: pattern=(\S+) status=(\S+) cause=(\S+)")
def agents(user):
    out, cur = {}, None
    for ln in user.splitlines():
        m = SEN.match(ln)
        if m:
            cur = m.group(1); out[cur] = {"domain": m.group(5), "metric": m.group(4)}
        elif cur and (a := AG.search(ln)):
            out[cur].update(pattern=a.group(1), status=a.group(2), cause=a.group(3))
    return out
claims, rows_out = [], collections.Counter()
for suite, f in SUITES.items():
    rows = {json.loads(l)["id"]: json.loads(l) for l in open(f, encoding="utf-8")}
    rp = RES / f"{suite}.jsonl"
    for l in open(rp, encoding="utf-8"):
        rec = json.loads(l); row = rows.get(rec["id"])
        if not row:
            continue
        pass
        if "gold" not in row and "root_metric" not in row.get("meta", {}): continue
        if "gold" not in row: row.setdefault("meta", {}).setdefault("checks", [])
        rows_out[suite] += 1
        g = S.gold_of(row); rep = S.parse((rec.get("final") or {}).get("content"))
        ag = agents(row["messages"][1]["content"])
        gold_claims = {}
        if "gold" not in row:
            gr = json.loads(row["messages"][-1]["content"])
            gold_claims = {c["ref"]: (c.get("claim", ""), c.get("verdict")) for c in gr.get("agent_checks", [])}
        pc = [c for c in (rep or {}).get("agent_checks") or [] if isinstance(c, dict)] if isinstance(rep, dict) else []
        lab = g["labels"].get((rep or {}).get("label"), 0.0) if isinstance(rep, dict) else 0.0
        sev = g["sevs"].get((rep or {}).get("severity"), 0.0) if isinstance(rep, dict) else 0.0
        gsev = max(g["sevs"], key=g["sevs"].get)
        for ref, vs in g["checks"].items():
            a = ag.get(ref, {})
            claim, gv = gold_claims.get(ref, ("", None))
            caught = any(c.get("ref") == ref and c.get("verdict") in vs for c in pc)
            ckind = claim.split()[0] if claim else "?"
            claims.append({"suite": suite, "id": rec["id"], "family": row.get("family"), "ref": ref, "domain": a.get("domain", "?"),
                           "agent_pattern": a.get("pattern"), "agent_status": a.get("status"), "agent_cause": a.get("cause"),
                           "claim_kind": ckind, "gold_verdict": gv, "parsed": isinstance(rep, dict), "caught": caught,
                           "label_ok": lab >= 1.0, "sev_ok": sev >= 1.0, "gold_sev": gsev,
                           "rep_sev": (rep or {}).get("severity") if isinstance(rep, dict) else None,
                           "sev_follows_agent": isinstance(rep, dict) and rep.get("severity") == a.get("status") and a.get("status") != gsev})
with open(RAW / "B_claims.jsonl", "w") as fh:
    for c in claims:
        fh.write(json.dumps(c) + "\n")
def agg(key):
    d = collections.defaultdict(lambda: collections.Counter())
    for c in claims:
        k = key(c); d[k]["n"] += 1; d[k]["caught"] += c["caught"]
        if not c["caught"]:
            d[k]["survived"] += 1; d[k]["survived_bad_report"] += (not c["label_ok"] or not c["sev_ok"])
            d[k]["survived_sev_follows_agent"] += c["sev_follows_agent"]
        else:
            d[k]["caught_bad_report"] += (not c["label_ok"] or not c["sev_ok"])
    return {str(k): dict(v) for k, v in sorted(d.items(), key=lambda x: -x[1]["n"])}
summ = {"rows": dict(rows_out), "claims": len(claims), "all": agg(lambda c: "ALL"), "suite": agg(lambda c: c["suite"]),
        "domain": agg(lambda c: c["domain"]), "claim_kind": agg(lambda c: c["claim_kind"]),
        "agent_status": agg(lambda c: c["agent_status"]), "agent_pattern": agg(lambda c: c["agent_pattern"]),
        "domain_x_kind": agg(lambda c: f'{c["domain"]}/{c["claim_kind"]}'), "family": agg(lambda c: c["family"])}
# reports where the 4B checks a claim nobody flagged (false correction)
# Part 2: store
db = sqlite3.connect(str(P / "2026-11-06_4b_local/data/store/fog_store_r3.sqlite"))
q = db.execute("""select i.id,i.label,i.severity,i.outcome,s.domain,s.status,s.pattern,s.likely_cause from incident i
                  join incident_sensor s on s.incident_id=i.id where s.ref='S1'""").fetchall()
st = collections.defaultdict(collections.Counter)
for iid, lab, sev, out, dom, ast, pat, cause in q:
    k = dom
    st[k]["n"] += 1
    if out == "false_alarm":
        st[k]["false_alarm"] += 1
        st[k]["fa_agent_alarm"] += ast in ("warning", "critical")
        st[k]["fa_report_alarm"] += sev in ("warning", "critical")
    if out in ("sensor_repaired", "sensor_replaced"):
        st[k]["true_fault"] += 1
        st[k]["tf_agent_fault"] += ast == "sensor_fault" or cause == "sensor_fault"
        st[k]["tf_report_fault"] += lab == "sensor_fault"
    st[k]["agent_fault_report_not"] += (ast == "sensor_fault") and lab != "sensor_fault"
    st[k]["agent_status_eq_report_sev"] += ast == sev
summ["store_S1"] = {k: dict(v) for k, v in sorted(st.items())}
(RAW / "B_summary.json").write_text(json.dumps(summ, indent=1))
a = summ["all"]["ALL"]; print("rows", dict(rows_out), "claims", len(claims), a)
for k in ("suite", "domain", "claim_kind", "agent_status"):
    print("--", k)
    for kk, v in summ[k].items(): print(f"  {kk:28s} n={v['n']:4d} caught={v['caught']:4d} survived={v.get('survived',0):3d} surv_bad={v.get('survived_bad_report',0)} sev_follow={v.get('survived_sev_follows_agent',0)} caught_bad={v.get('caught_bad_report',0)}")
print("-- store"); [print(" ", k, v) for k, v in summ["store_S1"].items()]
