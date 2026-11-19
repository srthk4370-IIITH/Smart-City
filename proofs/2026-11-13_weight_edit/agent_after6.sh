# pull Kaggle seq 6, score new snapshots (Q4_0 dev), write best to post/BEST
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt
bash pull.sh --once; echo pull_rc=$?
bash select.sh; echo select_rc=$?
python3 -c "
import json,glob,os
P=os.path.expanduser('~/smartcity_runs/agt_v3/post'); s={}
for f in glob.glob(P+'/snap_*/dev_score.json'): s[f.split('/')[-2]]=json.load(open(f))['score']
b=max(s,key=s.get); print(sorted(s.items())); print('BEST',b,s[b]); open(P+'/BEST','w').write(b)"
echo AFTER6_DONE
