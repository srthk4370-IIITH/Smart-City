import sys, json, collections
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/tools")
import tools_r3_impl as TR
ex = TR.ToolsR3(fog="offline")
d = ex.D
print(type(d), [k for k in vars(d)][:30])
x = d.incs[-1]; print(json.dumps({k: (v if not isinstance(v, (list, dict)) or len(json.dumps(v)) < 300 else str(v)[:300]) for k, v in x.items()}, default=str)[:2500])
c = collections.Counter(i["label"] for i in d.incs if i["full"]); print(c)
r = ex.run("co_occurring_incidents", {"id": d.incs[-5]["id"], "window_min": 120}) if hasattr(ex, "run") else None
print(str(r)[:1500])
