#!/usr/bin/env bash

# Script to run all pytest unit tests and save full output logs to reports/test_results.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

mkdir -p "${PROJECT_DIR}/reports"
LOG_FILE="${PROJECT_DIR}/reports/test_results.log"

echo "============================================================"
echo "Running Smart City Edge AI Test Suite..."
echo "Log file destination: ${LOG_FILE}"
echo "============================================================"

cd "${PROJECT_DIR}"
pytest -v --tb=short 2>&1 | tee "${LOG_FILE}"

echo ""
echo "============================================================"
echo "Test execution complete. Log saved to: ${LOG_FILE}"
echo "============================================================"
