"""tele.py: every 20 s record /api/status gate + progress (watching strip data) -> tele.jsonl. usage: python tele.py minutes"""
import json, sys, time, urllib.request
end = time.time() + 60 * float(sys.argv[1])
out = open("tele.jsonl", "a", encoding="utf-8")
while time.time() < end:
    try:
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/status", timeout=10).read())
        out.write(json.dumps({"t": time.strftime("%H:%M:%S"), "gate": d.get("gate"), "progress": d.get("progress")}) + "\n"); out.flush()
    except Exception as e:
        out.write(json.dumps({"t": time.strftime("%H:%M:%S"), "err": str(e)}) + "\n")
    time.sleep(20)
