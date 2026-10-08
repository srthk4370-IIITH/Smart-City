"""Build a qai-hub-models AIMET_ONNX_EXPORT checkpoint from our merged fine-tuned weights.

Same library calls the published DEFAULT_W4A16 export uses (qai-hub-models 0.63.0), but with our merged
HF checkpoint as the FP model: published w4a16 encodings + our weights -> model_dynamic.onnx/model.data.
Usage: python build_ft_ckpt.py <merged_hf_dir> <out_ckpt_dir>
"""
import json, shutil, sys, torch
from pathlib import Path
from qai_hub_models.models.llama_v3_2_3b_instruct.model import (
    Llama3_2_3B_PreSplit as FP, Llama3_2_3B_QuantizablePreSplit as Q)
from qai_hub_models.utils.asset_loaders import CachedWebModelAsset

merged, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
cfg = json.load(open(merged / "config.json"))
assert cfg.get("tie_word_embeddings") and cfg["num_hidden_layers"] == 28 and cfg["hidden_size"] == 3072, cfg
out.mkdir(parents=True, exist_ok=True)
cpu = torch.device("cpu")
enc = CachedWebModelAsset.from_asset_store(Q.model_id, Q.model_asset_version, "w4a16/model.encodings").fetch()
shutil.copy(enc, out / "model.encodings")
fp = FP.from_pretrained(checkpoint=str(merged), host_device=cpu)
Q.create_onnx_models(checkpoint=str(out), fp_model=fp, context_length=fp.context_length,
                     host_device=cpu, llm_io_type=fp.llm_io_type)
Q.save_tokenizer_and_config(checkpoint=str(out), fp_model=fp)
json.dump({"precision": "w4a16"}, open(out / "args.json", "w"))
print("done:", sorted(p.name for p in out.iterdir()))
