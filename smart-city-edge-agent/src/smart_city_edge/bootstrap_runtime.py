"""SDK-independent runtime for the trained bootstrap agent/orchestrator.

This can be translated directly to Kotlin/C++ on QIDK because it evaluates a
small JSON decision tree and does not depend on sklearn, Python, or an LLM.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class BootstrapRuntime:
    def __init__(self, policy_path: Path | str) -> None:
        self.policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
        self.feature_order: list[str] = self.policy["feature_order"]

    @staticmethod
    def _tree_predict(tree: dict[str, Any], values: list[float]) -> tuple[str, float]:
        inputs = [tree["imputation"][i] if not math.isfinite(value) else value for i, value in enumerate(values)]
        node = 0
        while tree["nodes"][node]["left"] != -1:
            current = tree["nodes"][node]
            node = current["left"] if inputs[current["feature"]] <= current["threshold"] else current["right"]
        votes = tree["nodes"][node]["value"]
        total = sum(votes)
        winner = max(range(len(votes)), key=lambda index: votes[index])
        return tree["classes"][winner], (votes[winner] / total if total else 0.0)

    def run(self, measurements: dict[str, float]) -> dict[str, Any]:
        values = [float(measurements.get(name, math.nan)) for name in self.feature_order]
        agent_label, agent_confidence = self._tree_predict(self.policy["agent_tree"], values)
        agent_code = self.policy["agent_class_order"].index(agent_label)
        plan, plan_confidence = self._tree_predict(self.policy["orchestrator_tree"], values + [float(agent_code)])
        evidence = [{"field": name, "value": measurements.get(name), "source": "air_quality_agent"} for name in self.feature_order if measurements.get(name) is not None]
        return {"agent": "air_quality", "agent_triage": agent_label, "agent_confidence": round(agent_confidence, 4), "orchestration_plan": plan, "agents_in_order": self.policy["plans"][plan], "black_box_reasoner_input": {"allowed_fields": self.policy["allowed_forwarded_fields"], "agent_triage": agent_label, "agent_confidence": round(agent_confidence, 4), "plan_confidence": round(plan_confidence, 4), "evidence": evidence, "root_cause": None, "requires_human_approval": True}}
