"""Generate the tiny C++ policy header used by the QIDK smoke runner."""
from __future__ import annotations
import argparse, json
from pathlib import Path

def floats(items): return ", ".join(f"{float(item):.9g}f" for item in items)
def strings(items): return ", ".join(json.dumps(str(item)) for item in items)
def nodes(items): return ",\n  ".join("{" + f"{node['left']}, {node['right']}, {node['feature']}, {float(node['threshold']):.9g}f, {{{floats(node['value'])}}}" + "}" for node in items)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--policy", type=Path, default=Path("models/bootstrap/edge_policy.json")); parser.add_argument("--output", type=Path, default=Path("qidk_runtime/generated/edge_policy.h")); args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8")); agent, orch = policy["agent_tree"], policy["orchestrator_tree"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    text = "#pragma once\nnamespace bootstrap {\nstruct Node { int left; int right; int feature; float threshold; float votes[8]; };\n"
    text += f"constexpr int kFeatureCount={len(policy['feature_order'])}; constexpr float kAgentImpute[]={{ {floats(agent['imputation'])} }}; constexpr float kOrchestratorImpute[]={{ {floats(orch['imputation'])} }};\n"
    text += f"constexpr const char* kAgentClasses[]={{ {strings(agent['classes'])} }}; constexpr const char* kPlanClasses[]={{ {strings(orch['classes'])} }};\n"
    text += f"constexpr int kAgentNodeCount={len(agent['nodes'])}; constexpr int kOrchestratorNodeCount={len(orch['nodes'])};\nconstexpr Node kAgentNodes[]={{\n  {nodes(agent['nodes'])}\n}};\nconstexpr Node kOrchestratorNodes[]={{\n  {nodes(orch['nodes'])}\n}};\n}}\n"
    args.output.write_text(text, encoding="utf-8"); print(f"Wrote {args.output}")
