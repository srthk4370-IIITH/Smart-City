"""data/today.json: what runs on the board tonight, read from the final-night proof files (read-only).

    py -3 Website/build/collect/today.py

Sources (any may be missing; the Today page then says "pending"):
  proofs/2026-10-28_master/FINAL_STATUS.md, final.log, final/*        final deploy (final.sh F0-F7)
  proofs/2026-10-28_master/split_post.log, final/split_post_result     split-4/6 A/B after the deploy
  proofs/2026-10-28_master/RAG_STATUS.md                               retrieval preliminary report
  proofs/2026-10-28_master/gate_study/table_B50.md                     event-gate study (young windows)
  proofs/2026-10-25_reasoner_final/eval/results/round2_result.txt      rsn_v2 laptop eval
  proofs/2026-10-28_master/final/chaos/chaos_*_incident.json           tonight's app run (aggregates only)
Privacy: only aggregates and status lines leave this script; no sensor windows, prompts, or model texts.
"""
import datetime as dt
import glob
import os
import statistics

from _lib import *  # noqa

S = __file__
M = PROOFS / "2026-10-28_master"
F = M / "final"
RF = PROOFS / "2026-10-27_reasoner_fast"
R2 = PROOFS / "2026-10-25_reasoner_final" / "eval" / "results" / "round2_result.txt"


def stamp(p):
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(p)).replace(microsecond=0).isoformat()
    except OSError:
        return None


def rd(p, limit=60000):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return None


def one(p):
    s = rd(p)
    return s.strip() if s else None


def md_table(md):
    """First markdown table -> list of row lists (header included)."""
    rows = []
    for line in (md or "").splitlines():
        l = line.strip()
        if l.startswith("|") and l.endswith("|"):
            cells = [c.strip() for c in l.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            rows.append(cells)
        elif rows:
            break
    return rows


def result_json(res):
    """The JSON object a night script appends to its Result line (fast-path check): numbers and flags only, no titles."""
    m = re.search(r"(\{.*\})", res or "")
    if not m:
        return None
    try:
        x = json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return None
    return {k: v for k, v in x.items() if k != "title" and isinstance(v, (int, float, bool, str))}


def final_status():
    p = M / "FINAL_STATUS.md"
    s = rd(p)
    out = {"present": s is not None, "file": rel(p), "updated": stamp(p)}
    if not s:
        return out
    m = re.search(r"\*\*Result:\*\*\s*(.+)", s)
    out["result"] = m.group(1).strip() if m else None
    out["passed"] = bool(out["result"] and out["result"].upper().startswith("PASS"))
    out["rolled_back"] = bool(out["result"] and "roll" in out["result"].lower())
    out["fastcheck"] = result_json(out["result"])
    t = md_table(s)
    if t:
        hdr = [h.lower() for h in t[0]]
        out["parts"] = [dict(zip(hdr, r)) for r in t[1:]]
    m = re.search(r"Board state after the run:\s*```\s*\n(.*?)```", s, re.S)
    if m:
        out["board_state"] = [l.strip() for l in m.group(1).splitlines() if l.strip()]
    m = re.search(r"^# FINAL status \((.*?)\)", s, re.M)
    out["written"] = m.group(1) if m else None
    return out


def final_log():
    s = rd(M / "final.log", 400000) or ""
    keep = [l for l in s.splitlines() if re.match(r"^\S+Z (F\d|===|ROLLBACK|rollback)", l)]
    return {"file": rel(M / "final.log"), "updated": stamp(M / "final.log"), "steps": keep[-40:]}


def decisions():
    out = {}
    for k in ("result", "reasoner", "reasoner_why", "agents", "agents_why", "split", "split_post_result", "research_skipped"):
        v = one(F / k)
        if v is not None:
            out[k] = v
    kg = rd(F / "known_good" / "htpd_profile")
    if kg:
        out["known_good_profile"] = [l for l in kg.splitlines() if re.match(r"^(bin|model|reasoner_model|reasoner_split|env)=", l)]
    for k in ("edge-agent.md5", "app.md5"):
        v = one(F / "known_good" / k)
        if v:
            out["known_good_" + k.split(".")[0].replace("-", "_")] = v.split()[0]
    return out


def split_post():
    p = M / "split_post.log"
    s = rd(p) or ""
    lines = [l for l in s.splitlines() if re.match(r"^\S+Z ", l)]
    res = one(F / "split_post_result")
    acc = rd(RF / "raw" / "split_post" / "acc.md")
    return {"present": bool(lines), "file": rel(p), "updated": stamp(p), "steps": lines[-20:], "result": res,
            "done": any("split_post done" in l or "split-3 stays" in l or "nothing to do" in l for l in lines),
            "acc_table": md_table(acc) if acc else None}


def drop_title_cols(md):
    """Remove 'title' columns from markdown tables (incident titles can quote live readings)."""
    out, idx = [], None
    for line in (md or "").splitlines():
        l = line.strip()
        if l.startswith("|") and l.endswith("|"):
            cells = l.strip("|").split("|")
            if idx is None:
                idx = [i for i, c in enumerate(cells) if c.strip().lower() == "title"]
            cells = [c for i, c in enumerate(cells) if i not in idx]
            out.append("|" + "|".join(cells) + "|")
        else:
            idx = None
            out.append(line)
    return "\n".join(out)


def rag_status():
    p = M / "RAG_STATUS.md"
    o = md_file(p)
    if o.get("md"):
        o["md"] = drop_title_cols(o["md"])
        m = re.search(r"\*\*Result:\*\*\s*(.+)", o["md"])
        o["result"] = m.group(1).strip() if m else None
        r = (o["result"] or "").upper()
        o["live"] = bool(r) and not re.search(r"NOT|FAIL|ROLL", r) and bool(re.search(r"PASS|DEPLOYED|LIVE", r))
        o["fastcheck"] = result_json(o["result"])
        col = [r for r in md_table(o["md"])]
        if col and any("preliminary (s)" in c for c in col[0]):
            i = next(j for j, c in enumerate(col[0]) if "preliminary (s)" in c)
            v = [float(r[i]) for r in col[1:] if i < len(r) and re.fullmatch(r"[0-9.]+", r[i])]
            o["prelim_max_s"] = max(v) if v else None
            o["n_incidents"] = len(col) - 1
        m = re.search(r"Retrieval hit rate:\s*(.+)", o["md"])
        o["hit_rate"] = m.group(1).strip() if m else None
        m = re.search(r"APK ([0-9a-f]{8}) \(edge-agent ([0-9a-f]{8})", o["md"])
        if m:
            o["apk"], o["edge_agent"] = m.group(1), m.group(2)
    return o


def status_md(p):
    """A status file written by a night job: md + its **Result:** line + live flag (deployed and not failed/rolled back)."""
    o = md_file(p)
    if o.get("md"):
        o["md"] = drop_title_cols(o["md"])
        m = re.search(r"\*\*Result:\*\*\s*(.+)", o["md"])
        o["result"] = m.group(1).strip() if m else None
        r = (o["result"] or "").upper()
        o["live"] = bool(r) and not re.search(r"NOT |FAIL|ROLL|KEPT|PENDING", r) and bool(re.search(r"PASS|DEPLOYED|LIVE", r))
        m = re.search(r"htpd_v8x\d+", o["md"])
        o["bin"] = m.group(0) if m else None
    return o


def overnight():
    """Only the job table and board line of OVERNIGHT_STATUS.md (the log tails below it quote incident titles)."""
    o = md_file(M / "OVERNIGHT_STATUS.md")
    if o.get("md"):
        o["md"] = o["md"].split("\n## ")[0].strip()
    return o


def md_file(p, limit=30000):
    s = rd(p, limit)
    return {"present": s is not None, "file": rel(p), "updated": stamp(p), "md": s}


def chaos(dirs):
    """Per-scenario timing aggregates from incident JSONs (no sensor data, no titles)."""
    rows = []
    files = []
    for d in dirs:
        files = sorted(glob.glob(str(d / "chaos_*_incident.json")))
        if files:
            src = d
            break
    else:
        return None
    for f in files:
        try:
            x = read_json(f)
        except Exception:  # noqa: BLE001
            continue
        i = x.get("incident") if isinstance(x, dict) else None
        if not isinstance(i, dict):
            rows.append({"scenario": x.get("scenario") if isinstance(x, dict) else None, "state": "no incident"})
            continue
        tl = i.get("timeline") or []

        def secs(t):
            h, m_, s_ = (int(v) for v in t.split(":"))
            return h * 3600 + m_ * 60 + s_

        t0 = t_pre = t_title = None
        for e in tl:
            msg, t = e.get("msg", ""), e.get("t")
            if not t or not re.match(r"\d\d:\d\d:\d\d$", t):
                continue
            if t0 is None and msg.startswith("Event gated"):
                t0 = secs(t)
            if t_pre is None and msg.startswith("Preliminary report shown"):
                t_pre = secs(t)
            if t_title is None and msg.startswith("Reasoner title"):
                t_title = secs(t)
        fin = i.get("final") or {}
        rows.append({
            "scenario": x.get("scenario"), "state": i.get("state"),
            "prelim_s": (t_pre - t0) if (t0 is not None and t_pre is not None) else None,
            "title_s": (t_title - t0) if (t0 is not None and t_title is not None) else None,
            "done_s": round(i["total_ms"] / 1000, 1) if i.get("total_ms") else None,
            "reasoner_s": round(fin["latency_ms"] / 1000, 1) if fin.get("latency_ms") else None,
            "npu_calls": i.get("npu_calls"), "severity": i.get("severity"),
            "valid": bool(fin.get("valid")), "fast_path": bool(i.get("fast_path")),
            "agents": len(i.get("agents") or []),
        })
    done = [r["done_s"] for r in rows if r.get("done_s")]
    summ = {"n": len(rows), "done_valid": sum(1 for r in rows if r.get("state") == "done" and r.get("valid"))}
    if done:
        summ.update(done_min=min(done), done_max=max(done), done_median=round(statistics.median(done), 1))
    for k in ("prelim_s", "title_s", "reasoner_s"):
        v = [r[k] for r in rows if r.get(k) is not None]
        if v:
            summ[k.replace("_s", "") + "_range"] = [min(v), max(v)]
    return {"dir": rel(src), "updated": stamp(files[-1]), "rows": rows, "summary": summ}


def models():
    """md5 sidecars of the staged GGUFs (Code/models_stage), the same files that were pushed to the board."""
    st = ROOT / "Code" / "models_stage"
    out = {}
    for f in sorted(st.glob("*.gguf.md5")):
        v = one(f)
        if v:
            out[f.name[:-4]] = v.split()[0]
    return out


def fastcheck():
    fs = sorted(glob.glob(str(RF / "raw" / "fastcheck_*.json")), key=os.path.getmtime)
    if not fs:
        return None
    try:
        x = read_json(fs[-1])
    except Exception:  # noqa: BLE001
        return None
    keep = {k: v for k, v in x.items() if isinstance(v, (int, float, bool, str)) and len(str(v)) < 200} if isinstance(x, dict) else {}
    return {"file": rel(fs[-1]), "updated": stamp(fs[-1]), "summary": keep}


TITLE_RE = re.compile(r""""title":\s*"(?:[^"\\]|\\.)*",?\s*|title='[^']*'""")


def scrub(o):
    """Drop incident titles quoted inside log lines / result JSON (they can quote live readings)."""
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    if isinstance(o, str):
        return TITLE_RE.sub("", o)
    return o


def main():
    out = {
        "meta": {"title": "Today: what runs on the board", "generated_at": NOW, "script": rel(S),
                 "source_files": [rel(M / "FINAL_STATUS.md"), rel(M / "final.log"), rel(M / "split_post.log"), rel(M / "RAG_STATUS.md"),
                                  rel(M / "gate_study" / "table_B50.md"), rel(R2), rel(M / "CHAIN_STATUS.json"), rel(M / "RSN_V2_RETRY.md"), rel(M / "OVERNIGHT_STATUS.md")],
                 "notes": "Read from the proof files when the site was built; the board itself is not probed by the build."},
        "final": final_status(),
        "final_log": final_log(),
        "decisions": decisions(),
        "split_post": split_post(),
        "rag": rag_status(),
        "rsn_v2_retry": status_md(M / "RSN_V2_RETRY.md"),
        "overnight": overnight(),
        "gate_study": md_file(M / "gate_study" / "table_B50.md"),
        "rsn_v2_eval": md_file(R2, 8000),
        "chaos_tonight": chaos([F / "chaos"]),
        "fastcheck": fastcheck(),
        "models_md5": models(),
    }
    out = scrub(out)
    bad = check_no_raw(out)
    assert not bad, f"today.json has raw-looking content: {bad[:5]}"
    (DATA / "today.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    o = main()
    print(json.dumps({k: (v.get("present") if isinstance(v, dict) and "present" in v else bool(v)) for k, v in o.items() if k != "meta"}))
