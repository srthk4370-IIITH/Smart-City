import json,sys
for l in open(sys.argv[1]):
    r=json.loads(l)
    if len(sys.argv)>2 and r['route']!=sys.argv[2]: continue
    print(f"{r['i']:>2} [{r['route']}] {r['q']}\n   NEW: {r['text'][:400]}\n   OLD: {(r.get('board_text') or '')[:250]}")
