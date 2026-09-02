"""Multi-Agent & Single-SLM Prompt Engine (Phase 8).

Formats compact JSON inputs into structured prompts for Llama 3.2 3B.
Supports Single-SLM mode and Multi-Agent mode (Domain Experts + Orchestrator).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from smart_city_edge.schemas import Domain, DomainAnalysis


class PromptEngine:
    """Generates structured, evidence-constrained prompts for SLM reasoning."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config = {}
        if config_path:
            path = Path(config_path)
            if path.is_file():
                with open(path, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}

    def build_single_slm_prompt(
        self,
        event_id: str,
        domain_summaries: dict[str, Any],
        evidence_ids: list[str],
        allowed_actions: list[str],
    ) -> str:
        """Format a single SLM prompt containing all domain summaries."""
        system_prompt = (
            "You are a Smart City Root-Cause Reasoning Engine. Analyze all 5 domain summaries "
            "(Energy, Air Quality, Water, Weather, Occupancy) and identify the primary root cause.\n"
            "STRICT RULES:\n"
            "1. Output ONLY valid JSON matching the schema below.\n"
            "2. 'evidence' MUST be a non-empty subset of the provided evidence IDs.\n"
            "3. 'requires_human_approval' MUST be true.\n"
            "4. Do NOT invent actions outside the allowed action list."
        )

        user_content = {
            "event_id": event_id,
            "allowed_actions": allowed_actions,
            "evidence_ids": evidence_ids,
            "domain_summaries": domain_summaries,
            "output_schema": {
                "root_cause": "string",
                "evidence": ["evidence_id"],
                "confidence": 0.95,
                "recommendation": "string",
                "requires_human_approval": True,
                "uncertainties": ["string"],
            },
        }

        return f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{json.dumps(user_content, indent=2)}<|im_end|>\n<|im_start|>assistant\n"

    def build_domain_agent_prompt(
        self,
        domain: Domain | str,
        event_id: str,
        summary: dict[str, Any],
        evidence_ids: list[str],
    ) -> str:
        """Format a domain-specific expert prompt (e.g. Energy, Water, Air Quality)."""
        domain_str = domain.value if isinstance(domain, Domain) else str(domain)
        system_prompt = (
            f"You are a specialized Smart City {domain_str.upper()} Domain Agent. "
            f"Analyze the {domain_str} telemetry and formulate a domain hypothesis.\n"
            "STRICT RULES:\n"
            "1. Output ONLY valid JSON for DomainAnalysis.\n"
            "2. 'evidence' MUST be a non-empty subset of the provided evidence IDs.\n"
            "3. 'confidence' MUST be between 0.0 and 1.0."
        )

        user_content = {
            "event_id": event_id,
            "domain": domain_str,
            "evidence_ids": evidence_ids,
            "domain_summary": summary,
            "output_schema": {
                "event_id": event_id,
                "domain": domain_str,
                "hypothesis": "string hypothesis",
                "evidence": ["evidence_id"],
                "confidence": 0.90,
                "uncertainty": "string uncertainty",
                "recommendation": "string recommendation",
            },
        }

        return f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{json.dumps(user_content, indent=2)}<|im_end|>\n<|im_start|>assistant\n"

    def build_orchestrator_prompt(
        self,
        event_id: str,
        domain_analyses: list[DomainAnalysis | dict[str, Any]],
        evidence_ids: list[str],
        allowed_actions: list[str],
    ) -> str:
        """Format the Cross-Domain Orchestrator prompt that synthesizes domain analyses."""
        system_prompt = (
            "You are the Cross-Domain Orchestrator. Synthesize individual domain hypotheses "
            "(Energy, Air Quality, Water, Weather, Occupancy) into a final RootCauseReport.\n"
            "STRICT RULES:\n"
            "1. Output ONLY valid JSON matching RootCauseReport.\n"
            "2. 'evidence' MUST be a non-empty subset of the provided evidence IDs.\n"
            "3. 'requires_human_approval' MUST be true."
        )

        analyses_data = [
            a.model_dump() if isinstance(a, DomainAnalysis) else a for a in domain_analyses
        ]

        user_content = {
            "event_id": event_id,
            "allowed_actions": allowed_actions,
            "evidence_ids": evidence_ids,
            "domain_analyses": analyses_data,
            "output_schema": {
                "event_id": event_id,
                "root_cause": "string primary root cause",
                "evidence": ["evidence_id"],
                "confidence": 0.95,
                "recommendation": "string recommendation",
                "requires_human_approval": True,
                "uncertainties": ["string uncertainty"],
            },
        }

        return f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{json.dumps(user_content, indent=2)}<|im_end|>\n<|im_start|>assistant\n"
