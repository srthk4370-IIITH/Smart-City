"""api_sweep.py: read-only sweep of every backend GET route + edge cases, timed. usage: python api_sweep.py <tag>
Appends one JSON row per call to api_sweep.jsonl and prints anomalies (non-2xx, > 1 s, invalid JSON, empty)."""
import json, sys, time, urllib.request, urllib.error

B = "http://127.0.0.1:8000"
TAG = sys.argv[1] if len(sys.argv) > 1 else "x"
GETS = ["/api/health", "/api/health/data", "/api/status", "/api/campus/status", "/api/sensors", "/api/topology", "/api/site",
        "/api/site/status", "/api/site/versions", "/api/site/validate", "/api/cards", "/api/rules", "/api/incidents", "/api/incidents?all=1",
        "/api/incidents/export", "/api/history?days=1", "/api/history?days=7", "/api/history?days=90", "/api/daily", "/api/streams",
        "/api/maintenance", "/api/mode", "/api/scenarios", "/api/prod/status", "/api/prod/time", "/api/chat/status",
        "/api/chat/sessions", "/api/live", "/v1/status",
        "/api/series?node=SR-AQ-KH03-03&metric=temp", "/api/series?node=WM-WD-KH98-00&metric=ph&hours=24",
        # edge cases
        "/api/incidents/INC-9999", "/api/incidents/../../etc/passwd", "/api/series", "/api/series?node=NOPE&metric=x",
        "/api/history?days=-5", "/api/history?days=100000", "/api/history?days=abc", "/api/series?node=SR-AQ-KH03-03&metric=temp&hours=99999"]


def call(p, timeout=30):
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(B + p), timeout=timeout) as r:
            body = r.read() if p != "/api/live" else r.read(2048)
            return r.status, body, time.time() - t
    except urllib.error.HTTPError as e:
        return e.code, e.read(), time.time() - t
    except Exception as e:  # timeouts, resets
        return -1, str(e).encode(), time.time() - t


out = open("api_sweep.jsonl", "a", encoding="utf-8")
for p in GETS:
    c, b, dt = call(p, 8 if p == "/api/live" else 30)
    ok_json = True
    try:
        json.loads(b)
    except Exception:
        ok_json = False
    row = dict(tag=TAG, at=time.strftime("%H:%M:%S"), path=p, code=c, ms=round(dt * 1000), bytes=len(b), json=ok_json,
               head=b[:160].decode("utf-8", "replace"))
    out.write(json.dumps(row) + "\n")
    flag = c < 200 or c >= 300 or dt > 1 or (not ok_json and p != "/api/live") or len(b) < 3
    print(("!! " if flag else "   ") + "%4d %6d ms %8d B json=%s %s %s" % (c, dt * 1000, len(b), ok_json, p, row["head"][:90] if flag else ""))
