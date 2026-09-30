# Smart City Edge AI — Makefile
# Run from smart-city-edge-agent/ directory after: source .venv/bin/activate

PYTHON      := .venv/bin/python
PYTEST      := .venv/bin/pytest
LIMIT       := 5000
SEED        := 42
DATASET     ?= /mnt/c/Users/hp/Desktop/dataset
LABELS      ?= data/labels/incidents.jsonl
EVENTS      ?= data/processed/five_domain_events.jsonl

.PHONY: help manifest preflight train train-full train-bootstrap prepare-llama-roles download-base train-llama-roles merge-llama-roles demo-bootstrap test-bootstrap qidk-header test test-unit extract clean

# Default target
help:
	@echo ""
	@echo "Smart City Edge AI — Available Commands"
	@echo "========================================"
	@echo "  make manifest       Hash and record the raw dataset"
	@echo "  make train          Train per-domain anomaly models on $(LIMIT) rows/domain"
	@echo "  make train-full     Train per-domain anomaly models on the full dataset"
	@echo "  make prepare-sft    Validate approved labels and create Llama training JSONL"
	@echo "  make download-base  Download licensed Llama 3.2 3B source weights"
	@echo "  make train-slm      QLoRA fine-tune Llama from approved labels"
	@echo "  make prepare-llama-roles Create Llama role-training JSONL from routing corpus"
	@echo "  make train-llama-roles Train shared Llama agent/orchestrator adapter"
	@echo "  make merge-llama-roles Merge adapter into weights for Qualcomm export"
	@echo "  make train-bootstrap Train Air Quality agent + routing orchestrator"
	@echo "  make demo-bootstrap  Show one end-to-end routing result"
	@echo "  make test-bootstrap  Verify trained artifacts and black-box contract"
	@echo "  make qidk-header     Generate C++ policy header for QIDK runner"
	@echo "  make train LIMIT=N  Train with custom row limit per CSV"
	@echo "  make test           Run all 16 unit tests"
	@echo "  make test-unit      Run unit tests verbosely (with live output)"
	@echo "  make extract        Extract anomaly event windows from dataset ($(LIMIT) rows)"
	@echo "  make extract-full   Extract from full dataset"
	@echo "  make clean          Remove generated model, events, and test logs"
	@echo ""

# ── Training ──────────────────────────────────────────────────────────────────

manifest:
	$(PYTHON) scripts/build_dataset_manifest.py --data-dir $(DATASET)

preflight:
	$(PYTHON) scripts/preflight_training.py --data-dir $(DATASET) --labels $(LABELS)

train: manifest
	@echo "\n>>> Training per-domain anomaly models (limit=$(LIMIT), seed=$(SEED))...\n"
	$(PYTHON) scripts/train_domain_anomaly.py --data-dir $(DATASET) --limit $(LIMIT) --seed $(SEED) --assume-unlabeled-normal

train-full: manifest
	@echo "\n>>> Training per-domain anomaly models on full datasets...\n"
	$(PYTHON) scripts/train_domain_anomaly.py --data-dir $(DATASET) --limit 0 --seed $(SEED) --assume-unlabeled-normal

prepare-sft:
	$(PYTHON) scripts/prepare_sft_dataset.py --events $(EVENTS) --labels $(LABELS)

download-base:
	$(PYTHON) scripts/download_llama.py

train-slm:
	$(PYTHON) scripts/train_llama_lora.py

prepare-llama-roles:
	$(PYTHON) scripts/prepare_llama_agent_orchestrator_sft.py

train-llama-roles:
	$(PYTHON) scripts/train_llama_lora.py --config configs/training/llama3_2_3b_agent_orchestrator_lora.yaml

merge-llama-roles:
	$(PYTHON) scripts/merge_llama_adapter.py

train-bootstrap: manifest
	$(PYTHON) scripts/train_bootstrap_agents.py --data-dir $(DATASET)

demo-bootstrap:
	$(PYTHON) scripts/demo_bootstrap_agents.py

test-bootstrap:
	$(PYTHON) scripts/test_bootstrap_models.py

qidk-header:
	$(PYTHON) scripts/generate_qidk_runner_header.py

# ── Event Extraction ──────────────────────────────────────────────────────────

extract:
	@echo "\n>>> Extracting anomaly event windows (limit=$(LIMIT) rows)...\n"
	$(PYTHON) scripts/extract_events.py --limit $(LIMIT)

extract-full:
	@echo "\n>>> Extracting from FULL dataset...\n"
	$(PYTHON) scripts/extract_events.py --full

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	@echo "\n>>> Running all unit tests...\n"
	$(PYTEST) -q 2>&1 | tee reports/test_results.log
	@echo "\nLog saved to reports/test_results.log"

test-unit:
	@echo "\n>>> Running all unit tests (verbose)...\n"
	$(PYTEST) -v --tb=short 2>&1 | tee reports/test_results.log

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:
	@echo "\n>>> Cleaning generated artifacts...\n"
	rm -f models/anomaly/model.onnx models/anomaly/norm_params.json
	rm -f data/processed/scrc_events.jsonl
	rm -f reports/test_results.log
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete."
