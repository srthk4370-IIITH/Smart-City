"""Run one visible end-to-end trained-agent demonstration."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from smart_city_edge.bootstrap_runtime import BootstrapRuntime


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=Path("models/bootstrap/edge_policy.json"))
    parser.add_argument("--measurements", default='{"co2_ppm":1250,"temperature_c":27,"relative_humidity_pct":55,"pm25_ug_m3":18,"pm10_ug_m3":30,"aqi":90}')
    args = parser.parse_args()
    result = BootstrapRuntime(args.policy).run(json.loads(args.measurements))
    print(json.dumps(result, indent=2))
