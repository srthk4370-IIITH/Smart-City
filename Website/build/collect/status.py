"""data/status.json: current position at build time (training read live from WSL, read-only)."""
import datetime as dt
import subprocess
import training_v2 as tv
from _lib import *

S = __file__


def main():
    lp = tv.log_path()
    ev = tv.parse_log(lp)
    steps = ev["steps"]
    last = steps[-1] if steps else None
    recent = [s["s_per_step"] for s in steps[-20:]]
    sps = sorted(recent)[len(recent) // 2] if recent else None
    remaining = 4494 - (last["step"] if last else 0)
    eta_h = round(remaining * sps / 3600, 1) if sps else None
    m = re.findall(r"all-done ETA (\w+ \d+ \d\d:\d\d)", text(lp))
    best = ev["best"][-1] if ev["best"] else None
    status_file = None
    try:
        status_file = read_json(WSL_RUN / "session_status.json")
    except Exception:
        pass
    sess = ev["sessions"][-1] if ev["sessions"] else {}
    fresh = bool(last) and (dt.datetime.now() - dt.datetime.fromisoformat(last["t"])).total_seconds() < 1800
    running = bool(sess) and not sess.get("hours") and fresh
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %ad %s", "--date=short"], capture_output=True, text=True, timeout=30).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True, timeout=60).stdout.strip())
    except Exception:
        head, dirty = None, None
    out = {
        "meta": {"title": "Where we are", "generated_at": NOW, "script": rel(S),
                 "source_files": ["WSL:~/smartcity_runs/agents_v2/train.log (read-only)" if lp != PROOFS / "2026-10-17_retrain_v2/train.log.txt" else rel(lp),
                                  "WSL:~/smartcity_runs/agents_v2/best.json", "HANDBOOK.md#2.37-2.40", "proofs/"],
                 "notes": "Device state is as last recorded in HANDBOOK/proofs; the board was not probed at build time (no adb from the site build)."},
        "training_v2": {
            "state": "running" if running else ("stopped" if sess.get("hours") else "no recent log lines (stalled or stopped)"),
            "step": last["step"] if last else None, "max_steps": 4494,
            "progress": round(last["step"] / 4494, 4) if last else None,
            "last_log_time": last["t"] if last else None,
            "best_dev_loss": best["loss"] if best else None, "best_step": best["step"] if best else None,
            "dev_loss_history": [{"step": e["step"], "loss": e["eval_loss"]} for e in ev["eval"]],
            "recent_s_per_step": sps, "eta_training_hours": eta_h,
            "trainer_eta_text": m[-1] if m else None,
            "eta_note": "training time only; excludes thermal pauses beyond the moving average, stops and sessions not running",
            "session_status_file": status_file,
            "evidence_ids": ["tv2_loss_curve", "tv2_progress", "tv2_sessions"]},
        "deployed_on_qidk": {
            "board": "Qualcomm QIDK, Snapdragon 8 Gen 3 (SM8650), Hexagon V75 NPU, Android 14",
            "app": "Smart City Edge (com.iiith.smartcityedge), native APK, starts the Go backend as the shell user via local adbd",
            "npu_engine": "htpd v6 (llama.cpp Hexagon daemon; 13 agent streams x 768 ctx + 4096 synthesizer ctx; drafting, prefix cache, NEON argmax); Genie/genied kept as revert",
            "model": "v1 fine-tuned Llama 3.2 3B (GPTQ int4 weights) repacked exactly to GGUF Q4_0/Q8_0 for htpd",
            "agent_window": "4 h (48 x 5 min); refinements at +1.5 h and +3 h; 12 h level-shift / drift checks as evidence",
            "severity_and_titles": "from the analysis (severity.go, title.go stubs until the cross-domain reasoner)",
            "accuracy_on_device": {"pattern": 0.907, "status": 0.944, "cause": 0.87, "json": 1.0, "policy": 1.0, "n": 54, "evidence_id": "acc_device54_engines"},
            "latency": {"mode3_median_s": 3.8, "chaos_12_agents_s": 20.7, "ab_13_agents_s": 14.7, "evidence_id": "lat_chaos_genie_vs_htpd"},
            "stress_test": {"passed": 132, "total": 135, "failures": "thermal only", "evidence_id": "ux_stress_runs"}},
        "repo": {"head": head, "dirty_working_tree": dirty, "branch_note": "work after the last commit lives in the working tree and proofs/"},
        "next": ["finish retrain v2 (4,494 steps)", "merge -> GGUF Q4_0 (imatrix) -> htpd", "NPU acceptance on test months (RETRAIN_V2_SPEC #20)",
                 "latency pass back to <= 14.7 s (13 agents) / <= 3.8 s typical", "cross-domain reasoner", "900-window rerun; Mode 1/2/3 labelled grid"],
    }
    (DATA / "status.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    o = main()
    print(json.dumps(o["training_v2"], indent=0)[:800])
