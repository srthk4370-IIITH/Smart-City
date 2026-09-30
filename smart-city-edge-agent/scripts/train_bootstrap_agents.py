"""Train an Air Quality agent and a routing-only orchestrator from sr-aq.csv.

The generated labels are explicit trigger-policy labels, not root-cause labels.
The trained orchestrator only selects an ordered agent plan and a safe evidence
package for a future black-box reasoning model.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

FEATURE_TO_COLUMN = {"co2_ppm": "CO2", "temperature_c": "Temperature", "relative_humidity_pct": "Relative Humidity", "pm25_ug_m3": "PM2.5", "pm10_ug_m3": "PM10", "aqi": "AQI"}
TRIAGE_TO_PLAN = {"air_nominal": "no_call", "co2_elevated": "air_then_occupancy_energy_weather", "pm25_elevated": "air_then_weather", "co2_and_pm25_elevated": "air_then_weather_occupancy_energy"}


def number(value: str | None) -> float:
    try:
        item = float(str(value).strip())
        return item if math.isfinite(item) else math.nan
    except (TypeError, ValueError):
        return math.nan


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_source(path: Path, feature_order: list[str], limit: int) -> tuple[np.ndarray, list[int]]:
    rows: list[tuple[int, list[float]]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            timestamp = number(row.get("Timestamp"))
            values = [number(row.get(FEATURE_TO_COLUMN[field])) for field in feature_order]
            if math.isfinite(timestamp) and math.isfinite(values[0]):
                rows.append((int(timestamp), values))
            if limit and len(rows) >= limit:
                break
    if len(rows) < 500:
        raise ValueError(f"Need 500 valid rows with measured CO2; got {len(rows)}")
    rows.sort(key=lambda item: item[0])
    return np.array([item[1] for item in rows], dtype=np.float32), [item[0] for item in rows]


def label(row: np.ndarray, policy: dict[str, float]) -> str:
    co2, pm25 = float(row[0]), float(row[3])
    elevated_co2 = math.isfinite(co2) and co2 >= policy["co2_ppm"]
    elevated_pm25 = math.isfinite(pm25) and pm25 >= policy["pm25_ug_m3"]
    if elevated_co2 and elevated_pm25: return "co2_and_pm25_elevated"
    if elevated_co2: return "co2_elevated"
    if elevated_pm25: return "pm25_elevated"
    return "air_nominal"


def export_onnx(model, feature_name: str, width: int, destination: Path) -> None:
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType
    destination.write_bytes(convert_sklearn(model, initial_types=[(feature_name, FloatTensorType([None, width]))], target_opset=17).SerializeToString())


def edge_tree(model) -> dict:
    """Serialize a sklearn tree to an SDK-independent JSON evaluator contract."""
    tree = model.named_steps["tree"].tree_
    classes = [str(item) for item in model.named_steps["tree"].classes_]
    return {"imputation": [float(item) for item in model.named_steps["impute"].statistics_], "classes": classes, "nodes": [{"left": int(tree.children_left[i]), "right": int(tree.children_right[i]), "feature": int(tree.feature[i]), "threshold": float(tree.threshold[i]), "value": [float(item) for item in tree.value[i][0]]} for i in range(tree.node_count)]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/training/bootstrap_air_orchestrator.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("models/bootstrap"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    try:
        import joblib
        from sklearn.impute import SimpleImputer
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.pipeline import Pipeline
        from sklearn.tree import DecisionTreeClassifier
    except ImportError as exc:
        raise SystemExit("Install requirements-training.txt in supported Python 3.10-3.12 first.") from exc
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    source = args.data_dir / cfg["source_file"]
    if not source.is_file(): raise SystemExit(f"Missing training source: {source}")
    X, timestamps = load_source(source, cfg["feature_order"], args.limit or cfg["sample_limit"])
    y_agent = np.array([label(row, cfg["bootstrap_trigger_policy"]) for row in X])
    y_plan = np.array([TRIAGE_TO_PLAN[value] for value in y_agent])
    n = len(X); train_end, dev_end = int(n * .70), int(n * .85)
    if len(set(y_agent[:train_end])) < 2:
        raise SystemExit("Training period has one trigger class. Increase --limit or obtain more varied history.")
    # Fixed-width constant imputation is deliberate: every runtime (Python,
    # ONNX, and QIDK C++) must receive exactly the same six-feature contract.
    agent = Pipeline([("impute", SimpleImputer(strategy="constant", fill_value=0.0, keep_empty_features=True)), ("tree", DecisionTreeClassifier(max_depth=5, min_samples_leaf=30, class_weight="balanced", random_state=cfg["seed"]))])
    agent.fit(X[:train_end], y_agent[:train_end])
    predicted_agent = agent.predict(X)
    classes = sorted(set(y_agent))
    agent_code = np.array([classes.index(value) for value in predicted_agent], dtype=np.float32).reshape(-1, 1)
    X_orchestrator = np.concatenate((X, agent_code), axis=1)
    orchestrator = Pipeline([("impute", SimpleImputer(strategy="constant", fill_value=0.0, keep_empty_features=True)), ("tree", DecisionTreeClassifier(max_depth=5, min_samples_leaf=30, class_weight="balanced", random_state=cfg["seed"]))])
    orchestrator.fit(X_orchestrator[:train_end], y_plan[:train_end])
    output = args.output_dir; output.mkdir(parents=True, exist_ok=True)
    joblib.dump(agent, output / "air_quality_agent.joblib"); joblib.dump(orchestrator, output / "orchestrator.joblib")
    export_onnx(agent, "sensor_features", X.shape[1], output / "air_quality_agent.onnx")
    export_onnx(orchestrator, "orchestrator_features", X_orchestrator.shape[1], output / "orchestrator.onnx")
    (output / "edge_policy.json").write_text(json.dumps({"contract_version": "1.0", "feature_order": cfg["feature_order"], "agent_class_order": classes, "plans": cfg["plans"], "allowed_forwarded_fields": cfg["reasoning_contract"]["allowed_forwarded_fields"], "agent_tree": edge_tree(agent), "orchestrator_tree": edge_tree(orchestrator)}, indent=2) + "\n", encoding="utf-8")
    metrics = {}
    for split, start, end in (("train", 0, train_end), ("dev", train_end, dev_end), ("test", dev_end, n)):
        agent_out, plan_out = agent.predict(X[start:end]), orchestrator.predict(X_orchestrator[start:end])
        metrics[split] = {"samples": end-start, "agent_accuracy": float(accuracy_score(y_agent[start:end], agent_out)), "agent_macro_f1": float(f1_score(y_agent[start:end], agent_out, average="macro", zero_division=0)), "orchestrator_accuracy": float(accuracy_score(y_plan[start:end], plan_out)), "orchestrator_macro_f1": float(f1_score(y_plan[start:end], plan_out, average="macro", zero_division=0))}
    corpus = output / "bootstrap_air_routing_corpus.jsonl"
    with corpus.open("w", encoding="utf-8") as handle:
        for index, (row, stamp) in enumerate(zip(X, timestamps)):
            triage_label, plan = str(y_agent[index]), str(y_plan[index])
            measurements = {name: None if not math.isfinite(float(value)) else round(float(value), 4) for name, value in zip(cfg["feature_order"], row)}
            record = {"event_id": f"air_{stamp}_{index}", "timestamp_unix": stamp, "split": "train" if index < train_end else "dev" if index < dev_end else "test", "measurements": measurements, "agent_label": triage_label, "orchestration_plan": plan, "agents_in_order": cfg["plans"][plan], "black_box_payload": {"evidence_fields": cfg["reasoning_contract"]["allowed_forwarded_fields"], "root_cause_label": None, "note": "Operational policy label; no causal diagnosis."}}
            handle.write(json.dumps(record) + "\n")
    metadata = {"artifact_version": "1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(), "source_file": source.name, "source_sha256": file_hash(source), "source_rows": n, "feature_order": cfg["feature_order"], "agent_classes": classes, "plans": cfg["plans"], "bootstrap_trigger_policy": cfg["bootstrap_trigger_policy"], "class_counts": dict(Counter(y_agent)), "split": "chronological_70_15_15", "metrics": metrics, "limits": ["Metrics measure imitation of the configured operational routing policy, not root-cause accuracy.", "No reasoning model was trained or invoked.", "Models require QAIRT/QNN validation before QIDK deployment."]}
    (output / "training_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Success: trained Air Quality agent + orchestrator from {n} rows into {output}")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__": main()
