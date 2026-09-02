"""Unit tests for Phase 4, Phase 6, and Phase 8 modules."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pytest

from smart_city_edge.anomaly_model import AnomalyScorer, DenoisingAutoencoder, export_to_onnx
from smart_city_edge.evaluator import EvaluationHarness
from smart_city_edge.rules import RuleEngine
from smart_city_edge.schemas import AnomalyEvent, Domain, FeatureWindow
from smart_city_edge.topology import TopologyRegistry


def test_topology_registry_parsing():
    snapshot_file = Path(__file__).parents[1] / "data" / "raw" / "latest.json"
    if snapshot_file.is_file():
        registry = TopologyRegistry(snapshot_file)
        node = registry.get_node("WM-WF-PL00-70")
        assert node is not None
        assert node.name == "Palash Nivas"
        assert node.category == "wf"
        assert node.domain == Domain.WATER
        assert node.latitude is not None

        aq_nodes = registry.get_nodes_by_category("aq")
        assert len(aq_nodes) > 0


def test_rule_engine_threshold_eval():
    engine = RuleEngine()
    now = datetime.now(timezone.utc)

    # Window breaching CO2 limit
    window_breached = FeatureWindow(
        window_id="win_01",
        building_id="Vindhya_A2",
        zone_id="Zone_1",
        start=now,
        end=now,
        feature_order=("indoor_co2_mean",),
        features={"indoor_co2_mean": 1250.0},  # Exceeds 1000 threshold
        evidence_ids=("ev_co2_01",),
    )

    evt, report = engine.evaluate_window(window_breached)
    assert evt is not None
    assert report is not None
    assert Domain.AIR_QUALITY in evt.domains
    assert "1250.0 ppm" in report.root_cause
    assert report.requires_human_approval is True

    # Window with normal readings
    window_normal = FeatureWindow(
        window_id="win_02",
        building_id="Vindhya_A2",
        zone_id="Zone_1",
        start=now,
        end=now,
        feature_order=("indoor_co2_mean",),
        features={"indoor_co2_mean": 450.0},
        evidence_ids=("ev_co2_02",),
    )

    evt_norm, report_norm = engine.evaluate_window(window_normal)
    assert evt_norm is None
    assert report_norm is None


def test_autoencoder_anomaly_scorer():
    model = DenoisingAutoencoder(input_dim=16)
    scorer = AnomalyScorer(model=model, threshold=0.1, input_dim=16)

    normal_vec = np.zeros((1, 16), dtype=np.float32)
    is_anom, score = scorer.is_anomaly(normal_vec)
    assert isinstance(is_anom, bool)
    assert score >= 0.0

    with TemporaryDirectory() as tmp_dir:
        onnx_file = Path(tmp_dir) / "model.onnx"
        export_path = export_to_onnx(model, input_dim=16, output_path=onnx_file)
        assert export_path.is_file()


def test_evaluation_harness_3mode_benchmark():
    harness = EvaluationHarness()
    now = datetime.now(timezone.utc)

    evt = AnomalyEvent(
        event_id="evt_eval_01",
        timestamp=now,
        building_id="Vindhya",
        zone_id="Zone_A",
        domains=(Domain.AIR_QUALITY, Domain.ENERGY),
        trigger_sources=("rule",),
        severity="medium",
        evidence_ids=("ev_co2_01", "ev_kw_01"),
    )

    win = FeatureWindow(
        window_id="win_eval_01",
        building_id="Vindhya",
        zone_id="Zone_A",
        start=now,
        end=now,
        feature_order=("indoor_co2_mean", "energy_kw_mean"),
        features={"indoor_co2_mean": 1100.0, "energy_kw_mean": 120.0},
        evidence_ids=("ev_co2_01", "ev_kw_01"),
    )

    results = harness.run_benchmark(events=[(evt, win)])
    assert "rules" in results
    assert "single_slm" in results
    assert "multi_agent" in results
    assert results["rules"].total_events == 1
    assert results["single_slm"].total_events == 1
    assert results["multi_agent"].total_events == 1
