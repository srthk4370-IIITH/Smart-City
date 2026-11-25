#!/usr/bin/env bash
# kaggle_upload_base.sh: one-time private upload of the edited base r3_edit_C1 (8.8 GB) as srthk4370/rsn-big-base (owner exception: private, deleted after the run).
# Symlink staging (no copy), token never read here (the kaggle CLI reads it itself). Safe to re-run: skips when the dataset is already ready.
K=~/venvs/kaggle/bin/kaggle; B=/mnt/c/Users/hp/qidk_models/r3_edit_C1; S=~/smartcity_runs/rsn_big_base_upload
L=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/logs/upload_base.log
U=$($K config view 2>/dev/null | sed -n 's/^- username: *//p' | head -1)
if $K datasets status $U/rsn-big-base 2>&1 | grep -qi ready; then echo "$(date -Is) already ready" >> $L; exit 0; fi
rm -rf $S; mkdir -p $S
for f in $B/*.safetensors $B/*.json $B/*.jinja $B/*.txt; do ln -s $f $S/; done
(cd $B && sha256sum *.safetensors) > $S/SHA256SUMS_base
printf '{"title": "rsn-big-base", "id": "%s/rsn-big-base", "licenses": [{"name": "other"}]}\n' "$U" > $S/dataset-metadata.json
echo "$(date -Is) uploading ($(du -shL $S | cut -f1))" >> $L
$K datasets create -p $S -t -r zip -q >> $L 2>&1; echo "$(date -Is) create rc $?" >> $L
for i in $(seq 1 120); do $K datasets status $U/rsn-big-base 2>&1 | grep -qi ready && { echo "$(date -Is) ready" >> $L; exit 0; }; sleep 30; done
echo "$(date -Is) not ready after wait" >> $L; exit 1
