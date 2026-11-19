O=~/smartcity_runs/rsn3_4b_r3; mkdir -p $O
for f in ~/smartcity_runs/fit4b_r3/*_seg_tok.pt; do ln -sfn "$f" "$O/$(basename $f)"; done
[ -s $O/maxlen.json ] || echo '{"max_len": 7424, "probe": "FIT.md r3 update"}' > $O/maxlen.json
ls -la $O
