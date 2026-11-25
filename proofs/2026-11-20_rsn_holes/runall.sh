cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/rsn_ft/post
for n in test_real_agent test_fog dev_p2 test_unseen_metric; do
 FT_NO_COOL=1 python3 run_ft.py --limit 10 --think 1 --tag p2 --port 18199 --resdir /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_holes/res v4 --name $n --file /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_holes/sub/$n.jsonl --tools /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn/data/final_v2/tools_v4.json >> /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_holes/res/run.log 2>&1
done
echo ALLDONE >> /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_holes/res/run.log
