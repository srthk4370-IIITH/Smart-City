#!/bin/bash
# v3 data build (detached via proofs/detach.sh): sites index -> agt_v3 generation -> verify/dedup/tokens -> gate sets.
# CPU only, nice 15, streaming writes. Logs: ~/detached/v3data.log ; status: proofs/2026-11-13_v3_data/STATUS
set -e
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data
PY=$HOME/venvs/rsn/bin/python
TOK=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/models/genie_bundle/llama_v3_2_3b_instruct-genie-w4a16-qualcomm_snapdragon_8gen3/tokenizer.json
SH=$HOME/smartcity_runs/v3_data/shards
st() { echo "$(date -Iseconds) $*" | tee -a $D/STATUS; }
mkdir -p $SH
st "start"
cd $D/core
nice -n 15 $PY - <<'EOF'
import json, sys
sys.path.insert(0, ".")
import sitegraph as ST
from collections import Counter
out = open("sites_index.jsonl", "w")
tot = Counter()
for split, n in (("train", 6000), ("dev", 300), ("test", 400)):
    for s in range(n):
        x = ST.gen_site(s, split)
        k = Counter(nd["kind"] for nd in x["nodes"])
        out.write(json.dumps({"split": split, "seed": s, "site_id": x["site_id"], "naming": x["naming"], "motifs": x["motifs"],
                              "nodes": len(x["nodes"]), "links": len(x["links"]), "kinds": dict(k),
                              "link_types": dict(Counter(l["type"] for l in x["links"]))}) + "\n")
        if s < 4:
            json.dump(x, open(f"sample_site_{split}_{s}.json", "w"))
        tot[split] += 1
json.dump(ST.campus_site(), open("campus_site.json", "w"), indent=1)
print(dict(tot))
EOF
st "sites index done"
cd $D/agt_v3
nice -n 15 $PY gen_agt.py --out $HOME/smartcity_runs/v3_data --procs 6 2>&1 | tail -3
st "generation done"
nice -n 15 $PY post.py $D $SH $TOK
st "verify/dedup/tokens done"
nice -n 15 $PY build_gate.py $D
st "gate sets done"
rm -f $D/agt_v3/_raw_*.jsonl
st "ALL DONE"
