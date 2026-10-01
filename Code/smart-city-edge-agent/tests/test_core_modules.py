"""Unit tests for PolicyGate (Phase 7), PromptEngine (Phase 8), and GenieRunner (Phase 9)."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from smart_city_edge.genie_runner import GenieExecutionResult, GenieRunner
from smart_city_edge.policy import PolicyGate
from smart_city_edge.prompts import PromptEngine
from smart_city_edge.schemas import Domain, DomainAnalysis, RootCauseReport


def test_policy_gate_valid_report():
    with TemporaryDirectory() as tmp_dir:
        audit_file = Path(tmp_dir) / "audit.jsonl"
        gate = PolicyGate(audit_log_path=audit_file)

        valid_payload = {
            "event_id": "evt_001",
            "root_cause": "Cooling valve fault causing thermal drift",
            "evidence": ["ev_temp_01", "ev_kw_01"],
            "confidence": 0.95,
            "recommendation": "Inspect valve actuator",
            "requires_human_approval": True,
            "uncertainties": ["Minor sensor noise"],
        }

        res = gate.validate(
            raw_output=json.dumps(valid_payload),
            known_evidence_ids={"ev_temp_01", "ev_kw_01", "ev_co2_01"},
        )

        assert res.is_valid is True
        assert res.report is not None
        assert res.report.event_id == "evt_001"
        assert len(res.rejection_reasons) == 0
        assert audit_file.exists()


def test_policy_gate_rejection_ungrounded_evidence():
    gate = PolicyGate()

    invalid_payload = {
        "event_id": "evt_002",
        "root_cause": "Unknown failure",
        "evidence": ["ev_hallucinated_099"],
        "confidence": 0.90,
        "recommendation": "Inspect area",
        "requires_human_approval": True,
        "uncertainties": ["None"],
    }

    res = gate.validate(
        raw_output=json.dumps(invalid_payload),
        known_evidence_ids={"ev_temp_01", "ev_kw_01"},
    )

    assert res.is_valid is False
    assert any("grounding violation" in r for r in res.rejection_reasons)


def test_policy_gate_rejection_safety_approval_false():
    gate = PolicyGate()

    invalid_payload = {
        "event_id": "evt_003",
        "root_cause": "Water pressure spike",
        "evidence": ["ev_press_01"],
        "confidence": 0.85,
        "recommendation": "Trigger emergency valve shutoff",
        "requires_human_approval": False,  # Should fail safety gate
        "uncertainties": ["None"],
    }

    res = gate.validate(
        raw_output=invalid_payload,
        known_evidence_ids={"ev_press_01"},
    )

    assert res.is_valid is False


def test_prompt_engine_single_slm():
    engine = PromptEngine()
    prompt = engine.build_single_slm_prompt(
        event_id="evt_100",
        domain_summaries={"energy": {"kw_mean": 45.2}},
        evidence_ids=["ev_1"],
        allowed_actions=["inspect_valve"],
    )

    assert "evt_100" in prompt
    assert "Single-SLM" in prompt or "all 5 domain summaries" in prompt
    assert "<|im_start|>" in prompt


def test_prompt_engine_domain_agent_and_orchestrator():
    engine = PromptEngine()

    domain_prompt = engine.build_domain_agent_prompt(
        domain=Domain.ENERGY,
        event_id="evt_101",
        summary={"energy_kw": 50.0},
        evidence_ids=["ev_kw_1"],
    )
    assert "ENERGY" in domain_prompt

    analysis = DomainAnalysis(
        event_id="evt_101",
        domain=Domain.ENERGY,
        hypothesis="HVAC over-consumption",
        evidence=("ev_kw_1",),
        confidence=0.88,
        uncertainty="Noise",
        recommendation="Check schedule",
    )

    orch_prompt = engine.build_orchestrator_prompt(
        event_id="evt_101",
        domain_analyses=[analysis],
        evidence_ids=["ev_kw_1"],
        allowed_actions=["inspect"],
    )
    assert "Cross-Domain Orchestrator" in orch_prompt


def test_genie_runner_mock_execution():
    runner = GenieRunner(use_mock_fallback=True)
    res = runner.run_prompt("Test prompt for root_cause reasoning")

    assert res.exit_code == 0
    assert res.latency_ms > 0
    parsed = res.extract_json()
    assert parsed is not None
    assert "root_cause" in parsed
