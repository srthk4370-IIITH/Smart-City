source ~/venvs/qaihm/bin/activate
P=$(python -c "import qai_hub_models,os;print(os.path.dirname(qai_hub_models.__file__))")
echo "=== supported precisions for llama_v3_2_3b_instruct:"
grep -rn "SUPPORTED_PRECISIONS\|DEFAULT_W4\b\|Precision.w4\b" $P/models/llama_v3_2_3b_instruct/*.py $P/models/templates/llama3/*.py 2>/dev/null | head -8
echo "=== what Precision.w4 means (activation dtype):"
grep -rn -A12 "^class Precision\|w4 = \|w4a16 = " $P/utils/base_config.py $P/utils/quantization.py 2>/dev/null | grep -i -E "w4|activation|float16|class Precision" | head -14
echo "=== is the published w4 encodings asset referenced?"
grep -rn "w4/model.encodings\|w4a16/model.encodings" $P/models/templates/llama3/model.py $P/models/llama_v3_2_3b_instruct/model.py 2>/dev/null | head -5
