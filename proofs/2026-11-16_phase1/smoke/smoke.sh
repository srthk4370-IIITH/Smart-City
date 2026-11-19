#!/bin/bash
# Phase 1 host smoke run: the backend (mock LLM, laptop CPU only) against the LIVE campus API for ~10 min.
# GET-only API reads; nothing is sent anywhere. Raw snapshots -> proofs/2026-11-16_phase1/smoke/raw, summary.json.
# usage (WSL): bash smoke.sh [minutes]
set -u
MIN=${1:-10}
export PATH=$HOME/go-sdk/go/bin:$PATH GOMAXPROCS=2
APP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app
OUT=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/smoke
D=/tmp/p1smoke; PORT=127.0.0.1:8097; U=http://$PORT
mkdir -p $OUT/raw; rm -rf $D; mkdir -p $D/state
cp -r $APP/device/data $APP/device/web $D/
echo v2 > $D/agent_version
cat > $D/htpd_profile <<'EOF'
input=campus
campus_poll_s=5
campus_backfill_h=12
site_group=1
agents=agt_v3
health_stale_min=30
EOF
(cd $APP/backend && go build -o /tmp/p1smoke-host .) || { echo "build failed"; exit 1; }
/tmp/p1smoke-host --dir $D --mock --addr $PORT > $OUT/raw/backend.log 2>&1 &
PID=$!; echo $PID > $OUT/raw/backend.pid
t0=$(date +%s)
snap(){ curl -s -m 20 $U$1 > $OUT/raw/$2 2>/dev/null; }
for i in $(seq 0 $MIN); do
  sleep 60
  kill -0 $PID 2>/dev/null || { echo "backend died" >> $OUT/raw/backend.log; break; }
  snap /api/campus/status campus_$i.json
  snap /api/health/data health_$i.json
  snap "/api/incidents" incidents_$i.json
done
snap /api/site site.json
snap /api/site/status site_status.json
snap "/api/incidents/export?format=csv" incidents.csv
snap /api/cards cards.json
snap /api/live live.json
snap /api/daily daily.json
curl -s -m 20 -X POST "$U/api/daily/run?ai=0" > $OUT/raw/daily_run.json
# site tool through the chat dispatcher path (direct)
kill $PID 2>/dev/null; sleep 2
python3 - "$OUT" "$t0" <<'PY'
import json, sys, glob, os, csv
out, t0 = sys.argv[1], int(sys.argv[2])
R = out + "/raw/"
def J(p):
    try: return json.load(open(R + p))
    except Exception as e: return {"_err": str(e)}
c = sorted(glob.glob(R + "campus_*.json"), key=lambda p: int(p.split("_")[-1].split(".")[0]))
hs = sorted(glob.glob(R + "health_*.json"), key=lambda p: int(p.split("_")[-1].split(".")[0]))
last_c = J(os.path.basename(c[-1])) if c else {}
last_h = J(os.path.basename(hs[-1])) if hs else {}
site = J("site.json"); ss = J("site_status.json")
kinds = {}
for n in site.get("nodes", []): kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
incs = J(os.path.basename(sorted(glob.glob(R + "incidents_*.json"))[-1])) if glob.glob(R + "incidents_*.json") else []
rows = list(csv.reader(open(R + "incidents.csv"))) if os.path.exists(R + "incidents.csv") else []
log = open(R + "backend.log").read()
summ = {"minutes": len(c), "campus_last": last_c.get("campus", last_c), "offline_last": last_c.get("offline"),
        "health_counts": last_h.get("counts"), "sensors": [(s["node"], s["metric"], s["state"], s.get("age_s")) for s in last_h.get("sensors", [])],
        "site": {"version": site.get("version"), "source": site.get("source"), "nodes": kinds, "links": len(site.get("links", []))},
        "suspects": ss.get("suspects"), "open": ss.get("open"),
        "incidents": len(incs) if isinstance(incs, list) else incs, "export_rows": max(0, len(rows) - 1),
        "panics": log.count("panic"), "log_campus_lines": [l for l in log.splitlines() if "campus" in l][:12]}
json.dump(summ, open(out + "/summary.json", "w"), indent=1)
print(json.dumps({k: summ[k] for k in ("minutes", "offline_last", "health_counts", "site", "incidents", "export_rows", "panics")}, indent=1))
PY
echo "=== smoke done"
