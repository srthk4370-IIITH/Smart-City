"""Board chat check with the engine label (WSL, stdlib): like 2026-10-28_master/chatcheck.py, plus the message `model`
field (split APK: "qwen3.5-2b rsn_v3 (gpu)" or the htpd fallback label). One session per run, questions in order."""
import json, shlex, subprocess, sys, time
A = "/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe"
sess = ""
for q in sys.argv[1:]:
    body = json.dumps({"session": sess, "message": q})
    cmd = "curl -s -m 200 -X POST -H 'Content-Type: application/json' -d %s http://127.0.0.1:8000/api/chat" % shlex.quote(body)
    t0 = time.time()
    out = subprocess.run([A, "shell", cmd], capture_output=True, text=True, timeout=260).stdout
    try:
        d = json.loads(out); sess = d["id"]; m = d["messages"][-1]
        print("%.0f s | model %s | tools %s | busy %s | error %s | %s -> %s" % (time.time() - t0, m.get("model", "-"),
              [t["name"] for t in m.get("tools") or []], m.get("busy", False), m.get("error", False), q, m["text"][:200]))
    except Exception as e:
        print("FAIL %s: %s %r" % (q, e, out[:200]))
