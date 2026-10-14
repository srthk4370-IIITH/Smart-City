#!/system/bin/sh
# On-device Genie benchmark driven by Genie's OWN profiler.
#
#   sh /data/local/tmp/bench_device.sh <config.json> <runs> <prompt_file> [bundle_dir]
#
# Reports init / prefill / decode per run. Do NOT use wall-clock here: `date +%s%N`
# arithmetic in the Android shell was measured giving ~1.7s for a run the profiler and
# the `time` builtin both put at ~5.97s. The profiler is the source of truth.
#
# Guard: refuses to run hot (numbers drift down through a session).
B=${4:-/data/local/tmp/genie_bundle_ft}
R=/data/local/tmp/genie_bundle
CFG=$1
N=${2:-3}
P=${3:-/data/local/tmp/app_prompt.txt}

t=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1)
t=$((t / 1000))
echo "temp=${t}C config=$CFG runs=$N prompt=$P"
[ "$t" -gt 80 ] && { echo "TOO HOT - aborting"; exit 1; }

cd "$B" || exit 1
i=0
while [ $i -lt "$N" ]; do
  i=$((i + 1))
  PF=/data/local/tmp/_bench_prof_$i.json
  rm -f "$PF"
  LD_LIBRARY_PATH=$R/qairt_2_50_libs \
  ADSP_LIBRARY_PATH="$R/dsp_2_50;$R/dsp;/vendor/dsp/cdsp;/vendor/lib/rfsa/adsp;/system/lib/rfsa/adsp" \
  $R/genie-t2t-run-2.50 -c "$CFG" --prompt_file "$P" --profile "$PF" >/dev/null 2>&1
  # pull the numbers out of the profile JSON (flattened, no jq on device)
  flat=$(tr -d ' \n' < "$PF")
  init=$(echo "$flat" | sed -n 's/.*"init-time":{"value":\([0-9]*\).*/\1/p')
  ttft=$(echo "$flat" | sed -n 's/.*"time-to-first-token":{"value":\([0-9]*\).*/\1/p')
  ptok=$(echo "$flat" | sed -n 's/.*"num-prompt-tokens":{"value":\([0-9]*\).*/\1/p')
  gtok=$(echo "$flat" | sed -n 's/.*"num-generated-tokens":{"value":\([0-9]*\).*/\1/p')
  gtime=$(echo "$flat" | sed -n 's/.*"token-generation-time":{"value":\([0-9]*\).*/\1/p')
  rate=$(echo "$flat" | sed -n 's/.*"token-generation-rate":{"value":\([0-9.]*\).*/\1/p')
  echo "run$i init=$((init / 1000))ms ttft=$((ttft / 1000))ms prompt_tok=$ptok gen_tok=$gtok decode=$((gtime / 1000))ms rate=$rate tok/s"
done
