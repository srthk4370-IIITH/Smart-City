"""Training v2 datasets: loss curve, sessions, speed, thermal pauses, interruptions, plan; plus v1 training for contrast.
Reads the live training log in WSL READ-ONLY (falls back to the copy in proofs/)."""
import datetime as dt
from _lib import *

S = __file__
T = "training_v2"
RV = PROOFS / "2026-10-17_retrain_v2"
V1 = TRAIN / "results" / "agents_20261006_2101"
START_DATE = dt.date(2026, 10, 17)
GRAD_ACCUM = 16


def log_path():
    p = WSL_RUN / "train.log"
    try:
        if p.exists() and p.stat().st_size >= (RV / "train.log.txt").stat().st_size:
            return p
    except OSError:
        pass
    return RV / "train.log.txt"


def parse_log(path, start_date=START_DATE):
    day, prev = start_date, None
    ev = {"steps": [], "train": [], "eval": [], "sessions": [], "thermal": [], "best": []}
    cur_step, sess = 0, None
    for line in text(path).splitlines():
        m = re.match(r"\[(\d\d):(\d\d):(\d\d)\] (.*)", line)
        if not m:
            continue
        t = dt.time(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if prev and t < prev and (dt.datetime.combine(day, prev) - dt.datetime.combine(day, t)).seconds > 3600:
            day += dt.timedelta(days=1)
        prev = t
        ts = dt.datetime.combine(day, t)
        body = m.group(4)
        if body.startswith("=== v2 session start"):
            sess = {"start": ts.isoformat(), "start_step": None, "end": None, "end_step": None, "end_reason": None,
                    "thermal_pauses": None, "paused_min": None, "peak_gpu_c": None, "s_per_step": []}
            ev["sessions"].append(sess)
            mm = re.search(r"GPU temp (\d+) C", body)
            sess["gpu_c_at_start"] = int(mm.group(1)) if mm else None
            continue
        mm = re.match(r"session: steps (\d+)/(\d+) done", body)
        if mm and sess:
            sess["start_step"] = int(mm.group(1))
            cur_step = int(mm.group(1))
            continue
        mm = re.match(r"step (\d+)/(\d+)\s+([\d.]+)s/step", body)
        if mm:
            cur_step = int(mm.group(1))
            ev["steps"].append({"t": ts.isoformat(), "step": cur_step, "s_per_step": float(mm.group(3))})
            if sess is not None:
                sess["s_per_step"].append(float(mm.group(3)))
                sess["end_step"] = cur_step
                sess["end"] = ts.isoformat()
            continue
        mm = re.match(r"metrics (\{.*\})", body)
        if mm:
            d = json.loads(mm.group(1))
            if "eval_loss" in d:
                ev["eval"].append({"t": ts.isoformat(), "epoch": d["epoch"], "eval_loss": d["eval_loss"],
                                   "eval_runtime_s": d["eval_runtime"], "step": round(d["epoch"] * 4494 / 2)})
            elif "loss" in d and "train_runtime" not in d:
                ev["train"].append({"t": ts.isoformat(), "step": cur_step, "epoch": d["epoch"], "logged_loss": d["loss"],
                                    "loss_per_token": round(d["loss"] / GRAD_ACCUM, 5), "grad_norm": d.get("grad_norm"),
                                    "lr": d.get("learning_rate")})
            continue
        mm = re.match(r"new best dev loss ([\d.]+) at step (\d+)", body)
        if mm:
            ev["best"].append({"t": ts.isoformat(), "loss": float(mm.group(1)), "step": int(mm.group(2))})
            continue
        mm = re.match(r"THERMAL: GPU (\d+) C >= (\d+) C", body)
        if mm:
            ev["thermal"].append({"t": ts.isoformat(), "gpu_c": int(mm.group(1)), "threshold_c": int(mm.group(2))})
            continue
        if body.startswith("STOP requested") and sess:
            sess["end_reason"] = "clean stop (user STOP flag / battery / time window)"
        mm = re.match(r"session ended at step (\d+)/\d+ after ([\d.]+) h; thermal pauses (\d+) \(([\d.]+) min\), peak GPU (\d+) C", body)
        if mm and sess:
            sess.update({"end": ts.isoformat(), "end_step": int(mm.group(1)), "hours": float(mm.group(2)),
                         "thermal_pauses": int(mm.group(3)), "paused_min": float(mm.group(4)), "peak_gpu_c": int(mm.group(5))})
    return ev


CAUSES = [  # (session start prefix, cause of the end when not a clean stop) from RESULTS.md + power_events.txt
    ("2026-10-17T02:00", "restarted after 4 min: supervisor relaunched with WSL capped at 10 GB (Windows had 0.7 GB free)"),
    ("2026-10-17T02:04", "blue screen 05:31 (bugcheck 0xD1 in vfpext.sys, Hyper-V virtual switch); steps 276-300 lost"),
    ("2026-10-17T10:04", "thermal sleep 10:25-13:04 froze it 2.6 h (Sleep Reason: Thermal Zone); stopped by hand at 318"),
    ("2026-10-17T14:15", "supervisor died with the assistant's shell (~15:43); stopped by hand at 443"),
    ("2026-10-17T23:31", "lid closed: Modern Standby 01:12-08:52 froze WSL; user stop at 12:11"),
]


def sessions(ev):
    sup = text(RV / "supervisor.log.txt") if (RV / "supervisor.log.txt").exists() else ""
    modes = re.findall(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d):\d\d\] training resources applied \((.*?)\)", sup)
    out = []
    for s in ev["sessions"]:
        start = s["start"][:16]
        mode = None
        for when, m in modes:
            w = when.replace(" ", "T")
            if w <= start:
                mode = "background (WSL 6 GB / 2 cores)" if "BACKGROUND" in m else "full (" + m + ")"
        cause = next((c for p, c in CAUSES if start.startswith(p)), None)
        sp = s.pop("s_per_step")
        s["median_s_per_step"] = sorted(sp)[len(sp) // 2] if sp else None
        s["mode"] = mode
        s["note"] = cause
        if s.get("end_reason") is None and s.get("hours") is None:
            s["end_reason"] = "running" if s is ev["sessions"][-1] else "interrupted"
        out.append(s)
    return out


SESS_COLS = ["start", "end", "start_step", "end_step", "hours", "mode", "end_reason", "note", "thermal_pauses", "paused_min",
             "peak_gpu_c", "gpu_c_at_start", "median_s_per_step"]


def main():
    lp = log_path()
    ev = parse_log(lp)
    srcs = [lp if lp == RV / "train.log.txt" else "WSL:~/smartcity_runs/agents_v2/train.log (read-only)",
            RV / "train.log.txt", RV / "RESULTS.md", RV / "loss_points.json", RV / "plan.json", RV / "best.json"]
    tr = ev["train"]
    evl = ev["eval"]
    write(T, "tv2_loss_curve", "Retrain v2: dev loss and train loss per token (train = logged loss / 16 grad-accum)", "loss",
          [ser("dev loss (every 300 steps)", [pt(e["step"], e["eval_loss"], epoch=e["epoch"], t=e["t"]) for e in evl], "ours"),
           ser("train loss per token (every 5 steps)", [pt(r["step"], r["loss_per_token"], epoch=r["epoch"]) for r in tr if r["step"]], "alt")],
          srcs, S, n=len(tr), chart={"type": "line", "x": "optimizer step", "y": "loss", "log_y": True},
          claim=f"Dev loss {evl[0]['eval_loss']} -> {min(e['eval_loss'] for e in evl)}; train ~ dev, no overfitting",
          why="The loss is the only accuracy signal until the NPU acceptance test runs.",
          notes="The trainer logs loss summed over 16 micro-batches; divided by 16 it is per token. Dev loss is not accuracy: "
                "acceptance runs on the QIDK NPU after training (RETRAIN_V2_SPEC #20). v1's dev loss (0.027) is on a different, "
                "easier dataset and is not comparable.")
    write(T, "tv2_progress", "Retrain v2: optimizer step over wall-clock time (gaps = interruptions)", "step",
          [ser("step", [pt(s["t"], s["step"]) for s in ev["steps"]], "ours")], srcs, S, chart={"type": "line", "x": "time"},
          notes="Steps are logged every 5. Flat gaps are stops, crashes, sleeps and standby (see tv2_sessions).")
    ss = sessions(ev)
    write(T, "tv2_sessions", "Retrain v2: every training session (resumable 6-8 h sessions)", "h",
          [ser("steps per session", [pt(s["start"], (s["end_step"] or 0) - (s["start_step"] or 0), hours=s.get("hours"),
                                         mode=s["mode"]) for s in ss], "ours", unit="steps")],
          srcs + [RV / "supervisor.log.txt", RV / "power_events.txt"], S, n=len(ss), chart={"type": "timeline"},
          table={"columns": SESS_COLS, "rows": [[s.get(c) for c in SESS_COLS] for s in ss]},
          notes="Times are local. Dates are inferred from the log's HH:MM:SS by day roll-over from 2026-10-17. 'hours', thermal pause "
                "counts and peak come from each session's own summary line.")
    th = [s for s in ss if s.get("thermal_pauses") is not None]
    write(T, "tv2_thermal_pauses", "GPU thermal guard: pauses per session", "minutes",
          [ser("minutes paused", [pt(s["start"], s["paused_min"], pauses=s["thermal_pauses"], hours=s["hours"], peak_c=s["peak_gpu_c"]) for s in th], "ours"),
           ser("share of session paused", [pt(s["start"], round(s["paused_min"] / 60 / s["hours"], 3) if s["hours"] else None) for s in th], "alt", unit="fraction")],
          srcs, S, n=sum(s["thermal_pauses"] for s in th), chart={"type": "bar"},
          claim=f"{sum(s['thermal_pauses'] for s in th)} pauses, {round(sum(s['paused_min'] for s in th) / 60, 1)} h paused; GPU peak 87 C",
          notes="Pause threshold 81 C until 2026-10-17 14:15, then 76 C (at 81 C the laptop had gone into thermal sleep). "
                "The laptop locks the GPU power limit (~50 W), so pausing is the only lever.")
    sp = [s for s in ev["steps"]]
    write(T, "tv2_speed", "Training speed (moving s/step reported by the trainer)", "s/step",
          [ser("s/step", [pt(s["t"], s["s_per_step"], step=s["step"]) for s in sp[::5]], "ours")], srcs, S,
          chart={"type": "line", "x": "time"},
          notes="Background mode 45.5 s/step (79 steps/h); full mode overnight 42 s/step (85 steps/h) per RESULTS.md. Includes "
                "thermal pauses. Every 5th logged point shown.")
    cur = ev["steps"][-1] if ev["steps"] else {"step": None}
    best = ev["best"][-1] if ev["best"] else None
    pe = text(RV / "power_events.txt")
    counts = {"bugcheck (BSOD)": len(re.findall(r"rebooted from a bugcheck", pe)), "unclean reboot (event 41)": len(re.findall(r"\s41 The system has rebooted", pe)),
              "thermal sleep": len(re.findall(r"Sleep Reason: Thermal Zone", pe)), "Modern Standby: lid": len(re.findall(r"entering Modern Standby\s+Reason: Lid", pe))}
    rows = [["10-17 01:53-01:58", "session exited at once, 3x", "Start-Process split the bash -lc command string", "start_v2.sh wrapper with no arguments"],
            ["10-17 02:03", "Windows almost out of RAM", "WSL at 13 GB with model files in page cache", "WSL capped at 10/11 GB; supervisor drops WSL cache below 2.5 GB free"],
            ["10-17 05:45", "blue screen; steps 276-300 lost", "bugcheck 0xD1 in vfpext.sys (Hyper-V virtual switch used by WSL networking)", "WSL networkingMode=none while training; checkpoints every 14 steps; auto-resume at logon"],
            ["10-17 10:25-13:04", "frozen 2.6 h", "sleep, Reason: Thermal Zone", "GPU pause 81 -> 76 C; WSL 4 cores"],
            ["10-17 13:05, 15:43", "supervisor died (training kept running)", "child of the assistant's shell", "launched through WMI; attach mode"],
            ["10-17", "new checkpoint interval ignored", "Trainer restores save_steps from the checkpoint", "train_v2.py rewrites trainer_state.json before resuming"],
            ["10-18 01:12-08:52, 16:18-16:46", "frozen (Modern Standby)", "Reason: Lid (lid closed)", "keep the lid open; lid action 'Do nothing' during full mode"],
            ["10-18 16:18", "ran on battery", "AC unplugged", "battery guard stops cleanly below 40%"]]
    write(T, "tv2_interruptions", "Retrain v2: interruptions, causes and fixes", "events",
          [ser("Windows power events (power_events.txt)", [pt(k, v) for k, v in counts.items()], "ref")],
          [RV / "RESULTS.md", RV / "power_events.txt", RV / "crash_0xD1_analysis.txt", RV / "supervisor.log.txt"], S,
          table={"columns": ["when", "what happened", "cause (evidence)", "fix"], "rows": rows}, chart={"type": "bar"},
          notes="The 2026-10-17 20:10 unclean reboot in power_events.txt has no recorded cause and fell between sessions.")
    plan = read_json(RV / "plan.json")
    pilot = read_json(RV / "pilot.json")
    v1plan = read_json(V1 / "plan.json")
    tab = [["model", "Llama-3.2-3B-Instruct", "Llama-3.2-3B-Instruct"],
           ["method", "QLoRA nf4", "QLoRA nf4"],
           ["LoRA rank / trainable", "r=16 / 24.3 M", f"r={plan['rank']} / 48.6 M"],
           ["roles", "5", "6 (+ HVAC)"],
           ["train examples", str(v1plan["per_role"] * 5), str(plan["train_rows"])],
           ["epochs / optimizer steps", "2 / 810", f"{plan['epochs']} / {plan['max_steps']}"],
           ["grad accumulation", "-", str(plan["grad_accum"])],
           ["lr / max length", "-", f"{plan['lr']} / {plan['max_len']}"],
           ["train tokens", "-", f"{plan['train_tokens']:,}"],
           ["pilot tokens/s / peak VRAM", f"{v1plan['pilot_tokens_per_s']} / {v1plan['pilot_peak_vram_gib']} GiB", f"{pilot['tokens_per_s']} / {pilot['peak_vram_gib']} GiB"],
           ["estimated training hours", "~6.5", str(pilot["est_training_hours"])],
           ["window lengths", "4 h only", "2-12 h (21 lengths)"],
           ["best dev loss", "0.027", str(best["loss"]) if best else "-"]]
    write(T, "tv2_plan", "Training setup: v1 (2026-10-07) vs v2 (in progress)", "-",
          [ser("train examples", [pt("v1", v1plan["per_role"] * 5), pt("v2", plan["train_rows"])], "ours")],
          [RV / "plan.json", RV / "pilot.json", V1 / "plan.json", V1 / "train.log", TRAIN / "RETRAIN_V2_SPEC.md", hb_section("2.40"), hb_section("2.7")],
          S, table={"columns": ["", "v1", "v2"], "rows": tab}, chart={"type": "bar"})
    v1 = parse_log(V1 / "train.log", dt.date(2026, 10, 7))
    write(T, "tv2_v1_loss_curve", "v1 training (2026-10-07): dev loss every ~50 steps", "loss",
          [ser("v1 dev loss", [pt(round(e["epoch"] * 405), e["eval_loss"], epoch=e["epoch"]) for e in v1["eval"]], "alt")],
          [V1 / "train.log", hb_section("2.7")], S, n=len(v1["eval"]), chart={"type": "line", "x": "optimizer step"},
          notes="810 steps, 2 epochs; 405 thermal pauses (67.9 min), peak GPU 87 C, no hibernation (after the 2.1b fixes).")
    return {"current_step": cur["step"], "max_steps": 4494, "best": best, "last_step_time": cur.get("t"),
            "sessions": ss, "log_source": str(srcs[0]) if not isinstance(srcs[0], Path) else rel(srcs[0]),
            "eval": evl, "steps": ev["steps"][-60:]}


if __name__ == "__main__":
    r = main()
    print(r["current_step"], r["best"], r["log_source"], len(r["sessions"]))
