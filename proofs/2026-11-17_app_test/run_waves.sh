# owner 2026-11-17: app test through the real app. schedule.json (Haiku-designed) -> per wave: clear, inject, wait WAVE_MIN, dump incidents opened in the wave (full detail).
source <(sed -n "11,36p" /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
T=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-17_app_test; WAVE_MIN=${WAVE_MIN:-60}
n=$(python3 -c "import json;print(len(json.load(open('$T/schedule.json'))))")
for ((k=0;k<n;k++)); do
  ids=$(python3 -c "import json;print(' '.join(json.load(open('$T/schedule.json'))[$k]['scenarios']))")
  t0=$(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/prod/status" | python3 -c "import json,sys;print(json.load(sys.stdin)['clock']['corrected'])")
  echo "$(date +%T) wave $((k+1)) [$ids] t0=$t0"
  sh_ "curl -s -m 20 -X POST -d '{\"scenario\":\"clear\"}' http://127.0.0.1:8000/api/inject" > /dev/null
  for s in $ids; do echo "  inject $s: $(sh_ "curl -s -m 20 -X POST -d '{\"scenario\":\"$s\"}' http://127.0.0.1:8000/api/inject" | head -c 160)"; done
  sleep $((WAVE_MIN*60))
  sh_ "curl -s -m 30 'http://127.0.0.1:8000/api/incidents?limit=100'" > $T/list_w$((k+1)).json
  for id in $(python3 -c "
import json,datetime as D
L=json.load(open('$T/list_w$((k+1)).json'));L=L if isinstance(L,list) else L['incidents']
t0=D.datetime.fromisoformat('$t0'.replace('Z','+00:00')).timestamp()
print(' '.join(i['id'] for i in L if i['created_unix']>=t0-60))"); do sh_ "curl -s -m 30 http://127.0.0.1:8000/api/incidents/$id"; echo; done > $T/wave_$((k+1)).jsonl
  echo "  wave $((k+1)) incidents: $(grep -c . $T/wave_$((k+1)).jsonl)"
done
sh_ "curl -s -m 20 -X POST -d '{\"scenario\":\"clear\"}' http://127.0.0.1:8000/api/inject" > /dev/null
echo WAVES_DONE
