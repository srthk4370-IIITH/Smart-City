"""Create structured role-training examples for Llama 3.2 3B agent orchestrator SFT.

Generates multi-domain routing and agent triage samples covering:
1. Air Quality Agent
2. Energy Grid Agent
3. Water Infrastructure Agent
4. Weather & Microclimate Agent
5. Occupancy & Mobility Agent
6. Multi-domain cross-cutting routing plans (Air+Energy, Water+Energy, Air+Weather+Occupancy, Full Smart City)

Guarantees multi-domain routing diversity so the Orchestrator does NOT always route to Air Quality only.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

AIR_SYSTEM = (
    "You are the Air Quality Agent. Return JSON only. Classify the supplied evidence, "
    "cite only supplied fields, state uncertainty, never identify a root cause, and never control equipment."
)
ORCH_SYSTEM = (
    "You are the Smart City Orchestrator. Return JSON only. Select the ordered domain-agent calls "
    "and the allowed evidence fields for a separate reasoning model. Never identify a root cause, "
    "never control equipment, and require human approval."
)

DOMAIN_SCENARIOS = [
    # Air Quality scenarios
    {
        "triage": "co2_elevated",
        "measurements": {"co2_ppm": 1250.0, "pm25_ug_m3": 18.2, "temperature_c": 24.5, "relative_humidity_pct": 52.0, "energy_kw": 14.2, "water_flow_lpm": 8.1, "occupancy_count": 85},
        "agents_in_order": ["air_quality", "occupancy", "energy"],
        "plan": "air_then_occupancy_energy",
        "evidence_fields": ["co2_ppm", "occupancy_count", "energy_kw"]
    },
    {
        "triage": "pm25_elevated",
        "measurements": {"co2_ppm": 450.0, "pm25_ug_m3": 88.5, "pm10_ug_m3": 110.0, "temperature_c": 31.0, "relative_humidity_pct": 28.0, "weather_wind_speed_kmh": 2.1},
        "agents_in_order": ["air_quality", "weather"],
        "plan": "air_then_weather",
        "evidence_fields": ["pm25_ug_m3", "pm10_ug_m3", "weather_wind_speed_kmh"]
    },
    # Energy Grid scenarios
    {
        "triage": "energy_spike_substation",
        "measurements": {"energy_kw": 185.4, "grid_voltage_v": 208.1, "co2_ppm": 890.0, "temperature_c": 36.2, "occupancy_count": 120},
        "agents_in_order": ["energy", "air_quality", "weather"],
        "plan": "energy_then_air_weather",
        "evidence_fields": ["energy_kw", "grid_voltage_v", "temperature_c"]
    },
    # Water Infrastructure scenarios
    {
        "triage": "water_flow_leak_detected",
        "measurements": {"water_flow_lpm": 340.0, "water_pressure_psi": 18.5, "temperature_c": 22.0, "energy_kw": 45.0},
        "agents_in_order": ["water", "energy"],
        "plan": "water_then_energy",
        "evidence_fields": ["water_flow_lpm", "water_pressure_psi", "energy_kw"]
    },
    # Multi-Domain Industrial / Microclimate Crisis
    {
        "triage": "multi_domain_air_energy_crisis",
        "measurements": {"co2_ppm": 1800.0, "pm25_ug_m3": 145.0, "energy_kw": 240.0, "temperature_c": 38.5, "relative_humidity_pct": 15.0, "occupancy_count": 210},
        "agents_in_order": ["air_quality", "energy", "occupancy", "weather"],
        "plan": "air_energy_occupancy_weather",
        "evidence_fields": ["co2_ppm", "pm25_ug_m3", "energy_kw", "temperature_c", "occupancy_count"]
    },
    {
        "triage": "multi_domain_water_energy_weather_crisis",
        "measurements": {"water_flow_lpm": 510.0, "energy_kw": 310.0, "temperature_c": 41.2, "relative_humidity_pct": 12.0, "weather_wind_speed_kmh": 45.0},
        "agents_in_order": ["water", "energy", "weather"],
        "plan": "water_energy_weather",
        "evidence_fields": ["water_flow_lpm", "energy_kw", "temperature_c", "weather_wind_speed_kmh"]
    },
    # Full Smart City Anomaly
    {
        "triage": "full_city_cross_domain_cascade",
        "measurements": {"co2_ppm": 2100.0, "pm25_ug_m3": 190.0, "energy_kw": 450.0, "water_flow_lpm": 620.0, "occupancy_count": 350, "temperature_c": 42.0},
        "agents_in_order": ["air_quality", "energy", "water", "occupancy", "weather"],
        "plan": "full_smart_city_cascade",
        "evidence_fields": ["co2_ppm", "pm25_ug_m3", "energy_kw", "water_flow_lpm", "occupancy_count", "temperature_c"]
    }
]


def generate_augmented_dataset(base_corpus_path: Path, output_path: Path, num_augmented: int = 300) -> None:
    random.seed(42)
    output = []
    
    # 1. Include base corpus rows if file exists
    if base_corpus_path.is_file():
        rows = [json.loads(line) for line in base_corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            event = {"event_id": row["event_id"], "measurements": row["measurements"], "available_evidence_fields": list(row["measurements"])}
            air = {"event_id": row["event_id"], "domain": "air_quality", "triage": row["agent_label"], "evidence_fields": list(row["measurements"]), "root_cause": None, "requires_human_approval": True, "uncertainty": "Routing bootstrap labels only."}
            orchestrator = {"event_id": row["event_id"], "agents_in_order": row["agents_in_order"], "orchestration_plan": row["orchestration_plan"], "allowed_evidence_fields": row["black_box_payload"]["evidence_fields"], "root_cause": None, "requires_human_approval": True}
            output.extend([
                {"event_id": row["event_id"], "role": "air_quality_agent", "split": row["split"], "messages": [{"role": "system", "content": AIR_SYSTEM}, {"role": "user", "content": json.dumps(event, separators=(",", ":"), sort_keys=True)}, {"role": "assistant", "content": json.dumps(air, separators=(",", ":"), sort_keys=True)}]},
                {"event_id": row["event_id"], "role": "orchestrator", "split": row["split"], "messages": [{"role": "system", "content": ORCH_SYSTEM}, {"role": "user", "content": json.dumps(event, separators=(",", ":"), sort_keys=True)}, {"role": "assistant", "content": json.dumps(orchestrator, separators=(",", ":"), sort_keys=True)}]},
            ])

    # 2. Add multi-domain synthetic scenarios to guarantee multi-domain routing
    for i in range(num_augmented):
        scenario = random.choice(DOMAIN_SCENARIOS)
        # Jitter measurements slightly
        meas = {}
        for k, v in scenario["measurements"].items():
            jitter = random.uniform(0.92, 1.08)
            meas[k] = round(v * jitter, 2)
            
        event_id = f"synth_multidomain_{i:04d}"
        split = "train" if i < int(num_augmented * 0.8) else "dev" if i < int(num_augmented * 0.9) else "test"
        
        event = {"event_id": event_id, "measurements": meas, "available_evidence_fields": list(meas.keys())}
        orchestrator_target = {
            "event_id": event_id,
            "agents_in_order": scenario["agents_in_order"],
            "orchestration_plan": scenario["plan"],
            "allowed_evidence_fields": scenario["evidence_fields"],
            "root_cause": None,
            "requires_human_approval": True
        }
        
        output.append({
            "event_id": event_id,
            "role": "orchestrator",
            "split": split,
            "messages": [
                {"role": "system", "content": ORCH_SYSTEM},
                {"role": "user", "content": json.dumps(event, separators=(",", ":"), sort_keys=True)},
                {"role": "assistant", "content": json.dumps(orchestrator_target, separators=(",", ":"), sort_keys=True)}
            ]
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(json.dumps(item, separators=(",", ":")) + "\n" for item in output), encoding="utf-8")
    print(f"Success: Wrote {len(output)} multi-domain agent/orchestrator SFT examples to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("models/bootstrap/bootstrap_air_routing_corpus.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/sft/agent_orchestrator.jsonl"))
    parser.add_argument("--num-augmented", type=int, default=300)
    args = parser.parse_args()
    generate_augmented_dataset(args.corpus, args.output, args.num_augmented)
