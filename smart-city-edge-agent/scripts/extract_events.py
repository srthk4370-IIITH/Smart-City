"""Stream SCRC-IHub dataset and extract AnomalyEvent evaluation windows (Task 2).

Streams telemetry rows from SCRC-IHub CSV datasets, evaluates them through
RuleEngine & AnomalyScorer, and streams results directly to disk (no RAM buffering).
Supports full dataset mode or sample limit mode.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from smart_city_edge.anomaly_model import AnomalyScorer
from smart_city_edge.ingestor import SCRCIHubIngestor
from smart_city_edge.rules import RuleEngine
from smart_city_edge.schemas import FeatureWindow
from smart_city_edge.topology import TopologyRegistry


def extract_scrc_events(
    data_dir: Path | str | None = None,
    output_file: Path | str | None = None,
    limit: int | None = 1000,
) -> Path:
    """Stream dataset, evaluate rules/autoencoder, and stream-write AnomalyEvents to disk."""
    print("Initializing SCRC-IHub Ingestor, RuleEngine & AnomalyScorer...")
    ingestor = SCRCIHubIngestor(data_dir=data_dir)
    rule_engine = RuleEngine()
    scorer = AnomalyScorer(threshold=0.1)

    out_path = Path(output_file) if output_file else Path(__file__).parents[1] / "data" / "processed" / "scrc_events.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    total_events = 0
    limit_str = f"limit={limit:,}" if limit else "FULL DATASET"

    # Stream-write directly to avoid RAM exhaustion on large datasets
    with open(out_path, "w", encoding="utf-8") as out_f:

        # --- Air Quality ---
        print(f"Ingesting Air Quality records from aq.csv ({limit_str})...")
        count = 0
        for rec in ingestor.read_aq_csv(limit=limit):
            count += 1
            building = rec.get("building_id", "Campus")
            zone = rec.get("zone_id", "Zone_1")
            co2 = rec.get("indoor_co2", 400.0)
            pm25 = rec.get("indoor_pm25", 15.0)

            win = FeatureWindow(
                window_id=f"win_aq_{count}",
                building_id=building,
                zone_id=zone,
                start=rec.get("timestamp", now),
                end=rec.get("timestamp", now),
                feature_order=("indoor_co2_mean", "indoor_pm25_mean"),
                features={"indoor_co2_mean": float(co2), "indoor_pm25_mean": float(pm25)},
                evidence_ids=(f"ev_aq_co2_{count}", f"ev_aq_pm25_{count}"),
            )

            evt, rule_report = rule_engine.evaluate_window(win)
            if evt:
                record = {
                    "event": evt.model_dump(mode="json"),
                    "report": rule_report.model_dump(mode="json") if rule_report else None,
                    "window": win.model_dump(mode="json"),
                }
                out_f.write(json.dumps(record) + "\n")
                total_events += 1
                if total_events % 10_000 == 0:
                    out_f.flush()
                    print(f"  ... {total_events:,} events written")

        # --- Water Flow ---
        print(f"Ingesting Water Flow records from wm-wf.csv ({limit_str})...")
        wf_count = 0
        for rec in ingestor.read_wf_csv(limit=limit):
            wf_count += 1
            node = rec.get("node_id", "WF-Node")
            rf = rec.get("raw_fields", {})
            flowrate = rf.get("Flowrate", 0.0)
            pressure = rf.get("Pressure", 0.0)

            win = FeatureWindow(
                window_id=f"win_wf_{wf_count}",
                building_id="Water_Distribution",
                zone_id=node,
                start=rec.get("timestamp", now),
                end=rec.get("timestamp", now),
                feature_order=("water_flowrate_mean", "water_pressure_max"),
                features={"water_flowrate_mean": float(flowrate), "water_pressure_max": float(pressure)},
                evidence_ids=(f"ev_wf_flow_{wf_count}", f"ev_wf_press_{wf_count}"),
            )

            evt, rule_report = rule_engine.evaluate_window(win)
            if evt:
                record = {
                    "event": evt.model_dump(mode="json"),
                    "report": rule_report.model_dump(mode="json") if rule_report else None,
                    "window": win.model_dump(mode="json"),
                }
                out_f.write(json.dumps(record) + "\n")
                total_events += 1
                if total_events % 10_000 == 0:
                    out_f.flush()
                    print(f"  ... {total_events:,} events written")

    print(f"\nTotal Anomaly Events extracted: {total_events:,}")
    print(f"Saved to: {out_path}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Anomaly Evaluation Events from SCRC-IHub dataset")
    parser.add_argument("--full", action="store_true", help="Extract from full dataset without sample limit")
    parser.add_argument("--limit", type=int, default=5000, help="Rows per CSV file (default: 5000)")
    args = parser.parse_args()

    limit = None if args.full else args.limit
    extract_scrc_events(limit=limit)
