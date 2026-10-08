#!/usr/bin/env bash
# After the Kaggle calibration shards finish: download their raw min/max, merge into AIMET-format
# activation encodings, combine with the exact GPTQ weight encodings, and export the Genie bundle.
#   bash finish_calib.sh            then on Windows: deploy_tuned.ps1 -Bundle <printed path> -PerRole 10
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source ~/venvs/kg/bin/activate; export KAGGLE_API_TOKEN="$(cat ~/.kaggle/access_token)"
D=~/kg_results; mkdir -p $D
STATS=()
for i in 0 1 2 3; do
  mkdir -p $D/s$i
  kaggle kernels output srthk4370/qidk-calib-shard$i -p $D/s$i -o >/dev/null 2>&1 || true
  f=$(ls $D/s$i/out/model.encodings.stats.json $D/s$i/model.encodings.stats.json 2>/dev/null | head -1 || true)
  if [ -n "$f" ]; then STATS+=("$f"); echo "shard $i: $f"; else echo "shard $i: no stats"; fi
done
[ ${#STATS[@]} -gt 0 ] || { echo "no shard stats downloaded"; exit 1; }
deactivate; source ~/venvs/qaihm/bin/activate
PUB=~/.qaihm/qai-hub-models/models/llama_v3_2_3b_instruct/v7/w4a16/model.encodings
cd $HERE/kaggle
python merge_stats.py $PUB $D/calibrated.encodings "${STATS[@]}"
python $HERE/merge_calibrated.py $D/calibrated.encodings ~/qaihm_work/ftgptq16_ckpt ~/qaihm_work/ftcal_ckpt
CKPT=~/qaihm_work/ftcal_ckpt OUT=~/qaihm_work/ftcal_genie bash $HERE/export_gptq.sh
