"""E2/E3 paired gate: CAND + rules vs REF(mixA50) + live rules, per set; one line per set.
  python e2.py --cand TAG [--ref mixA50] [--sets dev rw5dev] [--cand-rules ALL,leak_keep,hvac_teacher] [--out f.json]
CAND may equal REF with different rules (rule gate). Sets: dev rw5dev test rw5test (topup3f eval dirs) or a DIR path."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dp_lib as D  # noqa: E402
import p1_rules  # noqa: E402  (registers the P1 rules into trackb_lib.RULES)

ap = argparse.ArgumentParser()
ap.add_argument("--cand", required=True); ap.add_argument("--ref", default="mixA50")
ap.add_argument("--sets", nargs="+", default=["dev", "rw5dev"])
ap.add_argument("--cand-rules", default="ALL"); ap.add_argument("--ref-rules", default="ALL")
ap.add_argument("--out"); ap.add_argument("--regold", action="store_true", help="P1a label-definition change on gold")
a = ap.parse_args()
rl = D.expand
res, allok = {}, True
for ds in a.sets:
    d = Path(ds) if "/" in ds else D.L.SETS[ds]
    rows = D.load_rows(d / "eval3e.jsonl")
    ng = len(p1_rules.regold(rows)) if a.regold else 0
    ref = {i: v[0] for i, v in D.ruled(rows, D.load_samples(d / "eval" / a.ref / "samples.jsonl"), rl(a.ref_rules)).items()}
    cand = {i: v[0] for i, v in D.ruled(rows, D.load_samples(d / "eval" / a.cand / "samples.jsonl"), rl(a.cand_rules)).items()}
    t, fd = D.paired(rows, ref, cand)
    ok, line = D.gate_line(Path(ds).name, t, fd)
    allok &= ok
    print(line + (f" regold{ng}" if a.regold else ""), flush=True)
    res[Path(ds).name] = {"table": t, "flat": fd, "pass": ok}
print(f"GATE {'PASS' if allok else 'FAIL'} cand={a.cand}[{a.cand_rules}] ref={a.ref}[{a.ref_rules}]")
if a.out:
    json.dump(res, open(a.out, "w"), indent=1)
