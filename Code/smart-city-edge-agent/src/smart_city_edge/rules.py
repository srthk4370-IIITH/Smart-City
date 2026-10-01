"""Rule Engine Baseline & Anomaly Trigger (Phase 6).

Evaluates FeatureWindow statistics against domain thresholds in configs/thresholds.yaml.
Emits AnomalyEvent triggers and conservative Rule-Based RootCauseReport (Mode 1).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from smart_city_edge.schemas import (
    AnomalyEvent,
    Domain,
    FeatureWindow,
    RootCauseReport,
)


class RuleEngine:
    """Evaluates sensor feature statistics against rule thresholds."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.thresholds: dict[str, float] = {
            "indoor_co2_max": 1000.0,
            "indoor_pm25_max": 35.0,
            "water_pressure_max_kpa": 400.0,
            "energy_kw_max": 100.0,
            "water_flowrate_max": 50.0,
        }
        if config_path:
            path = Path(config_path)
            if path.is_file():
                with open(path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f) or {}
                    if isinstance(loaded, dict):
                        self.thresholds.update({k: float(v) for k, v in loaded.items() if isinstance(v, (int, float))})

    def evaluate_window(
        self, window: FeatureWindow
    ) -> tuple[AnomalyEvent | None, RootCauseReport | None]:
        """Evaluate feature window; emit AnomalyEvent and Mode 1 Rule Report on breach."""
        breached_domains: set[Domain] = set()
        cited_evidence: list[str] = []
        violations: list[str] = []

        features = window.features

        # Check CO2 threshold (Air Quality)
        co2_val = features.get("indoor_co2_mean", features.get("indoor_co2", 0.0))
        if co2_val > self.thresholds.get("indoor_co2_max", 1000.0):
            breached_domains.add(Domain.AIR_QUALITY)
            violations.append(f"Indoor CO2 level ({co2_val:.1f} ppm) exceeded threshold ({self.thresholds['indoor_co2_max']} ppm)")
            cited_evidence.extend([ev for ev in window.evidence_ids if "co2" in ev or "air" in ev or "pm" in ev])

        # Check PM2.5 threshold (Air Quality)
        pm25_val = features.get("indoor_pm25_mean", features.get("indoor_pm25", 0.0))
        if pm25_val > self.thresholds.get("indoor_pm25_max", 35.0):
            breached_domains.add(Domain.AIR_QUALITY)
            violations.append(f"Indoor PM2.5 level ({pm25_val:.1f} µg/m³) exceeded threshold ({self.thresholds['indoor_pm25_max']} µg/m³)")
            cited_evidence.extend([ev for ev in window.evidence_ids if "pm25" in ev or "air" in ev])

        # Check Water Pressure / Flow threshold (Water)
        pressure_val = features.get("water_pressure_max", features.get("water_pressure_kpa", 0.0))
        if pressure_val > self.thresholds.get("water_pressure_max_kpa", 400.0):
            breached_domains.add(Domain.WATER)
            violations.append(f"Water pressure ({pressure_val:.1f} kPa) exceeded threshold ({self.thresholds['water_pressure_max_kpa']} kPa)")
            cited_evidence.extend([ev for ev in window.evidence_ids if "water" in ev or "press" in ev])

        # Check Energy threshold (Energy)
        energy_val = features.get("energy_kw_mean", features.get("energy_kw", 0.0))
        if energy_val > self.thresholds.get("energy_kw_max", 100.0):
            breached_domains.add(Domain.ENERGY)
            violations.append(f"Energy consumption ({energy_val:.1f} kW) exceeded threshold ({self.thresholds['energy_kw_max']} kW)")
            cited_evidence.extend([ev for ev in window.evidence_ids if "energy" in ev or "kw" in ev])

        if not breached_domains:
            return None, None

        # Fallback to general evidence if none domain-matched
        final_evidence = tuple(sorted(set(cited_evidence or window.evidence_ids)))
        event_id = f"evt_rule_{uuid.uuid4().hex[:8]}"

        anomaly_event = AnomalyEvent(
            event_id=event_id,
            timestamp=window.end,
            building_id=window.building_id,
            zone_id=window.zone_id,
            domains=tuple(sorted(breached_domains, key=lambda d: d.value)),
            trigger_sources=("rule",),
            severity="high" if len(breached_domains) > 1 else "medium",
            evidence_ids=final_evidence,
            anomaly_score=None,
        )

        rule_report = RootCauseReport(
            event_id=event_id,
            root_cause="; ".join(violations),
            evidence=final_evidence,
            confidence=0.99,  # High deterministic rule confidence
            recommendation=f"Rule Breach: Dispatch facility engineer to inspect {window.building_id} / {window.zone_id}",
            requires_human_approval=True,
            uncertainties=("Rule baseline evaluates fixed thresholds without multi-domain SLM context",),
        )

        return anomaly_event, rule_report
