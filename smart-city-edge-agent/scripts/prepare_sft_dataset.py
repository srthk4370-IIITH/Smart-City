"""Turn human-approved incident labels plus replay evidence into SFT JSONL.

This script never generates diagnoses.  It merely binds an approved label to
the immutable evidence snapshot that the model will see during training.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ALLOWED_ACTIONS = {"inspect_hvac", "inspect_ventilation", "inspect_water_system", "request_facility_review"}
SYSTEM = ("You are a bounded smart-city diagnostic assistant. Return JSON only. "
          "Treat causes as hypotheses, cite only supplied evidence IDs, never control equipment, "
          "and set requires_human_approval to true.")


def read_jsonl(path: Path) -> list[dict]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try: records.append(json.loads(line))
            except json.JSONDecodeError as exc: raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
    return records


def event_index(records: list[dict]) -> dict[str, dict]:
    indexed = {}
    for record in records:
        event = record.get("event", record)
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("Every replay record needs event.event_id")
        if event_id in indexed: raise ValueError(f"Duplicate event_id: {event_id}")
        evidence = event.get("evidence_ids") or record.get("evidence_ids")
        if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
            raise ValueError(f"{event_id}: evidence_ids must be a string list")
        indexed[event_id] = record
    return indexed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True, help="Five-domain replay/event JSONL")
    parser.add_argument("--labels", type=Path, required=True, help="Human-approved incident labels JSONL")
    parser.add_argument("--output", type=Path, default=Path("data/processed/sft/incidents.jsonl"))
    args = parser.parse_args()
    events = event_index(read_jsonl(args.events)); labels = read_jsonl(args.labels)
    prepared = []
    seen = set()
    for label in labels:
        required = {"event_id", "split", "root_cause", "evidence_ids", "confidence", "recommendation", "uncertainties", "annotator_id", "label_version"}
        missing = required - label.keys()
        if missing: raise ValueError(f"label missing fields: {sorted(missing)}")
        event_id = label["event_id"]
        if event_id in seen: raise ValueError(f"duplicate label for {event_id}")
        seen.add(event_id)
        if event_id not in events: raise ValueError(f"label {event_id} has no immutable replay event")
        if label["split"] not in {"train", "dev", "test"}: raise ValueError(f"{event_id}: invalid split")
        if label["recommendation"] not in ALLOWED_ACTIONS: raise ValueError(f"{event_id}: unsafe/unapproved recommendation")
        if not isinstance(label["root_cause"], str) or not label["root_cause"].strip(): raise ValueError(f"{event_id}: root_cause must be non-empty")
        if not isinstance(label["confidence"], (int, float)) or not 0 <= label["confidence"] <= 1: raise ValueError(f"{event_id}: confidence must be in [0, 1]")
        if not isinstance(label["uncertainties"], list) or not label["uncertainties"]: raise ValueError(f"{event_id}: uncertainties required")
        event = events[event_id]; event_payload = event.get("event", event); known = set(event_payload.get("evidence_ids", event.get("evidence_ids", [])))
        cited = label["evidence_ids"]
        if not cited or not set(cited) <= known: raise ValueError(f"{event_id}: label cites unavailable evidence")
        user_payload = {"event": event_payload, "window": event.get("window"), "domain_summaries": event.get("domain_summaries"), "allowed_actions": sorted(ALLOWED_ACTIONS)}
        assistant_payload = {"event_id": event_id, "root_cause": label["root_cause"], "evidence": cited, "confidence": label["confidence"], "recommendation": label["recommendation"], "requires_human_approval": True, "uncertainties": label["uncertainties"]}
        prepared.append({"event_id": event_id, "split": label["split"], "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(user_payload, separators=(",", ":"), sort_keys=True)}, {"role": "assistant", "content": json.dumps(assistant_payload, separators=(",", ":"), sort_keys=True)}], "label_version": label["label_version"]})
    if not prepared: raise ValueError("No labels supplied")
    if not any(row["split"] == "train" for row in prepared) or not any(row["split"] == "dev" for row in prepared) or not any(row["split"] == "test" for row in prepared):
        raise ValueError("Need explicit train, dev, and test labels; never evaluate on training incidents.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in prepared: handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(f"Prepared {len(prepared)} examples; sha256={digest}; output={args.output}")


if __name__ == "__main__": main()
