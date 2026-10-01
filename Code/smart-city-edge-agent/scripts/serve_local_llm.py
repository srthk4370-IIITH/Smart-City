"""Local LLM Server (WSL Bridge) for Web App Inference.

This script exposes a FastAPI endpoint at port 8001. It loads the fine-tuned
Llama-3.2-3B orchestrator model (merged or base+LoRA) to serve inference requests
locally with zero cloud compilation requirements.
"""
from __future__ import annotations

from pathlib import Path
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
except ImportError:
    raise RuntimeError("Missing PyTorch or Transformers. Run this in the WSL .venv environment.")

app = FastAPI(title="Local LLM Inference Server")

MERGED_DIR = Path("models/merged/llama-orchestrator-agent")
BASE_DIR = Path("models/base/llama-3.2-3b-instruct")
LORA_DIR = Path("models/llama-lora/agent-orchestrator-3b")


class GenerationRequest(BaseModel):
    prompt: str
    temperature: float = 0.1
    max_tokens: int = 512


model = None
tokenizer = None


@app.on_event("startup")
async def load_model() -> None:
    global model, tokenizer

    # 1. Select best local model directory
    if MERGED_DIR.exists() and (MERGED_DIR / "config.json").exists():
        model_dir = MERGED_DIR
        print(f"✓ Loading fine-tuned merged model from: {model_dir}")
        use_lora = False
    elif BASE_DIR.exists() and (BASE_DIR / "config.json").exists():
        model_dir = BASE_DIR
        print(f"✓ Loading base model from: {model_dir}")
        use_lora = LORA_DIR.exists()
    else:
        raise FileNotFoundError(f"Neither {MERGED_DIR} nor {BASE_DIR} found on disk.")

    # 2. Load tokenizer completely offline
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 3. Determine device and quantization
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Target execution device: {device}")

    try:
        from transformers import BitsAndBytesConfig
        quant = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        base_model = AutoModelForCausalLM.from_pretrained(
            model_dir,
            local_files_only=True,
            quantization_config=quant if device == "cuda" else None,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            device_map="auto" if device == "cuda" else None,
        )
    except Exception as e:
        print(f"BitsAndBytes not available or failed ({e}); falling back to standard precision: {device}")
        base_model = AutoModelForCausalLM.from_pretrained(
            model_dir,
            local_files_only=True,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        )
        base_model.to(device)

    # 4. Attach LoRA if using base model
    if use_lora:
        try:
            from peft import PeftModel
            print(f"✓ Attaching LoRA adapter from: {LORA_DIR}")
            model = PeftModel.from_pretrained(base_model, LORA_DIR)
        except Exception as err:
            print(f"Warning: Could not attach LoRA ({err}), using base model directly.")
            model = base_model
    else:
        model = base_model

    model.eval()
    print("✅ Model loaded and ready to serve requests on port 8001!")


@app.post("/generate")
async def generate(req: GenerationRequest) -> dict:
    if not model or not tokenizer:
        return {"error": "Model not loaded"}

    device = next(model.parameters()).device
    inputs = tokenizer(req.prompt, return_tensors="pt").to(device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=req.max_tokens,
            temperature=req.temperature,
            do_sample=True if req.temperature > 0 else False,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )

    input_len = inputs["input_ids"].shape[1]
    generated_tokens = outputs[0][input_len:]
    output_text = tokenizer.decode(generated_tokens, skip_special_tokens=True)

    return {
        "text": output_text,
        "prompt_tokens": input_len,
        "completion_tokens": len(generated_tokens),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
