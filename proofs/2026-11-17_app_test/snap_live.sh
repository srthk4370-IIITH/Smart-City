source <(sed -n "11,36p" /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
T=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-17_app_test
for i in $(seq 1 15); do sh_ "curl -s -m 20 http://127.0.0.1:8000/api/live" > /tmp/live_snap.json
python3 - >> $T/live_w3.log <<'P'
import json,time
d=json.load(open("/tmp/live_snap.json"))
for r in (d.get("roles") or {}).values():
  for s in (r if isinstance(r,list) else r.get("sensors",[])):
    if s.get("injected") or s.get("status") not in ("normal",None): print(time.strftime("%H:%M"),s["node"],s["metric"],s.get("last"),s.get("status"),s.get("pattern"),"abn",s.get("abnormal_for"),"rep",s.get("reported"),"inj",s.get("injected"))
P
sleep 600; done
