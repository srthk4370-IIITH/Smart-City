"""Run one extra incident suite (e.g. RWH-2) through the round-1 runner (eval/run_v3.py run_items: same prompts, compact tools,
stored-result tool executor) against a served model -> eval/results/<tag>/<suite>.jsonl (resumable).
  python3 run_suite.py --tag rsn_v3_t1 --port 18097 --suite rwh2 --file .../heldout/incidents_rwh2.jsonl"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
R1E = os.path.abspath(os.path.join(HERE, "..", "..", "..", "2026-10-25_reasoner_final", "eval"))
sys.path.insert(0, R1E)
import run_v3 as RV  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--tag", required=True)
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--suite", required=True)
ap.add_argument("--file", required=True)
ap.add_argument("--limit", type=int, default=0)
a = ap.parse_args()
od = os.path.join(R1E, "results", a.tag)
os.makedirs(od, exist_ok=True)
n = RV.run_items(RV.RB.Client(a.port, 1200), RV.load(a.file), os.path.join(od, a.suite + ".jsonl"), a.limit)
print("%s %s: %d items" % (a.tag, a.suite, n))
