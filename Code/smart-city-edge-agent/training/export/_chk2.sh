source ~/venvs/qaihm/bin/activate
P=$(python -c "import qai_hub_models,os;print(os.path.dirname(qai_hub_models.__file__))")
echo "=== llama3/model.py around the Precision.w4 branch:"
sed -n '490,520p' $P/models/templates/llama3/model.py
echo "=== how the default checkpoint picks the encodings asset:"
grep -rn -B3 -A6 "model.encodings" $P/models/templates/llama3/model.py | head -40
