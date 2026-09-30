"""Download compiled Genie bundle from Qualcomm AI Hub.

This script recovers previously compiled link job outputs and assembles
the complete Genie bundle for QIDK deployment.

All 3 link jobs completed successfully on AI Hub:
  part_1: jpxl8n3lp → model mqvo2w08m
  part_2: j5m01qo9g → model mnj876pkm  
  part_3: jgnzdloqg → model mqey14o4m

Usage (WSL):
  source .venv/bin/activate
  python3 scripts/download_genie_bundle.py --output models/genie_bundle
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import qai_hub as hub


# Link job IDs from previous successful compilation
LINK_JOBS = {
    "part_1_of_3": "jpxl8n3lp",
    "part_2_of_3": "j5m01qo9g",
    "part_3_of_3": "jgnzdloqg",
}

MODEL_NAME = "llama_v3_2_3b_instruct"
# This is the cached checkpoint directory containing tokenizer files
CHECKPOINT_DIR = Path.home() / ".qaihm" / "qai-hub-models" / "models" / "llama_v3_2_3b_instruct" / "v4" / "llama32_ckpt_w4a16" / "llama32_ckpt_w4a16"


def generate_proper_genie_config(
    checkpoint_dir: Path,
    model_list: list[str],
    context_length: int = 4096,
) -> dict:
    """Generate the proper genie_config.json using the cached model config."""
    config_path = checkpoint_dir / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"config.json not found at {config_path}")

    with open(config_path) as f:
        llm_config = json.load(f)

    # Extract model parameters
    hidden_size = llm_config.get("hidden_size", 3072)
    num_attention_heads = llm_config.get("num_attention_heads", 24)
    num_key_value_heads = llm_config.get("num_key_value_heads", 8)
    head_dim = llm_config.get("head_dim", hidden_size // num_attention_heads)
    vocab_size = llm_config.get("vocab_size", 128256)
    bos_token_id = llm_config.get("bos_token_id", 128000)
    eos_token_id = llm_config.get("eos_token_id", 128009)
    rope_theta = int(llm_config.get("rope_theta", 500000))

    # Build the config in the exact format Genie runtime expects
    genie_config = {
        "dialog": {
            "version": 1,
            "type": "basic",
            "context": {
                "version": 1,
                "size": context_length,
                "n-vocab": vocab_size,
                "bos-token": bos_token_id,
                "eos-token": eos_token_id,
            },
            "sampler": {
                "version": 1,
                "seed": 42,
                "temp": 0.8,
                "top-k": 40,
                "top-p": 0.95,
            },
            "tokenizer": {"version": 1, "path": "tokenizer.json"},
            "engine": {
                "version": 1,
                "n-threads": 3,
                "backend": {
                    "version": 1,
                    "type": "QnnHtp",
                    "QnnHtp": {
                        "version": 1,
                        "use-mmap": True,
                        "spill-fill-bufsize": 0,
                        "mmap-budget": 0,
                        "poll": True,
                        "cpu-mask": "0xe0",
                        "kv-dim": head_dim,
                        "allow-async-init": False,
                    },
                    "extensions": "htp_backend_ext_config.json",
                },
                "model": {
                    "version": 1,
                    "type": "binary",
                    "binary": {
                        "version": 1,
                        "ctx-bins": model_list,
                    },
                },
            },
        }
    }

    # Handle rope_scaling for Llama 3.2
    rope_scaling = llm_config.get("rope_scaling")
    if rope_scaling is not None:
        positional_encodings = {
            "type": "rope",
            "rope-dim": head_dim // 2,
            "rope-theta": rope_theta,
            "rope-scaling": {
                "rope-type": rope_scaling.get("rope_type", "llama3"),
                "factor": 8.0,
                "low-freq-factor": rope_scaling.get("low_freq_factor", 1.0),
                "high-freq-factor": rope_scaling.get("high_freq_factor", 4.0),
                "original-max-position-embeddings": rope_scaling.get(
                    "original_max_position_embeddings", 8192
                ),
            },
        }
        genie_config["dialog"]["engine"]["model"]["positional-encoding"] = positional_encodings
    else:
        genie_config["dialog"]["engine"]["backend"]["QnnHtp"]["pos-id-dim"] = head_dim // 2
        genie_config["dialog"]["engine"]["backend"]["QnnHtp"]["rope-theta"] = rope_theta

    return genie_config


def generate_htp_backend_ext_config(output_path: Path) -> None:
    """Generate htp_backend_ext_config.json for the Genie HTP backend."""
    htp_config = {
        "graphs": {
            "vtcm_mb": 8
        }
    }
    with open(output_path / "htp_backend_ext_config.json", "w") as f:
        json.dump(htp_config, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Download compiled Genie bundle from AI Hub")
    parser.add_argument("--output", type=Path, default=Path("models/genie_bundle"), help="Output directory")
    parser.add_argument("--force", action="store_true", help="Re-download even if files exist")
    args = parser.parse_args()

    # Resolve the output path to match what the export script creates
    output_dir = args.output / f"{MODEL_NAME}-genie-w4a16-qualcomm_snapdragon_8gen3"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("GENIE BUNDLE RECOVERY — Download from AI Hub")
    print("=" * 70)

    # 1. Download compiled binaries from link jobs
    for part_name, job_id in LINK_JOBS.items():
        bin_filename = f"{MODEL_NAME}_{part_name}.bin"
        bin_path = output_dir / bin_filename

        if bin_path.exists() and bin_path.stat().st_size > 100_000_000 and not args.force:
            size_mb = bin_path.stat().st_size / (1024 * 1024)
            print(f"✓ {bin_filename} already exists ({size_mb:.0f}MB) — skipping")
            continue

        print(f"\n→ Downloading {bin_filename} from link job {job_id}...")
        try:
            link_job = hub.get_job(job_id)
            target_model = link_job.get_target_model()
            if target_model is None:
                print(f"  ❌ No target model for job {job_id}")
                continue
            target_model.download(str(bin_path))
            size_mb = bin_path.stat().st_size / (1024 * 1024)
            print(f"  ✓ Downloaded {bin_filename} ({size_mb:.0f}MB)")
        except Exception as e:
            print(f"  ❌ Failed to download {bin_filename}: {e}")
            raise

    # 2. Copy tokenizer and config files from cached checkpoint
    print("\n→ Copying tokenizer and config from cached checkpoint...")
    tokenizer_files = [
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "chat_template.jinja",
        "config.json",
    ]
    for fname in tokenizer_files:
        src = CHECKPOINT_DIR / fname
        dst = output_dir / fname
        if src.exists():
            shutil.copy2(str(src), str(dst))
            print(f"  ✓ Copied {fname}")
        else:
            print(f"  ⚠ {fname} not found in checkpoint cache")

    # 3. Generate proper genie_config.json
    print("\n→ Generating genie_config.json...")
    model_list = [f"{MODEL_NAME}_{part}.bin" for part in LINK_JOBS.keys()]
    try:
        genie_config = generate_proper_genie_config(
            CHECKPOINT_DIR, model_list, context_length=4096
        )
        config_path = output_dir / "genie_config.json"
        with open(config_path, "w") as f:
            json.dump(genie_config, f, indent=4)
        print(f"  ✓ Created genie_config.json (Llama 3.2 3B, context=4096)")
    except Exception as e:
        print(f"  ❌ Failed to generate genie_config.json: {e}")

    # 4. Generate htp_backend_ext_config.json
    print("\n→ Generating htp_backend_ext_config.json...")
    generate_htp_backend_ext_config(output_dir)
    print(f"  ✓ Created htp_backend_ext_config.json")

    # 5. Verify bundle completeness
    print("\n" + "=" * 70)
    print("BUNDLE VERIFICATION")
    print("=" * 70)
    required_files = {
        **{f"{MODEL_NAME}_{part}.bin": "Compiled model binary" for part in LINK_JOBS},
        "genie_config.json": "Genie runtime config",
        "tokenizer.json": "Tokenizer data",
        "config.json": "Model config",
        "htp_backend_ext_config.json": "HTP backend config",
    }
    all_ok = True
    total_size = 0
    for fname, desc in required_files.items():
        p = output_dir / fname
        if p.exists():
            size_mb = p.stat().st_size / (1024 * 1024)
            total_size += size_mb
            print(f"  ✓ {fname}: {size_mb:.1f}MB — {desc}")
        else:
            print(f"  ❌ MISSING: {fname} — {desc}")
            all_ok = False

    if all_ok:
        print(f"\n✅ GENIE BUNDLE IS COMPLETE! (Total: {total_size:.0f}MB)")
        print(f"   Location: {output_dir.resolve()}")
        print(f"\n   Next: Push to QIDK (Windows PowerShell):")
        print(f"   cd C:\\Users\\hp\\Desktop\\qidk\\smart-city-edge-agent")
        print(f"   C:\\Users\\hp\\Desktop\\qidk\\platform-tools\\adb.exe shell mkdir -p /data/local/tmp/genie_bundle/")
        print(f'   Get-ChildItem -Path "{output_dir}" | ForEach-Object {{')
        print(f"       C:\\Users\\hp\\Desktop\\qidk\\platform-tools\\adb.exe push $_.FullName /data/local/tmp/genie_bundle/")
        print(f"   }}")
    else:
        print(f"\n❌ Bundle is INCOMPLETE — check errors above.")

    return 0 if all_ok else 1


if __name__ == "__main__":
    exit(main())
