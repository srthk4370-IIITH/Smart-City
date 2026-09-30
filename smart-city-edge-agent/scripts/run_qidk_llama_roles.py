"""Run the Air Agent and Orchestrator prompts through a deployed Genie bundle."""
from __future__ import annotations
import argparse
import json
import subprocess
import time

def invoke(adb: str, serial: str, bundle: str, config: str, prompt: str) -> dict:
    escaped = prompt.replace("'", "'\\\"'\\\"'")
    command = f"cd {bundle} && export LD_LIBRARY_PATH=. && export ADSP_LIBRARY_PATH=. && ./genie-t2t-run -c {config} -p '{escaped}'"
    started = time.perf_counter(); result = subprocess.run([adb, "-s", serial, "shell", command], capture_output=True, text=True); elapsed = (time.perf_counter()-started)*1000
    return {"exit_code": result.returncode, "latency_ms": round(elapsed, 2), "stdout": result.stdout, "stderr": result.stderr}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--adb", required=True); parser.add_argument("--serial", default="3ce9a4e2"); parser.add_argument("--bundle", default="/data/local/tmp/smart_city_edge/genie_bundle"); parser.add_argument("--config", required=True); args = parser.parse_args()
    evidence = {"event_id":"qidk_demo_001","measurements":{"co2_ppm":1250,"temperature_c":27,"relative_humidity_pct":55,"pm25_ug_m3":18,"pm10_ug_m3":30,"aqi":90}}
    air_prompt = AIR_SYSTEM = "You are the Air Quality Agent. Return JSON only. Never identify root cause or control equipment. Evidence: " + json.dumps(evidence)
    air = invoke(args.adb, args.serial, args.bundle, args.config, air_prompt)
    orch_prompt = "You are the Smart City Orchestrator. Return JSON only with agents_in_order, allowed_evidence_fields, root_cause:null, requires_human_approval:true. Never control equipment. Event: " + json.dumps(evidence) + " Air-agent raw output: " + air["stdout"]
    orchestrator = invoke(args.adb, args.serial, args.bundle, args.config, orch_prompt)
    print(json.dumps({"air_quality_agent": air, "orchestrator": orchestrator}, indent=2))
