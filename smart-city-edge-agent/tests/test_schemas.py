from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smart_city_edge.schemas import RootCauseReport, SensorRecord


def sensor_payload() -> dict[str, object]:
    return {
        "record_id": "record-001",
        "timestamp": datetime(2026, 8, 20, tzinfo=UTC),
        "building_id": "building-a",
        "zone_id": "zone-1",
        "energy_kw": 4.2,
        "indoor_pm25": 7.1,
        "indoor_co2": 650.0,
        "indoor_temp_c": 23.5,
        "indoor_humidity": 48.0,
        "water_lpm": 2.3,
        "water_pressure_kpa": 240.0,
        "outdoor_temp_c": 30.0,
        "outdoor_humidity": 61.0,
        "wind_mps": 3.0,
        "occupancy_count": 12,
        "hvac_state": "cooling",
        "ventilation_state": "on",
    }


def test_sensor_record_accepts_contract() -> None:
    assert SensorRecord.model_validate(sensor_payload()).occupancy_count == 12


def test_sensor_record_rejects_negative_occupancy() -> None:
    payload = sensor_payload()
    payload["occupancy_count"] = -1
    with pytest.raises(ValidationError):
        SensorRecord.model_validate(payload)


def test_report_requires_human_approval() -> None:
    with pytest.raises(ValidationError):
        RootCauseReport.model_validate(
            {
                "event_id": "evt-1",
                "root_cause": "Ventilation is off during occupancy.",
                "evidence": ["co2.slope"],
                "confidence": 0.8,
                "recommendation": "request_facility_review",
                "requires_human_approval": False,
                "uncertainties": ["No maintenance log was provided."],
            }
        )

