"""Phase driver (WSL python3). Runs gen_host.py for v2 and 3d alternately, cheapest-first so partial results are usable:
  1 alert   : (d,n) in (4,48), (8,48) + clean (0,48)
  2 chain   : d=18 at the n the app's WindowN policy picks from THIS model's d=8 answer (sim_chain_s24.windown),
              then d=36 at the n picked from the d=8 pattern and the d=18 status
  3 host400 : the frozen host400 set
  4 fill    : the remaining d=18/36 x n in {48,96,144} rows (full fixed-window tables, other policies)
  nice -n 10 python3 run_phases.py [--phases 1 2 3 4]"""
import argparse, json, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "Code/smart-city-edge-agent/training/v2/post"))
import common_v2 as C  # stdlib-only at import; cut_at_action used below
MODELS = {"v2": str(Path.home() / "smartcity_runs/agents_v2/post/gguf/ft_v2_q4_0.gguf"),
          "3d": str(Path.home() / "smartcity_runs/agents_v2_topup3d/post/gguf/ft_v2t3d_q4_0.gguf")}
FAM = {"flatline": "flat", "spike": "transient", "dip": "transient", "erratic": "noisy", "oscillation": "noisy",
       "stable": "stable", "gradual_increase": "trend", "gradual_decrease": "trend", "exponential_increase": "trend",
       "step_increase": "step", "step_decrease": "step", "throttling": "step"}
RANK = {"critical": 3, "warning": 2, "sensor_fault": 1, "normal": 0}


def windown(stage, early_p, status):          # verbatim logic of proofs/2026-10-21_v2_confirm/sim_chain_s24.py
    f = FAM.get(early_p, "invalid")
    if f == "stable" and RANK.get(status, 0) >= 2:
        f = "invalid"
    if status == "sensor_fault":
        return 144 if f in ("flat", "noisy") else 96
    if f == "flat": return 144
    if f in ("transient", "invalid"): return 96
    if f == "step" and stage == "3h": return 96
    if f == "noisy" and stage == "3h": return 144
    return 48


def ps(text):                                  # device text = cut at "action" and closed, then json.loads (as the sim)
    try:
        o = json.loads(C.cut_at_action(text)[0]); return o.get("pattern"), o.get("status")
    except Exception:
        return None, None


def outputs(tag):
    p = HERE / "raw" / tag / "outputs.jsonl"
    return {o["key"]: o for o in map(json.loads, open(p, encoding="utf-8"))} if p.exists() else {}


def run(tag, rows, name):
    f = HERE / "raw" / tag / f"todo_{name}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(f"=== {tag} phase {name}: {len(rows)} rows", flush=True)
    subprocess.run([sys.executable, str(HERE / "gen_host.py"), "--model", MODELS[tag], "--tag", tag,
                    "--prompts", str(f.relative_to(HERE))], check=True)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--phases", nargs="+", type=int, default=[1, 2, 3, 4])
    ap.add_argument("--tags", nargs="+", default=["v2", "3d"]); a = ap.parse_args()
    place = [json.loads(l) for l in open(HERE / "prompts_place.jsonl", encoding="utf-8")]
    P = {r["key"]: r for r in place}
    host = [json.loads(l) for l in open(HERE / "prompts_host400.jsonl", encoding="utf-8")]
    ev = sorted({r["id"] for r in place if r["d"] == 8})
    for ph in a.phases:
        if ph == 1:
            for t in a.tags:
                run(t, [r for r in place if (r["d"], r["n"]) in ((4, 48), (8, 48), (0, 48))], "1_alert")
        elif ph == 2:
            for t in a.tags:
                O = outputs(t)
                rows = []
                for i in ev:
                    e = ps(O[f"p|{i}|8|48"]["text"])
                    rows.append(P[f"p|{i}|18|{windown('1.5h', e[0], e[1])}"])
                run(t, rows, "2a_chain18")
            for t in a.tags:
                O = outputs(t)
                rows = []
                for i in ev:
                    e = ps(O[f"p|{i}|8|48"]["text"])
                    r1 = ps(O[f"p|{i}|18|{windown('1.5h', e[0], e[1])}"]["text"])
                    st = "sensor_fault" if r1[1] == "sensor_fault" else r1[1]
                    rows.append(P[f"p|{i}|36|{windown('3h', e[0], st)}"])
                run(t, rows, "2b_chain36")
        elif ph == 3:
            for t in a.tags:
                run(t, host, "3_host400")
        elif ph == 4:
            for t in a.tags:
                run(t, [r for r in place if r["d"] in (18, 36)], "4_fill")


if __name__ == "__main__":
    main()
