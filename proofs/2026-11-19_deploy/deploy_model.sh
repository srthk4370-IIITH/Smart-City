# owner 2026-11-19: deploy a model to the QIDK board. usage: deploy_model.sh agent|reasoner GGUF
# .part+md5+mv via push_md5 with the app stopped; profile backup; agent: model=, agent_tools=1, agent_ctx=1280, HTPD_JSON_ABORT=1; reasoner: reasoner_model=.
# rollback to the backup profile if the app does not come up or the first forced analysis is invalid.
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
KIND=$1; SRC=$2; RG=/data/local/tmp/gpu; NAME=$(basename "$SRC"); TS=$(date +%m%d%H%M)
[ -s "$SRC" ] || { st "deploy $KIND: missing $SRC"; exit 1; }
st "deploy $KIND $NAME: stop app"; stop_app | tail -1
sh_ "cp $W/htpd_profile $W/htpd_profile.before_$KIND.$TS"
push_md5 "$SRC" $RG "$NAME" || { st "ABORT: push failed"; start_app; exit 1; }
if [ $KIND = agent ]; then
  sh_ "sed -i -e 's#^model=.*#model=$RG/$NAME#' -e 's#^agent_ctx=.*#agent_ctx=1280#' -e 's#HTPD_JSON_ABORT=2#HTPD_JSON_ABORT=1#' $W/htpd_profile; grep -q '^agent_tools=' $W/htpd_profile && sed -i 's#^agent_tools=.*#agent_tools=1#' $W/htpd_profile || echo agent_tools=1 >> $W/htpd_profile"
else
  sh_ "sed -i 's#^reasoner_model=.*#reasoner_model=$RG/$NAME#' $W/htpd_profile"
fi
sh_ "grep -E '^(model|reasoner_model|agent_ctx|agent_tools)=' $W/htpd_profile; grep -o 'HTPD_JSON_ABORT=[0-9]' $W/htpd_profile"
rollback(){ st "ROLLBACK $KIND: $1"; stop_app >/dev/null; sh_ "cp $W/htpd_profile.before_$KIND.$TS $W/htpd_profile"; start_app; exit 2; }
start_app || rollback "app not up"
sleep 120
sh_ "curl -s -m 150 -X POST -d '{\"node\":\"SR-AQ-KH03-03\",\"metric\":\"co2\",\"mode\":3}' http://127.0.0.1:8000/api/analyze" > /dev/null; sleep 90
id=$(sh_ "curl -s -m 20 'http://127.0.0.1:8000/api/incidents?limit=1'" | python3 -c "import json,sys;L=json.load(sys.stdin);L=L if isinstance(L,list) else L['incidents'];print(L[0]['id'])")
chk=$(sh_ "curl -s -m 20 http://127.0.0.1:8000/api/incidents/$id" | python3 -c "
import json,sys;d=json.load(sys.stdin);a=[x for x in d.get('agents') or [] if x.get('gen_tokens')]
f=d.get('final') or {};print('agents_valid=%d/%d final=%s %s'%(sum(1 for x in a if x.get('valid')),len(a),f.get('model'),'valid' if f.get('valid') else 'invalid'))")
st "deploy $KIND $NAME check $id: $chk"
case "$chk" in *"agents_valid=0/"*) rollback "agent output invalid";; esac
[ $KIND = reasoner ] && case "$chk" in *invalid*) rollback "reasoner report invalid";; esac
st "DEPLOYED $KIND $NAME"; echo DEPLOY_OK
