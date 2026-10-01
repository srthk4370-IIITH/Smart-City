import json
from pathlib import Path

from smart_city_edge.bootstrap_runtime import BootstrapRuntime


def test_bootstrap_runtime_returns_safe_black_box_contract(tmp_path: Path) -> None:
    # A two-class tree: CO2 <= 1000 means nominal; otherwise elevated.
    policy = {
        "feature_order": ["co2_ppm", "temperature_c"],
        "agent_class_order": ["air_nominal", "co2_elevated"],
        "plans": {"no_call": [], "air_then_occupancy_energy_weather": ["air_quality", "occupancy", "energy", "weather"]},
        "allowed_forwarded_fields": ["co2_ppm", "agent_triage", "evidence"],
        "agent_tree": {"imputation": [500.0, 25.0], "classes": ["air_nominal", "co2_elevated"], "nodes": [{"left": 1, "right": 2, "feature": 0, "threshold": 1000.0, "value": [5, 5]}, {"left": -1, "right": -1, "feature": -2, "threshold": -2.0, "value": [5, 0]}, {"left": -1, "right": -1, "feature": -2, "threshold": -2.0, "value": [0, 5]}]},
        "orchestrator_tree": {"imputation": [500.0, 25.0, 0.0], "classes": ["no_call", "air_then_occupancy_energy_weather"], "nodes": [{"left": 1, "right": 2, "feature": 2, "threshold": 0.5, "value": [5, 5]}, {"left": -1, "right": -1, "feature": -2, "threshold": -2.0, "value": [5, 0]}, {"left": -1, "right": -1, "feature": -2, "threshold": -2.0, "value": [0, 5]}]},
    }
    path = tmp_path / "edge_policy.json"; path.write_text(json.dumps(policy), encoding="utf-8")
    result = BootstrapRuntime(path).run({"co2_ppm": 1250, "temperature_c": 27})
    assert result["agent_triage"] == "co2_elevated"
    assert result["agents_in_order"] == ["air_quality", "occupancy", "energy", "weather"]
    assert result["black_box_reasoner_input"]["root_cause"] is None
    assert result["black_box_reasoner_input"]["requires_human_approval"] is True
