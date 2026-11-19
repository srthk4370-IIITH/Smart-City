"""Chat sweep through the app (WSL, stdlib). usage: python3 sweep.py questions.json out.jsonl
One question at a time; waits for board temp <= 60 C and an idle chat before each. Same group letter = same chat session."""
import json, shlex, subprocess, sys, time
A = "/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe"
def sh(c, t=60):
    return subprocess.run([A, "shell", c], capture_output=True, text=True, timeout=t).stdout
def temp_c():
    t = sh("cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1").strip()
    return int(t) // 1000 if t.isdigit() else -1
def sim():
    try: return json.loads(sh("curl -s -m 10 http://127.0.0.1:8000/api/status")).get("sim_time")
    except Exception: return None
qs = json.load(open(sys.argv[1])); out = open(sys.argv[2], "a"); sess = {}
START = int(sys.argv[3]) if len(sys.argv) > 3 else 1  # resume: skip questions before START (1-based)
for i, (g, q) in enumerate(qs):
    if i + 1 < START: continue
    w0 = time.time()
    while True:
        tc = temp_c()
        if 0 < tc <= 60: break
        if time.time() - w0 > 900: break
        time.sleep(15)
    body = json.dumps({"session": sess.get(g, ""), "message": q})
    s0 = sim(); t0 = time.time()
    raw = sh("curl -s -m 320 -X POST -H 'Content-Type: application/json' -d %s http://127.0.0.1:8000/api/chat" % shlex.quote(body), 360)
    wall = time.time() - t0
    rec = {"i": i + 1, "group": g, "q": q, "temp_c": tc, "sim_time": s0, "wall_s": round(wall, 1)}
    try:
        d = json.loads(raw); sess[g] = d["id"]; m = d["messages"][-1]
        rec.update(session=d["id"], text=m["text"], ms=m.get("ms"), queued_ms=m.get("queued_ms", 0), busy=m.get("busy", False),
                   error=m.get("error", False), model=m.get("model"), tools=[{"name": t["name"], "args": t.get("args"), "result": (t.get("result") or "")[:1500]} for t in m.get("tools") or []])
    except Exception as e:
        rec.update(fail=str(e), raw=raw[:300])
    out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
    print(rec["i"], rec.get("ms"), [t["name"] for t in rec.get("tools", [])], q, "->", (rec.get("text") or rec.get("raw", ""))[:160], flush=True)
    time.sleep(3)
print("SWEEP DONE", flush=True)
