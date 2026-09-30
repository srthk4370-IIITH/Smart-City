"""Policy Gate & Safety Guardrails (Phase 7).

Validates reasoning outputs against safety rules, evidence grounding,
schema constraints, and human-approval requirements.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smart_city_edge.schemas import RootCauseReport


class PolicyValidationResult:

    def __init__(
        self,
        is_valid: bool,
        report: RootCauseReport | None = None,
        rejection_reasons: list[str] | None = None,
        raw_input: Any = None,
    ):
        self.is_valid = is_valid
        self.report = report
        self.rejection_reasons = rejection_reasons or []
        self.raw_input = raw_input

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "report": self.report.model_dump() if self.report else None,
            "rejection_reasons": self.rejection_reasons,
            "raw_input": str(self.raw_input),
        }


class PolicyGate:
    """Enforces safety guardrails, evidence grounding, and human approval for SLM reports."""

    def __init__(self, audit_log_path: Path | str | None = None) -> None:
        self.audit_log_path = Path(audit_log_path) if audit_log_path else None
        if self.audit_log_path:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    def validate(
        self,
        raw_output: str | dict[str, Any],
        known_evidence_ids: set[str] | list[str],
        allowed_actions: list[str] | None = None,
    ) -> PolicyValidationResult:
        """Validate raw LLM JSON against schema, evidence bounds, and safety rules."""
        rejection_reasons: list[str] = []
        known_set = set(known_evidence_ids)

        # 1. JSON Parsing
        data: dict[str, Any]
        if isinstance(raw_output, str):
            try:
                data = json.loads(raw_output)
            except json.JSONDecodeError as err:
                rejection_reasons.append(f"Invalid JSON format: {err}")
                res = PolicyValidationResult(False, None, rejection_reasons, raw_output)
                self._log_audit(res)
                return res
        elif isinstance(raw_output, dict):
            data = raw_output
        else:
            rejection_reasons.append(f"Unexpected input type: {type(raw_output).__name__}")
            res = PolicyValidationResult(False, None, rejection_reasons, raw_output)
            self._log_audit(res)
            return res

        # 2. Schema Validation via RootCauseReport
        report: RootCauseReport | None = None
        try:
            report = RootCauseReport.model_validate(data)
        except ValidationError as val_err:
            for error in val_err.errors():
                loc = ".".join(str(e) for e in error["loc"])
                rejection_reasons.append(f"Schema violation at '{loc}': {error['msg']}")

        if report is None:
            res = PolicyValidationResult(False, None, rejection_reasons, raw_output)
            self._log_audit(res)
            return res

        # 3. Safety Check: requires_human_approval must be True
        if not report.requires_human_approval:
            rejection_reasons.append("Safety violation: requires_human_approval must be True")

        # 4. Evidence Grounding Check: All cited evidence must exist in known_evidence_ids
        for ev in report.evidence:
            if ev not in known_set:
                rejection_reasons.append(f"Evidence grounding violation: '{ev}' is not in valid evidence set")

        # 5. Allowed Action Check (if provided)
        if allowed_actions is not None:
            rec_lower = report.recommendation.lower()
            allowed_set = {a.lower() for a in allowed_actions}
            # Verify if recommendation specifies an explicit action outside allowed_set
            if any(forbidden in rec_lower for forbidden in ["actuate", "override", "shut off", "lock"]) and not any(
                a in rec_lower for a in allowed_set
            ):
                rejection_reasons.append(f"Action restriction violation: Recommendation contains unauthorized action")

        is_valid = len(rejection_reasons) == 0
        res = PolicyValidationResult(
            is_valid=is_valid,
            report=report if is_valid else None,
            rejection_reasons=rejection_reasons,
            raw_input=raw_output,
        )
        self._log_audit(res)
        return res

    def _log_audit(self, result: PolicyValidationResult) -> None:
        if not self.audit_log_path:
            return
        try:
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result.to_dict()) + "\n")
        except IOError:
            pass
