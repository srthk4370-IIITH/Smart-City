"""One line per candidate: pattern/status (v2->cand, W/L) for ALL + stages (+ rw5 cases if present), and the count of
slices (n>=25) down > 1 pt.   python brief_3f.py SET_DIR REF CAND..."""
import json, subprocess, sys
from pathlib import Path
E, ref, cands = Path(sys.argv[1]).expanduser(), sys.argv[2], sys.argv[3:]
H = Path(__file__).resolve().parent.parent / "topup3e"
subprocess.run([sys.executable, str(H / "host_eval3e.py"), "table", "--out", str(E), "--ref", ref, "--cand", *cands],
               cwd=H, capture_output=True)
T = json.loads((E / "tables.json").read_text())
for c, row in T.items():
    f = lambda s, k: (lambda x: f"{100*x['ref']/x['n']:.1f}>{100*x['cand']/x['n']:.1f}({x['wins']}/{x['losses']})")(row[s][k]) if s in row and k in row[s] else "-"
    keys = [s for s in ("ALL", "stage_early", "stage_1.5h", "stage_3h", "compound", "calm_or_routine") if s in row]
    keys += sorted(s for s in row if s.startswith("rw5_") and s != "rw5_chatter_next")
    bad = [f"{s}.{k[0]}" for s, v in row.items() for k in ("pattern", "status") if k in v and v[k]["n"] >= 25 and (v[k]["cand"] - v[k]["ref"]) / v[k]["n"] < -0.01]
    print(f"{c}: " + " | ".join(f"{s.replace('stage_','').replace('rw5_','')} p{f(s,'pattern')} s{f(s,'status')}" for s in keys) + f" || down>1pt: {bad}")
