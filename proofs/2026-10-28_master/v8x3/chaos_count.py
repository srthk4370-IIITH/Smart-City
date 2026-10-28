import glob, json, os, sys
t0 = float(sys.argv[1]); n = d = v = 0
for f in glob.glob("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/raw/chaos_*_incident.json"):
    if os.path.getmtime(f) < t0: continue
    x = json.load(open(f)); i = x.get("incident"); n += 1
    if isinstance(i, dict): d += i.get("state") == "done"; v += bool((i.get("final") or {}).get("valid"))
print(n, d, v)
