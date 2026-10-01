import sys
import os
sys.path.insert(0, os.path.abspath('src'))
from smart_city_edge.genie_runner import GenieRunner

runner = GenieRunner(use_mock_fallback=False)
result = runner.run_prompt("Reply exactly: QIDK NPU READY", timeout_sec=90)

if result:
    print(f"Exit Code: {result.exit_code}")
    print(f"Latency (ms): {round(result.latency_ms)}")
    print(f"Output:\n{result.raw_output}")
else:
    print("Execution failed (returned None)")
