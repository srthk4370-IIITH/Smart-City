"""QLoRA fine-tuning for the model family that will be benchmarked on QIDK."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path


def records(path: Path, split: str, max_examples: int | None = None, seed: int = 42) -> list[dict]:
    result = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = [row for row in result if row.get("split") == split]
    if not selected: raise ValueError(f"No {split} examples in {path}")
    if max_examples and len(selected) > max_examples:
        random.Random(seed).shuffle(selected)
        selected = selected[:max_examples]
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/training/llama3_2_3b_agent_orchestrator_lora.yaml"))
    args = parser.parse_args()
    try:
        import torch, yaml
        from torch.utils.data import Dataset
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, DataCollatorForSeq2Seq, Trainer, TrainingArguments
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    except ImportError as exc:
        raise SystemExit("Install requirements-training.txt with a CUDA PyTorch build in WSL first.") from exc
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    model_dir, dataset_path, output_dir = (Path(config[key]) for key in ("model_dir", "prepared_dataset", "output_dir"))
    if not model_dir.is_dir(): raise SystemExit(f"Base model missing: {model_dir}. Run scripts/download_llama.py after accepting the Meta licence.")
    if not dataset_path.is_file(): raise SystemExit(f"Prepared labelled data missing: {dataset_path}. Run scripts/prepare_sft_dataset.py first.")
    if output_dir.exists() and any(output_dir.iterdir()): raise SystemExit(f"Refusing to overwrite existing output: {output_dir}")
    if not torch.cuda.is_available(): raise SystemExit("QLoRA training requires CUDA; use the NVIDIA-enabled WSL environment.")
    random.seed(config["seed"]); torch.manual_seed(config["seed"])
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    if tokenizer.pad_token is None: tokenizer.pad_token = tokenizer.eos_token
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(model_dir, local_files_only=True, quantization_config=quant, device_map="auto")
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )
    lora = LoraConfig(r=config["lora_rank"], lora_alpha=config["lora_alpha"], lora_dropout=config["lora_dropout"], target_modules=config["target_modules"], bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)
    class ChatDataset(Dataset):
        def __init__(self, examples: list[dict]): self.examples = examples
        def __len__(self): return len(self.examples)
        def __getitem__(self, index):
            messages = self.examples[index]["messages"]
            prefix = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
            full = prefix + messages[-1]["content"] + tokenizer.eos_token
            encoded = tokenizer(full, truncation=True, max_length=config["max_sequence_length"])
            prefix_ids = tokenizer(prefix, add_special_tokens=False)["input_ids"]
            labels = [-100] * len(encoded["input_ids"])
            p_len = len(prefix_ids)
            if p_len < len(encoded["input_ids"]):
                labels[p_len:] = encoded["input_ids"][p_len:]
            else:
                # If sequence was heavily truncated, keep at least the last token for gradient computation
                labels[-1] = encoded["input_ids"][-1]
            encoded["labels"] = labels
            return encoded
    train = ChatDataset(records(dataset_path, "train", config.get("max_train_examples"), config["seed"]))
    dev = ChatDataset(records(dataset_path, "dev", config.get("max_dev_examples"), config["seed"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    training_args = TrainingArguments(output_dir=str(output_dir), num_train_epochs=config["epochs"], learning_rate=config["learning_rate"], per_device_train_batch_size=config["per_device_train_batch_size"], per_device_eval_batch_size=1, gradient_accumulation_steps=config["gradient_accumulation_steps"], logging_steps=config["logging_steps"], save_steps=config["save_steps"], eval_strategy="steps", eval_steps=config["save_steps"], save_total_limit=2, warmup_ratio=config["warmup_ratio"], fp16=True, report_to="none", seed=config["seed"], remove_unused_columns=False)
    trainer = Trainer(model=model, args=training_args, train_dataset=train, eval_dataset=dev, data_collator=DataCollatorForSeq2Seq(tokenizer, pad_to_multiple_of=8, label_pad_token_id=-100))
    trainer.train(); trainer.save_model(); tokenizer.save_pretrained(output_dir)
    metadata = {"base_model_id": config["model_id"], "base_model_dir": str(model_dir), "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(), "config": config, "test_split": "held out; not loaded by trainer", "warning": "This adapter is not a QAIRT/Genie bundle. Re-export and validate with the Qualcomm-supported pipeline before deployment."}
    (output_dir / "training_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Saved LoRA adapter to {output_dir}")


if __name__ == "__main__": main()
