# Smart City Edge AI — Makefile
# Run from smart-city-edge-agent/ directory after: source .venv/bin/activate

PYTHON      := .venv/bin/python
PYTEST      := .venv/bin/pytest
LIMIT       := 5000
SEED        := 42

.PHONY: help train train-full test test-unit extract clean

# Default target
help:
	@echo ""
	@echo "Smart City Edge AI — Available Commands"
	@echo "========================================"
	@echo "  make train          Train autoencoder on $(LIMIT) rows/CSV (80/20 split)"
	@echo "  make train-full     Train autoencoder on FULL dataset (80/20 split, slow)"
	@echo "  make train LIMIT=N  Train with custom row limit per CSV"
	@echo "  make test           Run all 16 unit tests"
	@echo "  make test-unit      Run unit tests verbosely (with live output)"
	@echo "  make extract        Extract anomaly event windows from dataset ($(LIMIT) rows)"
	@echo "  make extract-full   Extract from full dataset"
	@echo "  make clean          Remove generated model, events, and test logs"
	@echo ""

# ── Training ──────────────────────────────────────────────────────────────────

train:
	@echo "\n>>> Training autoencoder (limit=$(LIMIT) rows/CSV, seed=$(SEED))...\n"
	$(PYTHON) scripts/train_anomaly.py --limit $(LIMIT) --seed $(SEED)

train-full:
	@echo "\n>>> Training autoencoder on FULL dataset (80/20 split)...\n"
	$(PYTHON) scripts/train_anomaly.py --full --seed $(SEED)

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
