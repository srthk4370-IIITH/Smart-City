# INC-0011: HTPD_JSON_ABORT=2 nesting rule truncates agt_v3 answers at "src": [ -> set 1 (length rule only), restart, forced analyze
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
stop_app | tail -1
sh_ "cp $W/htpd_profile $W/htpd_profile.abort2 && sed -i 's/HTPD_JSON_ABORT=2/HTPD_JSON_ABORT=1/' $W/htpd_profile && grep -o 'HTPD_JSON_ABORT=[0-9]' $W/htpd_profile"
start_app && st "abort1: app up"; sleep 90
sh_ "curl -s -m 120 -X POST -d '{\"node\":\"SR-AQ-KH03-03\",\"metric\":\"co2\",\"mode\":3}' http://127.0.0.1:8000/api/analyze" ; echo; sleep 60
id=$(sh_ "curl -s -m 20 'http://127.0.0.1:8000/api/incidents?limit=1'" | python3 -c "import json,sys;L=json.load(sys.stdin);L=L if isinstance(L,list) else L['incidents'];print(L[0]['id'])")
sh_ "curl -s -m 20 http://127.0.0.1:8000/api/incidents/$id" | python3 -c "
import json,sys;d=json.load(sys.stdin);print(d['id'])
for a in d.get('agents') or []: print(a.get('ref'),a.get('valid'),a.get('gen_tokens'),(a.get('raw') or '')[-60:])
print([t['msg'][:120] for t in d['timeline'] if 'agent done' in t['msg'] or 'REJECT' in t['msg']])"
echo ABORT1_DONE
