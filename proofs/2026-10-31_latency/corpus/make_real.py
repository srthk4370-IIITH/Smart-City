#!/usr/bin/env python3
"""Real-app reports for the v9 draft corpus + held-out lab requests.

From the board's incidents.jsonl (pulled 2026-10-31): keeps incidents whose final report came from the reasoner
(model 'qwen3.5-4b (htpd)'), writes
  real_reports.jsonl        all of them (id, final.raw) -> build_corpus.py input
  test_ids.txt              the TEST most recent ones with distinct titles (held out from corpus_real_excl)
  rreq_real/q10N.json       lab requests for the test incidents: q10.json template (prefix, schema, split, max_new)
                            with the incident's real prompt
usage: python3 make_real.py incidents.jsonl outdir [TEST=6]
"""
import json, os, sys

src, out = sys.argv[1], sys.argv[2]
TEST = int(sys.argv[3]) if len(sys.argv) > 3 else 6
T = json.load(open('/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/bench/rreq_split/q10.json'))
os.makedirs(out + '/rreq_real', exist_ok=True)
rows = []
for l in open(src, encoding='utf-8'):
    l = l.strip()
    if not l:
        continue
    r = json.loads(l)
    f = r.get('final') or {}
    if f.get('model') != 'qwen3.5-4b (htpd)' or not (f.get('raw') or '').startswith('{"title"'):
        continue
    rows.append(r)
with open(out + '/real_reports.jsonl', 'w') as w:
    for r in rows:
        w.write(json.dumps({'id': r['id'], 'final': {'raw': r['final']['raw']}}) + '\n')
last = {}
for r in rows:
    last[r["id"]] = r
rows = sorted(last.values(), key=lambda r: r["id"])
test, seen = [], set()
for r in reversed(rows):
    p = r['final'].get('prompt') or ''
    if not p.startswith(T['prefix']) or r['title'] in seen:
        continue
    seen.add(r['title'])
    test.append(r)
    if len(test) == TEST:
        break
with open(out + '/test_ids.txt', 'w') as w:
    for k, r in enumerate(test):
        q = dict(T)
        q['prompt'] = r['final']['prompt']
        q['id'] = 'app:' + r['id']
        open(f"{out}/rreq_real/q{100 + k}.json", 'w').write(json.dumps(q) + '\n')  # htpd reads one request per line
        w.write(f"q{100 + k} {r['id']} {r['severity']} {(r['final'].get('parsed') or {}).get('label')} | {r['title']}\n")
print(len(rows), 'reasoner reports;', len(test), 'test requests')
print(open(out + '/test_ids.txt').read())
