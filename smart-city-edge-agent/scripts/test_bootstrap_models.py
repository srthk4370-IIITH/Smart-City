"""Verify trained artifacts locally, including the black-box input contract."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from smart_city_edge.bootstrap_runtime import BootstrapRuntime

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--model-dir", type=Path, default=Path("models/bootstrap")); args = parser.parse_args()
    required = ["air_quality_agent.joblib", "orchestrator.joblib", "air_quality_agent.onnx", "orchestrator.onnx", "edge_policy.json", "training_metadata.json"]
    missing = [name for name in required if not (args.model_dir / name).is_file()]
    if missing: raise SystemExit("Missing trained artifacts: " + ", ".join(missing))
    meta = json.loads((args.model_dir / "training_metadata.json").read_text(encoding="utf-8"))
    runtime = BootstrapRuntime(args.model_dir / "edge_policy.json")
    result = runtime.run({"co2_ppm": 1250, "temperature_c": 27, "relative_humidity_pct": 55, "pm25_ug_m3": 18, "pm10_ug_m3": 30, "aqi": 90})
    assert result["agent"] == "air_quality" and result["black_box_reasoner_input"]["root_cause"] is None
    assert result["black_box_reasoner_input"]["requires_human_approval"] is True
    print("PASS artifact integrity and routing contract")
    print(json.dumps({"test_metrics": meta["metrics"].get("test"), "demo_result": result}, indent=2))
