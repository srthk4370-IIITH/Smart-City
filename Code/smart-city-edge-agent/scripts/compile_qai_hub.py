"""Compile merged Llama 3.2 model for Snapdragon NPU via Qualcomm AI Hub.

Uses Qualcomm AI Hub Models (qai_hub_models) for Hexagon NPU compilation.
Automatically uses local model weights and handles Hugging Face authentication.
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile Llama 3.2 for Qualcomm Snapdragon NPU via Qualcomm AI Hub")
    parser.add_argument("--checkpoint", type=str, default="DEFAULT", help="AIMET checkpoint path or 'DEFAULT' to use Qualcomm pre-quantized weights")
    parser.add_argument("--device", type=str, default="Samsung Galaxy S24 (Family)", help="Qualcomm AI Hub target device for SM8650 / Snapdragon 8 Gen 3")
    parser.add_argument("--output", type=Path, default=Path("models/genie_bundle"), help="Output directory for compiled bundle")
    parser.add_argument("--hf-token", type=str, default=None, help="Hugging Face API token (for Meta gated model access)")
    args = parser.parse_args()

    # 1. Resolve Hugging Face token (from argument, environment, or cached file)
    hf_token = args.hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not hf_token:
        cached_token = Path.home() / ".cache" / "huggingface" / "token"
        if cached_token.exists():
            try:
                hf_token = cached_token.read_text(encoding="utf-8").strip()
            except Exception:
                pass

    if hf_token:
        os.environ["HF_TOKEN"] = hf_token
        os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token
        print("✓ Authenticated via Hugging Face token.")
    else:
        print("ℹ No Hugging Face token specified; will rely on verified local model files.")

    # 2. Resolve local model path (prefer merged fine-tuned model, fall back to base model)
    local_merged = Path("models/merged/llama-orchestrator-agent").resolve()
    local_base = Path("models/base/llama-3.2-3b-instruct").resolve()
    target_local_model = None

    if local_merged.exists() and (local_merged / "config.json").exists():
        target_local_model = local_merged
        print(f"✓ Found local fine-tuned merged model: {target_local_model}")
    elif local_base.exists() and (local_base / "config.json").exists():
        target_local_model = local_base
        print(f"✓ Found local base model: {target_local_model}")

    if target_local_model:
        try:
            import qai_hub_models.models.llama_v3_2_3b_instruct.model as llama_model
            local_model_str = str(target_local_model)
            llama_model.HF_REPO_NAME = local_model_str

            # Monkey-patch from_pretrained to ensure local directory is used
            orig_from_pretrained = llama_model.Llama3_2_3B.from_pretrained

            @classmethod
            def patched_from_pretrained(cls, checkpoint=local_model_str, *p_args, **p_kwargs):
                if checkpoint in ("meta-llama/Llama-3.2-3B-Instruct", "DEFAULT", None):
                    checkpoint = local_model_str
                return orig_from_pretrained(checkpoint=checkpoint, *p_args, **p_kwargs)

            llama_model.Llama3_2_3B.from_pretrained = patched_from_pretrained

            # Monkey-patch __init__
            orig_init = llama_model.Llama3_2_3B.__init__

            def patched_init(self, checkpoint=local_model_str, *p_args, **p_kwargs):
                if checkpoint in ("meta-llama/Llama-3.2-3B-Instruct", "DEFAULT", None):
                    checkpoint = local_model_str
                return orig_init(self, checkpoint=checkpoint, *p_args, **p_kwargs)

            llama_model.Llama3_2_3B.__init__ = patched_init
            print("✓ Successfully patched Llama3_2_3B to load directly from local disk.")
        except Exception as e:
            print(f"Note: Could not patch Llama3_2_3B defaults: {e}")

    print("=" * 70)
    print("QUALCOMM AI HUB CLOUD EXPORT & COMPILATION (LLAMA 3.2 3B)")
    print("=" * 70)
    print(f"Checkpoint       : {args.checkpoint}")
    print(f"Target Hardware  : {args.device} (SM8650 / Snapdragon 8 Gen 3 / V75 NPU)")
    print(f"Output Directory : {args.output}")
    print("\nDelegating quantization & compilation to Qualcomm AI Hub cloud compiler...")

    args.output.mkdir(parents=True, exist_ok=True)

    # Set sys.argv for export_main
    sys_args = [
        "export.py",
        "--device", args.device,
        "--skip-inferencing",
        "--skip-profiling",
        "--output-dir", str(args.output),
    ]
    if args.checkpoint != "DEFAULT":
        sys_args.extend(["--checkpoint", args.checkpoint])

    sys.argv = sys_args

    try:
        from qai_hub_models.models.llama_v3_2_3b_instruct.export import main as export_entry
        export_entry()
        print("\n✅ Qualcomm AI Hub compilation and download completed successfully!")
        print(f"Compiled bundle is ready in: {args.output}")
    except Exception as exc:
        err_str = str(exc)
        print(f"\n❌ Compilation encountered an error: {err_str}")
        print("\nDetailed Diagnosis:")
        if "401" in err_str or "Unauthorized" in err_str or "gated" in err_str.lower():
            print("• Hugging Face Authorization Error:")
            print("  Meta Llama 3.2 is gated. Ensure your token in ~/.cache/huggingface/token has read access.")
        else:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
