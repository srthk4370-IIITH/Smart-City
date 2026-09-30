"""Versioned, strict interchange contracts shared by replay and reasoning modes."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Domain(StrEnum):
    ENERGY = "energy"
    AIR_QUALITY = "air_quality"
    WATER = "water"
    WEATHER = "weather"
    OCCUPANCY = "occupancy"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SensorRecord(StrictModel):
    """A synchronised sensor observation; labels must live outside this contract."""

    record_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    building_id: str = Field(min_length=1, max_length=64)
    zone_id: str = Field(min_length=1, max_length=64)
    energy_kw: float = Field(ge=0)
    indoor_pm25: float = Field(ge=0)
    indoor_co2: float = Field(ge=0)
    indoor_temp_c: float
    indoor_humidity: float = Field(ge=0, le=100)
    water_lpm: float = Field(ge=0)
    water_pressure_kpa: float = Field(ge=0)
    outdoor_temp_c: float
    outdoor_humidity: float = Field(ge=0, le=100)
    wind_mps: float = Field(ge=0)
    occupancy_count: int = Field(ge=0)
    hvac_state: Literal["off", "heating", "cooling", "ventilating", "unknown"]
    ventilation_state: Literal["off", "on", "unknown"]
    schema_version: Literal["1.0"] = "1.0"


class FeatureWindow(StrictModel):
    window_id: str = Field(min_length=1)
    building_id: str = Field(min_length=1)
    zone_id: str = Field(min_length=1)
    start: datetime
    end: datetime
    feature_order: tuple[str, ...] = Field(min_length=1)
    features: dict[str, float]
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("features")
    @classmethod
    def finite_features(cls, features: dict[str, float]) -> dict[str, float]:
        if not features:
            raise ValueError("features cannot be empty")
        return features


class AnomalyEvent(StrictModel):
    event_id: str = Field(min_length=1)
    timestamp: datetime
    building_id: str = Field(min_length=1)
    zone_id: str = Field(min_length=1)
    domains: tuple[Domain, ...] = Field(min_length=1)
    trigger_sources: tuple[Literal["rule", "anomaly_model"], ...] = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"]
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    anomaly_score: float | None = Field(default=None, ge=0)


class DomainAnalysis(StrictModel):
    event_id: str = Field(min_length=1)
    domain: Domain
    hypothesis: str = Field(min_length=1, max_length=500)
    evidence: tuple[str, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    uncertainty: str = Field(min_length=1, max_length=500)
    recommendation: str = Field(min_length=1, max_length=500)


class RootCauseReport(StrictModel):
    event_id: str = Field(min_length=1)
    root_cause: str = Field(min_length=1, max_length=500)
    evidence: tuple[str, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    recommendation: str = Field(min_length=1, max_length=500)
    requires_human_approval: Literal[True] = True
    uncertainties: tuple[str, ...] = Field(min_length=1)

