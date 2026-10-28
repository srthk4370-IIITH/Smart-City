"""Regenerate everything in Website/data/ from the sources.

  py -3 Website/build/collect/run_all.py

Order: topic collectors -> decisions -> route -> qa -> status -> raw-data guard -> catalog -> packs -> README.
Read-only on proofs/, HANDBOOK.md, the repo and the WSL training folder. Writes only under Website/data/.
"""
import gzip
import hashlib
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import *  # noqa

import accuracy, agent_design, latency, hardware, refinement, app_ux, training_v2, dataset_v2, ops, timeline, extras  # noqa
import use_case, situations  # noqa
import decision_groups, route, qa, status, today  # noqa

TOPICS = ["use_case", "situations", "latency", "hardware", "accuracy", "agent_design", "refinement", "training_v2", "dataset_v2", "app_ux", "ops", "timeline"]
TOPIC_TITLES = {"use_case": "Use case: what it is for, in numbers", "situations": "Situations: measured incidents, start to report", "latency": "Latency", "hardware": "Hardware (NPU, GPU, thermals, memory)", "accuracy": "Accuracy",
                "agent_design": "Agent design (windows, placement, 12 h checks, modes, gate)", "refinement": "Refined re-analysis",
                "training_v2": "Training v2 run", "dataset_v2": "Dataset v2 and source data", "app_ux": "App, stress tests and UX",
                "ops": "Operations (crashes, sleeps, disk, power)", "timeline": "Timeline"}


def clean():
    for t in TOPICS:
        d = DATA / t
        if d.exists():
            shutil.rmtree(d)
    p = DATA / "packs"
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)


def strip_sample(r, keep):
    return {k: r.get(k) for k in keep if k in r}


def gz(name, obj):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    bad = check_no_raw(obj)
    assert not bad, f"pack {name} has raw-looking content: {bad[:5]}"
    p = DATA / "packs" / name
    with gzip.open(p, "wb", compresslevel=9) as f:
        f.write(raw)
    return {"file": f"packs/{name}", "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "items": obj.get("n") if isinstance(obj, dict) else None, "description": obj.get("description") if isinstance(obj, dict) else None}


def packs(samples, tv2):
    out = []
    allds = {}
    for p in sorted(DATA.glob("*/*.json")):
        if p.parent.name in TOPICS:
            allds[p.stem] = read_json(p)
    out.append(gz("all_datasets.json.gz", {"description": "every dataset in data/<topic>/ (aggregates, CIs, tables)", "n": len(allds), "datasets": allds}))
    keep = ["role", "gold_pattern", "_gold", "_pred", "json", "pattern", "status", "likely_cause", "action", "action_derived", "evidence", "policy", "tokens", "latency_s"]
    HA = PROOFS / "2026-10-16_htpd_accuracy"
    dev = {"genie_device54": [strip_sample(r, keep) for r in read_jsonl(TRAIN / "results/device_eval_samples.jsonl")],
           "htpd_v1_device54": [strip_sample(r, keep) for r in read_jsonl(HA / "device54/samples.jsonl")],
           "htpd_final_device54": [strip_sample(r, keep) for r in read_jsonl(HA / "device54_v5pc/samples.jsonl")],
           "htpd_final_test900_partial": [strip_sample(r, keep) for r in read_jsonl(HA / "test900/samples.jsonl")]}
    out.append(gz("device_accuracy_scores.json.gz", {"description": "per-window predicted vs gold labels and pass/fail flags on the QIDK (no inputs)",
                                                     "n": sum(len(v) for v in dev.values()), **dev}))
    out.append(gz("window_study_scores.json.gz", {"description": "per-call labels and scores, window study (604 cases x 4 lengths); no sensor values",
                                                  "n": len(samples["window_study_samples"]), "rows": samples["window_study_samples"]}))
    out.append(gz("placement_study_scores.json.gz", {"description": "per-call labels and scores, placement study (208 events x 6 onsets); no sensor values",
                                                     "n": len(samples["placement_samples"]), "rows": samples["placement_samples"]}))
    rep = read_json(PROOFS / "2026-10-16_htpd_v6_app_stress_report_final.json")
    incs = [{"tag": i["tag"], "id": i["id"], "mode": i["mode"], "state": i["state"], "npu_calls": i["npu_calls"], "total_ms": i["total_ms"],
             "agents": [strip_sample(a, ["ref", "role", "valid", "pattern", "status", "cause", "action", "repairs", "errors"]) for a in i["agents"]]}
            for i in rep["incidents"]]
    out.append(gz("app_stress_v6.json.gz", {"description": "final htpd v6 app stress run: every check and per-incident timings/labels (no observation text)",
                                            "n": len(rep["results"]), "checks": [{"check": r["check"], "ok": r["ok"]} for r in rep["results"]], "incidents": incs}))
    man = read_json(PROOFS / "2026-10-17_retrain_v2/dataset_manifest.json")
    man = {k: v for k, v in man.items() if k != "heldout_nodes"}
    man["heldout_node_counts"] = {r: len(v) for r, v in read_json(PROOFS / "2026-10-17_retrain_v2/dataset_manifest.json")["heldout_nodes"].items()}
    chk = read_json(PROOFS / "2026-10-17_retrain_v2/dataset_checks.json")
    for s in chk["results"].values():
        s.pop("examples", None)
    out.append(gz("dataset_v2_composition.json.gz", {"description": "v2 dataset manifest and QA check results (aggregates only; sensor IDs reduced to counts)",
                                                     "n": man["splits"]["train"]["n"], "manifest": man, "checks": chk}))
    ev = training_v2.parse_log(training_v2.log_path())
    out.append(gz("training_v2_metrics.json.gz", {"description": "parsed training log: steps, train loss (logged and per token), dev loss, thermal pauses, sessions",
                                                  "n": len(ev["train"]), "steps": ev["steps"], "train": ev["train"], "eval": ev["eval"],
                                                  "thermal": ev["thermal"], "best": ev["best"]}))
    out.append(gz("decisions_route_qa.json.gz", {"description": "decisions, route and Q&A as published", "n": None,
                                                 "decisions": read_json(DATA / "decisions.json"), "route": read_json(DATA / "route.json"),
                                                 "qa": read_json(DATA / "qa.json"), "status": read_json(DATA / "status.json")}))
    return out


CLAIMS = {  # one-line takeaways for datasets whose collector did not set one (numbers from the dataset itself)
    "acc_pipeline_parity": "Every identity gate passed: 400/400 prompts byte-identical to training",
    "acc_v1_host_per_role": "Fine-tuned 87-100% per role vs rules 53-63% (occupancy excluded: circular)",
    "ad_detector_tuning_frontier": "At 15% false alarms the raw 12 h check catches 64% of old steps, the daily baseline 23%",
    "ad_placement_heatmap": "Steps are right from 1 h; oscillation and slow rises only at 3 h",
    "ad_policy_gate": "Transparent repairs: agent pass rate 3/6 -> 5/6, nothing invented",
    "ad_window_per_family": "At 4 h, 83-100% of classic patterns are flagged; recurring small spikes only 32%",
    "ux_fault_injection": "Killed processes recover: backend in 8 s, NPU daemon in <= 15 s",
    "ux_screenshots": "Operator UI before and after the report-page and refinement work",
    "ds_event_age": "Training events range from fresh (<= 1 h) to old (> 3 h), not just 1-3 h",
    "ds_families": "Events are 29% of rows; the rest teaches faults, routines, drifts and old shifts",
    "ds_fault_kind": "Seven sensor-fault kinds, from stuck to quantised readings",
    "ds_routine": "Over 20 kinds of normal routine labelled normal (hard negatives)",
    "ds_tokens": "Prompts ~733 tokens; answers ~76 tokens until the derived 'action'",
    "hw_board_thermal": "Idle ~43 C after the UI fix; chaos peaks 94-96 C need a heatsink",
    "hw_grid_agreement": "llama.cpp on the NPU agrees with Genie on 22/26 agent patterns; the GPU on 8/12",
    "lat_htpd_levers": "Verified drafting: 4 agents 14.9 s -> 5.8 s with identical answers",
    "ops_power_events": "1 blue screen, 1 thermal sleep and 6 lid standbys during training",
    "ref_stage_timing": "Refined reports land 37 s and 74 s after the early one at 2 s demo polls",
    "tl_milestones": "Spec (17 Sep) -> NPU fine-tune (7 Oct) -> batched NPU daemon (16 Oct) -> v2 training (17 Oct+)",
    "tv2_interruptions": "Eight interruption causes found; each now has a guard",
    "tv2_plan": "v2: 35,946 examples, 6 roles, r=32 (v1: 6,480, 5 roles, r=16)",
    "tv2_sessions": "Training survives stops: every session resumed from a checkpoint",
}


def fold():
    """Remove redundant/thin datasets; fold their content into the dataset named in _lib.REDIRECT."""
    files = {p.stem: p for t in TOPICS for p in (DATA / t).glob("*.json")}
    for old in sorted(REDIRECT):
        if old not in files:
            continue
        tgt = canon(old)
        assert tgt in files and tgt not in REDIRECT, (old, tgt)
        o = read_json(files[old])
        t = read_json(files[tgt])
        entry = {"id": old, "title": o["meta"]["title"], "unit": o["meta"]["unit"], "n": o["meta"].get("n"),
                 "claim": o["meta"].get("claim"), "notes": o["meta"].get("notes"), "source_files": o["meta"]["source_files"],
                 "series": o.get("series", [])}
        for k in ("table", "paired_tests", "paired", "extra"):
            if k in o:
                entry[k] = o[k]
        t.setdefault("folded", []).append(entry)
        t["meta"].setdefault("merged_ids", []).append(old)
        t["meta"]["source_files"] = list(dict.fromkeys(t["meta"]["source_files"] + o["meta"]["source_files"]))
        add = o["meta"].get("claim") or o["meta"]["title"]
        t["meta"]["notes"] = (t["meta"].get("notes") or "") + f" | Also ({old}): {add}."
        files[tgt].write_text(json.dumps(t, indent=1, ensure_ascii=False), encoding="utf-8")
        files[old].unlink()
    for t in TOPICS:
        for p_ in (DATA / t).glob("*.json"):
            d = read_json(p_)
            if not d["meta"].get("claim") and p_.stem in CLAIMS:
                d["meta"]["claim"] = CLAIMS[p_.stem]
                p_.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    # every published dataset must have real points and a claim
    for t in TOPICS:
        for p in (DATA / t).glob("*.json"):
            d = read_json(p)
            pts = [q for s_ in d["series"] for q in s_["points"] if q.get("y") is not None]
            assert len(pts) >= 2, f"{p.stem} has fewer than 2 data points"
            assert d["meta"].get("claim"), f"{p.stem} has no claim"


def readme(catalog):
    lines = ["# Website/data (local only, generated)", "",
             "Generated by `py -3 Website/build/collect/run_all.py`; checked by `py -3 Website/build/verify.py`.",
             "Plain JSON, gitignored; `build/build.py` encrypts it into `dist/`. No raw sensor data: aggregates, CIs and per-sample scores only.", "",
             "Top-level: `catalog.json` (index), `decisions.json`, `route.json`, `qa.json`, `status.json`, `packs/*.json.gz` (downloads).", ""]
    for t in TOPICS:
        lines.append(f"## {TOPIC_TITLES[t]} (`{t}/`)")
        for m in [c for c in catalog["datasets"] if c["topic"] == t]:
            lines.append(f"- `{m['id']}`: {m['title']}")
        lines.append("")
    lines.append("## Packs (`packs/`)")
    for p in catalog["packs"]:
        lines.append(f"- `{p['file']}`: {p['description']}")
    (DATA / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    t0 = time.time()
    DATA.mkdir(parents=True, exist_ok=True)
    clean()
    accuracy.main()
    samples = agent_design.main()
    latency.main(); hardware.main(); refinement.main(); app_ux.main()
    tv2 = training_v2.main()
    dataset_v2.main(); ops.main(); timeline.main(); extras.main(); use_case.main(); situations.main()
    before = len(list(DATA.glob("*/*.json"))) - len(list((DATA / "raw").glob("*.json")))
    fold()
    decision_groups.main(); route.main(); qa.main(); status.main(); today.main()
    # raw-data guard over every published JSON
    problems = {}
    for p in DATA.rglob("*.json"):
        if p.relative_to(DATA).parts[0] == "raw":
            continue  # raw explorer data: included on purpose (SPEC data policy 3, user 2026-10-19); still encrypted
        bad = check_no_raw(read_json(p))
        if bad:
            problems[rel(p)] = bad[:5]
    assert not problems, f"raw-data guard failed: {problems}"
    metas = []
    for p in sorted(DATA.glob("*/*.json")):
        if p.parent.name in TOPICS:
            metas.append(read_json(p)["meta"])
    pk = packs(samples, tv2)
    catalog = {"generated_at": NOW, "script": rel(Path(__file__)), "topics": TOPICS, "topic_titles": TOPIC_TITLES,
               "counts": {t: sum(1 for m in metas if m["topic"] == t) for t in TOPICS},
               "datasets": [{k: m.get(k) for k in ("id", "title", "topic", "unit", "n", "source_files", "script", "generated_at", "notes", "claim", "why", "chart")} for m in metas],
               "top_level": ["decisions.json", "route.json", "qa.json", "status.json"], "packs": pk}
    (DATA / "catalog.json").write_text(json.dumps(catalog, indent=1, ensure_ascii=False), encoding="utf-8")
    readme(catalog)
    print(f"datasets: {before} before consolidation -> {len(metas)} published {catalog['counts']}")
    print(f"decision groups: {read_json(DATA / 'decisions.json')['meta']['n']} (children {read_json(DATA / 'decisions.json')['meta']['n_children']})  qa: {read_json(DATA / 'qa.json')['meta']['n']}  route: {read_json(DATA / 'route.json')['meta']['counts']}")
    print(f"packs: {[p['file'] for p in pk]}")
    print(f"done in {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
