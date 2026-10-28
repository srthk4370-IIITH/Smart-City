"""manifest.json for this proof folder: inputs (with hashes), engine, settings, file hashes, row counts.
  py -3 make_manifest.py"""
import hashlib
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
Q = HERE.parents[1]


def sha16(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def nlines(p):
    return sum(1 for _ in open(p, encoding="utf-8")) if Path(p).exists() else 0


man = {
    "created": datetime.now().isoformat(timespec="seconds"),
    "purpose": "Accuracy of two Q4_0 GGUFs (v2 deployed vs 3d top-up step 50) without the QIDK board: laptop CPU "
               "llama.cpp greedy, scored with the device-eval code; plus v2 host vs v2 device agreement.",
    "models": {
        "v2": {"path": "WSL ~/smartcity_runs/agents_v2/post/gguf/ft_v2_q4_0.gguf", "md5": "250f109cf253c7fe582f3676e4f5d5a3",
               "sha256_gguf_manifest": "9d10c173b51207e2d230689dcb34fa9b104d697022cc8fe8efa6cbad427b22cd"},
        "3d": {"path": "WSL ~/smartcity_runs/agents_v2_topup3d/post/gguf/ft_v2t3d_q4_0.gguf", "md5": "e9088e111cf85a036a3119e864ab6305"}},
    "engine": {"llama.cpp": "620d2225cc436ab0b001e3200e590e3b286ef9ab (~/gpu_work/llama.cpp/build-host, CPU, GGML_NATIVE, AVX2/AVX-VNNI)",
               "why_cpu": "no CUDA toolkit (nvcc) in WSL or Windows; downloading one was out of scope (offline task)",
               "server": "llama-server -t 4 -tb 4 -np 4 -c 8192 -ngl 0 -fa auto --temp 0, run under nice -n 10",
               "request": "prompt minus leading <|begin_of_text|> (server adds BOS; /tokenize check equal to htpd tokens) + "
                          "PREFILL '{\"pattern\": \"', temperature 0, top_k 1, n_predict 160, stop ['\"action\"', '<|eot_id|>'], "
                          "cache_prompt; identical to training/v2/post/host_eval_v2.py gen_gguf",
               "cpu": "13th Gen Intel i5-13420H (WSL 8 vCPU, 12 GB), 4 threads"},
    "inputs": {
        "host400": {"eval_set": "proofs/2026-10-20_v2_post/eval_set.json", "sha16": sha16(Q / "proofs/2026-10-20_v2_post/eval_set.json"),
                    "rows": "data/sft_v2/test.jsonl"},
        "placement_s24": {"prompts": "proofs/2026-10-21_v2_confirm/placement_s24/prompts.jsonl",
                          "sha16": sha16(Q / "proofs/2026-10-21_v2_confirm/placement_s24/prompts.jsonl"),
                          "subset": "(d,n) in (0,48),(4,48),(8,48) + d in {18,36} x n in {48,96,144}"},
        "device_reference": ["proofs/2026-10-21_v2_confirm/host400_k8/samples.jsonl",
                             "proofs/2026-10-21_v2_confirm/placement_s24/samples.jsonl"]},
    "scoring": {"host400": "common_v2.score_one (same as eval_htpd_v2.py)",
                "placement": "placement_v2.analyze rules (parse_answer, _norm, pattern == truth; clean: status != normal)",
                "chain": "sim_chain_s24.py logic (WindowN policy, spike/dip keep rule) applied per source",
                "stats": "Wilson 95% CI, exact two-sided McNemar on paired rows/cases"},
    "files": {str(p.relative_to(HERE)).replace("\\", "/"):
              {"sha16": sha16(p), "lines": nlines(p) if p.suffix in (".jsonl", ".md", ".py", ".log") else None}
              for p in sorted(HERE.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and p.name != "manifest.json"},
}
(HERE / "manifest.json").write_text(json.dumps(man, indent=1))
print(json.dumps({k: v for k, v in man.items() if k != "files"}, indent=1))
