cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/device
rm -rf /tmp/rest && mkdir -p /tmp/rest && cp -r data web /tmp/rest/
./edge-agent-host --dir /tmp/rest --mock --addr 127.0.0.1:8095 --poll-ms 100 > /tmp/rest/log.txt 2>&1 &
sleep 2
python3 - <<'PY'
import json, time, urllib.request, collections
B = "http://127.0.0.1:8095"
get = lambda p: json.loads(urllib.request.urlopen(B + p, timeout=20).read())
seen = collections.Counter()
for t in range(200):           # ~100 s at 100 ms polls = ~1000 readings per sensor
    time.sleep(1)
    for r in get("/api/live")["roles"].values():
        for s in r["sensors"]:
            if s["status"] not in ("normal",): seen[(s["metric"], s["status"])] += 1
            if s["pattern"] not in ("stable", "vacant", "context", "-"): seen[(s["metric"], s["pattern"])] += 1
print("2000 rest readings -> incidents:", len(get("/api/incidents")))
print("non-normal observations (sensor, status/pattern: seconds seen):", dict(seen) or "none")
PY
kill %1
