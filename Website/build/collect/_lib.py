"""Shared helpers for the evidence-site collectors (DATA agent).

Every collector reads source files (proofs/, HANDBOOK.md, training results, the live
training log read-only) and writes Website/data/<topic>/<id>.json in the data contract:
  {meta:{id,title,topic,unit,n,source_files,script,generated_at,notes,...}, series:[...], ci:[...]}

series = [{name, role: "ours"|"alt"|"ref", points:[{x, y, n?, k?, lo?, hi?, label?}]}]
Rates are fractions in [0,1] unless meta.unit says otherwise; lo/hi are 95% CIs.
No raw sensor data is ever written (see FORBIDDEN_KEYS, enforced by run_all.py).
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # C:\Users\hp\Desktop\qidk
WEB = ROOT / "Website"
DATA = WEB / "data"
PROOFS = ROOT / "proofs"
HB = ROOT / "HANDBOOK.md"
TRAIN = ROOT / "Code" / "smart-city-edge-agent" / "training"
APP = ROOT / "Code" / "smart-city-edge-agent" / "app"
WSL_RUN = Path(r"\\wsl.localhost\Ubuntu\home\hp_srthk4370\smartcity_runs\agents_v2")

NOW = _dt.datetime.now().replace(microsecond=0).isoformat()

FORBIDDEN_KEYS = {"xs", "base", "prompt", "prompts", "raw", "text", "observations",
                  "values", "series_values", "readings"}


def rel(p) -> str:
    p = Path(p)
    try:
        return str(p.resolve().relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def read_jsonl(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def text(p) -> str:
    return Path(p).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- statistics
def wilson(k: int, n: int, z: float = 1.96):
    if n <= 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


def rate(k: int, n: int, **kw):
    lo, hi = wilson(k, n)
    d = {"y": round(k / n, 4) if n else None, "k": int(k), "n": int(n), "lo": lo, "hi": hi,
         "ci_method": "wilson95"}
    d.update(kw)
    return d


def rate_from(r: float, n: int, **kw):
    """Rate known only as a rounded fraction: k = round(r*n)."""
    return rate(int(round(r * n)), n, **kw)


def binom_two_sided(b: int, c: int) -> float:
    """Exact two-sided McNemar (binomial on discordant pairs)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    s = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return float(f"{min(1.0, 2 * s):.3g}")


def mcnemar(a_ok, b_ok):
    b = sum(1 for x, y in zip(a_ok, b_ok) if x and not y)
    c = sum(1 for x, y in zip(a_ok, b_ok) if y and not x)
    return {"only_a": b, "only_b": c, "n": len(a_ok), "p_exact": binom_two_sided(b, c),
            "test": "McNemar exact (binomial on discordant pairs)"}


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def t_ci(xs):
    xs = [float(x) for x in xs]
    n = len(xs)
    if n < 2:
        return (None, None)
    m = mean(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    # t quantiles for small n (two-sided 95%)
    tq = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
          9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042}
    df = n - 1
    t = tq.get(df) or next((tq[k] for k in sorted(tq) if k >= df), 1.96)
    h = t * sd / math.sqrt(n)
    return (round(m - h, 4), round(m + h, 4))


def boot_ci(xs, B=2000, seed=7, stat=mean):
    xs = list(xs)
    if len(xs) < 2:
        return (None, None)
    rnd = random.Random(seed)
    vals = sorted(stat([xs[rnd.randrange(len(xs))] for _ in xs]) for _ in range(B))
    return (round(vals[int(0.025 * B)], 4), round(vals[int(0.975 * B) - 1], 4))


def pt(x, y, **kw):
    d = {"x": x, "y": y}
    d.update({k: v for k, v in kw.items() if v is not None})
    return d


def ser(name, points, role="alt", **kw):
    d = {"name": name, "role": role, "points": points}
    d.update(kw)
    return d


def hb_section(sec: str) -> str:
    return f"HANDBOOK.md#{sec}"


# ---------------------------------------------------------------- writer
WRITTEN: list[dict] = []


def write(topic, id, title, unit, series, source_files, script, n=None, notes="",
          chart=None, claim=None, why=None, table=None, extra=None, ci=None):
    assert re.fullmatch(r"[a-z0-9_]+", id), id
    srcs = []
    for s in source_files:
        if isinstance(s, Path):
            srcs.append(rel(s))
        else:
            srcs.append(str(s).replace("\\", "/"))
    srcs = list(dict.fromkeys(srcs))
    if ci is None:
        ci = []
        for s in series or []:
            for p in s.get("points", []):
                if p.get("lo") is not None and p.get("hi") is not None:
                    ci.append({"series": s["name"], "x": p["x"], "lo": p["lo"], "hi": p["hi"],
                               "method": p.get("ci_method", "wilson95")})
    if n is None:
        ns = [p.get("n") for s in series or [] for p in s.get("points", []) if p.get("n")]
        n = max(ns) if ns else None
    meta = {"id": id, "title": title, "topic": topic, "unit": unit, "n": n,
            "source_files": srcs, "script": rel(script), "generated_at": NOW, "notes": notes}
    if chart:
        meta["chart"] = chart
    if claim:
        meta["claim"] = claim
    if why:
        meta["why"] = why
    obj = {"meta": meta, "series": series or []}
    if ci:
        obj["ci"] = ci
    if table:
        obj["table"] = table
    if extra:
        obj.update(extra)
    out = DATA / topic / f"{id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    WRITTEN.append(meta)
    return obj


def check_no_raw(obj, path="$"):
    """Return list of offending paths (forbidden keys or long float arrays)."""
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            # a forbidden key holding text or a list is raw content; a dict of statistics (e.g. token counts) is fine
            if k in FORBIDDEN_KEYS and isinstance(v, (str, list)) and v:
                bad.append(f"{path}.{k}")
            bad += check_no_raw(v, f"{path}.{k}")
    elif isinstance(obj, list):
        if len(obj) > 40 and all(isinstance(x, float) for x in obj):
            bad.append(f"{path}[float array len {len(obj)}]")
        for i, v in enumerate(obj[:5000]):
            bad += check_no_raw(v, f"{path}[{i}]")
    return bad


def parse_agent_json(s: str):
    """Parse the pattern/status/cause from a model answer (stopped before 'action')."""
    if not s:
        return None
    t = s.strip()
    # strict, same as the study scripts: the answer as-is, or closed where generation stopped at "action"
    for cand in (t, t.rstrip(", ") + "}"):
        try:
            d = json.loads(cand)
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- consolidation (round 2)
# Datasets removed from the published catalog -> the dataset that now carries their notes.
# Old ids still resolve through canon(); run_all.py folds the removed dataset's title/claim/notes/table into the target.
REDIRECT = {
    # latency
    "lat_async_init": "lat_route_agent_call", "lat_action_trim": "lat_route_agent_call", "lat_phase_trace": "lat_route_incident",
    "lat_genieapp_batch": "lat_route_incident", "lat_gap_sweep": "lat_route_incident", "lat_word_limits": "lat_call_breakdown",
    "lat_genie_settings": "lat_call_breakdown", "lat_bandwidth_roof": "lat_call_breakdown", "lat_two_windows": "lat_ctx2048",
    "lat_rejected_lade": "lat_rejected_ideas", "lat_rejected_grammar": "lat_rejected_ideas", "lat_rejected_multigraph": "lat_rejected_ideas",
    "lat_rejected_rpc": "lat_rejected_ideas", "lat_rejected_continuous_batching": "lat_rejected_ideas",
    "lat_rejected_parallel_npu": "lat_rejected_ideas", "lat_rejected_prewarm": "lat_rejected_ideas",
    # hardware
    "hw_platform_paths": "uc_edge_offline", "hw_gpu_bench_knobs": "hw_gpu_batched", "hw_gpu_bringup_failures": "hw_grid",
    "hw_grid_peak_temp": "hw_grid", "hw_memory": "hw_board_thermal", "hw_htp_knob_sweep": "hw_htp_batching", "hw_ui_cpu": "hw_board_thermal",
    # accuracy
    "acc_action_derived": "acc_device54_engines", "acc_test900_partial": "acc_device54_engines", "acc_device54_per_role": "acc_device54_engines",
    "acc_fakequant_host": "acc_quant_waterfall", "acc_device_v1_validation": "acc_quant_waterfall",
    # agent design
    "ad_window_variety": "ad_window_headline", "ad_window_paired": "ad_window_headline", "ad_window_subthr_called": "ad_window_old_events",
    "ad_placement_called": "ad_placement_heatmap", "ad_placement_paired": "ad_placement_curve", "ad_longrange_per_family": "ad_longrange_arms",
    "ad_longrange_paired": "ad_longrange_arms", "ad_modes_latency": "ux_mode2_vs_mode3_latency", "ad_event_gate": "uc_alert_reduction",
    "ad_disagreement": "ad_policy_gate", "ad_review_answers": "ad_policy_gate", "ad_self_learning": "uc_human_in_loop",
    "ad_reasoner_plan": "hw_board_thermal",
    # refinement
    "ref_go_tests": "ref_device_runs", "ref_ui_checks": "ref_device_runs",
    # training
    "tv2_speed": "tv2_sessions", "tv2_progress": "tv2_sessions", "tv2_v1_loss_curve": "tv2_loss_curve",
    # dataset
    "ds_patterns": "ds_families", "ds_event_active": "ds_families", "ds_confidence": "ds_families", "ds_mix": "ds_families",
    "ds_label_alarm_rate": "ds_routine", "ds_tokens_by_window": "ds_tokens", "ds_hvac_injection": "ds_hvac_real_labels",
    "ds_hvac_profile": "ds_hvac_real_labels", "ds_v1_dataset": "ds_roles", "ds_status": "ds_roles", "ds_event_size": "ds_event_age",
    "ds_source_data": "uc_coverage",
    # app / ux
    "ux_mode3_latency_runs": "ux_stress_runs", "ux_v6_final_checks": "ux_stress_runs", "ux_report_page_checks": "ux_screenshots",
    "ux_severity_from_reasoner": "ux_screenshots", "ux_hardening": "ux_fault_injection",
    # ops / timeline
    "ops_ram_guard": "ops_power_events", "ops_v1_thermal_fix": "ops_incidents", "ops_disk": "ops_incidents",
    "tl_commits": "tl_milestones", "tl_proofs": "tl_milestones",
}


def canon(id):
    seen = set()
    while id in REDIRECT and id not in seen:
        seen.add(id)
        id = REDIRECT[id]
    return id
