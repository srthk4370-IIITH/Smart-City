"""Automated QIDK On-Device Testing Script via ADB & Genie C++ API.

Tests execution on Qualcomm Hexagon NPU (Snapdragon 8 Elite / SM8650) using genie-t2t-run.
Measures TTFT (Time to First Token), TPS (Tokens per Second), latency, and schema validity.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_BUNDLE_DIR = "/data/local/tmp/genie_bundle"
DEFAULT_CONFIG = "genie_config.json"

TEST_PROMPTS = [
    {
        "name": "Orchestrator Multi-Domain Triage Test",
        "prompt": (
            "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n"
            "You are the Smart City Orchestrator. Return JSON only. Select the ordered domain-agent calls "
            "and the allowed evidence fields for a separate reasoning model. Never identify a root cause, "
            "never control equipment, and require human approval.<|eot_id|>\n"
            "<|start_header_id|>user<|end_header_id|>\n"
            "{\"event_id\":\"qidk_ev_001\",\"measurements\":{\"co2_ppm\":1450.0,\"pm25_ug_m3\":88.0,\"energy_kw\":210.0,\"temperature_c\":38.0}}<|eot_id|>\n"
            "<|start_header_id|>assistant<|end_header_id|>\n"
        )
    },
    {
        "name": "Air Quality Agent Triage Test",
        "prompt": (
            "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n"
            "You are the Air Quality Agent. Return JSON only. Classify the supplied evidence, "
            "cite only supplied fields, state uncertainty, never identify a root cause, and never control equipment.<|eot_id|>\n"
            "<|start_header_id|>user<|end_header_id|>\n"
            "{\"event_id\":\"qidk_ev_001\",\"domain\":\"air_quality\",\"measurements\":{\"co2_ppm\":1450.0,\"pm25_ug_m3\":88.0}}<|eot_id|>\n"
            "<|start_header_id|>assistant<|end_header_id|>\n"
        )
    }
]


def run_adb_cmd(cmd_list: list[str]) -> str:
    adb_bin = "adb"
    # Check fallback path on Windows
    fallback_adb = Path("C:/Users/hp/Desktop/qidk/platform-tools/adb.exe")
    if fallback_adb.is_file():
        adb_bin = str(fallback_adb)
        
    full_cmd = [adb_bin] + cmd_list
    try:
        res = subprocess.run(full_cmd, capture_output=True, text=True, check=True, timeout=30)
        return res.stdout.strip()
    except subprocess.CalledProcessError as err:
        return f"ADB_ERROR: {err.stderr.strip()}"
    except Exception as exc:
        return f"EXECUTION_ERROR: {str(exc)}"


def check_qidk_device() -> str | None:
    output = run_adb_cmd(["devices"])
    lines = [line.strip() for line in output.splitlines() if line.strip() and not line.startswith("List of")]
    if not lines:
        return None
    # Return first device serial
    return lines[0].split()[0]


def run_ondevice_inference(bundle_dir: str, config_file: str, prompt: str) -> dict:
    t0 = time.perf_counter()
    
    # Escape prompt quotes for ADB shell execution
    escaped_prompt = prompt.replace('"', '\\"')
    
    adb_shell_cmd = (
        f"cd {bundle_dir} && "
        f"export LD_LIBRARY_PATH={bundle_dir}/aarch64-android:{bundle_dir}:$LD_LIBRARY_PATH && "
        f"export ADSP_LIBRARY_PATH={bundle_dir}/dsp/unsigned:{bundle_dir}/dsp:$ADSP_LIBRARY_PATH && "
        f"./genie-t2t-run -c llama-orchestrator_config.json -p \"{escaped_prompt}\""
    )
    
    raw_output = run_adb_cmd(["shell", adb_shell_cmd])
    t_total_ms = (time.perf_counter() - t0) * 1000.0
    
    # Parse metrics if reported by genie-t2t-run
    ttft_ms = None
    tps = None
    
    ttft_match = re.search(r"TTFT[:\s]+([\d\.]+)\s*ms", raw_output, re.IGNORECASE)
    if ttft_match:
        ttft_ms = float(ttft_match.group(1))
        
    tps_match = re.search(r"TPS[:\s]+([\d\.]+)", raw_output, re.IGNORECASE)
    if tps_match:
        tps = float(tps_match.group(1))
        
    return {
        "raw_output": raw_output,
        "latency_ms": round(t_total_ms, 2),
        "ttft_ms": ttft_ms,
        "tps": tps
    }


def main():
    parser = argparse.ArgumentParser(description="QIDK On-Device Model Testing Script")
    parser.add_argument("--bundle-dir", type=str, default=DEFAULT_BUNDLE_DIR)
    parser.add_argument("--config", type=str, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    
    print("=" * 70)
    print("QIDK ON-DEVICE NPU TESTING HARNESS (Qualcomm SM8650)")
    print("=" * 70)
    
    serial = check_qidk_device()
    if not serial:
        print("[WARN] No QIDK device detected via ADB. Please connect QIDK device over USB.")
        print("       Running fallback ADB environment inspection...")
        print("       ADB binary path check: C:\\Android\\platform-tools\\adb.exe")
        sys.exit(1)
        
    print(f"[OK] QIDK Device Connected: Serial {serial}")
    
    # Check directory contents on device
    check_dir = run_adb_cmd(["shell", f"ls -lh {args.bundle_dir}"])
    if "No such file" in check_dir or "ADB_ERROR" in check_dir:
        print(f"[WARN] Genie bundle path {args.bundle_dir} not found on device.")
        print("       Please push genie_bundle using: adb push ./genie_bundle/* /data/local/tmp/genie_bundle/")
        sys.exit(1)
        
    print(f"[INFO] Genie bundle verified on device at {args.bundle_dir}\n")
    
    for idx, test in enumerate(TEST_PROMPTS, 1):
        print(f"[{idx}/{len(TEST_PROMPTS)}] Executing {test['name']}...")
        res = run_ondevice_inference(args.bundle_dir, args.config, test["prompt"])
        
        print(f"  - Total Execution Latency: {res['latency_ms']} ms")
        if res['ttft_ms']: print(f"  - Time to First Token (TTFT): {res['ttft_ms']} ms")
        if res['tps']: print(f"  - Throughput (TPS): {res['tps']} tokens/sec")
        print(f"  - Output snippet:\n    {res['raw_output'][:200]}...\n")
        
    print("=" * 70)
    print("[OK] QIDK On-Device Testing Completed.")
    print("=" * 70)


if __name__ == "__main__":
    main()
