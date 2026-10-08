P=com.iiith.smartcityedge
run-as $P mkdir -p files/genie_bundle files/genie_bundle_ft
cp1() { src=$1; dst=$2; if [ "$(run-as $P stat -c %s $dst 2>/dev/null)" = "$(stat -c %s $src)" ]; then echo "skip $dst"; return; fi; cat $src | run-as $P sh -c "cat > $dst"; echo "ok $dst $(run-as $P stat -c %s $dst)"; }
for f in llama_v3_2_3b_instruct_part_1_of_3.bin llama_v3_2_3b_instruct_part_2_of_3.bin llama_v3_2_3b_instruct_part_3_of_3.bin smartcity_agent.json htp_backend_ext_config.json tokenizer.json; do
  cp1 /data/local/tmp/genie_bundle/$f files/genie_bundle/$f
  cp1 /data/local/tmp/genie_bundle_ft/$f files/genie_bundle_ft/$f
done
[ -f /data/local/tmp/genie_bundle_ft/VALIDATED ] && cp1 /data/local/tmp/genie_bundle_ft/VALIDATED files/genie_bundle_ft/VALIDATED
run-as $P ls -la files/genie_bundle files/genie_bundle_ft
