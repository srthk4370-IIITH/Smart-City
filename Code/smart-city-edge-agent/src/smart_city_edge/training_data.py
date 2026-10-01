"""Canonical, fail-closed feature extraction for historical anomaly training.

Each detector is trained within one physical domain.  Cross-domain reasoning is
performed later on compact event summaries; concatenating unrelated sensor rows
would create fake joint observations.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class DomainSpec:
    domain: str
    filename: str
    fields: tuple[str, ...]
    units: tuple[str, ...]


SPECS = {
    "air_quality": DomainSpec("air_quality", "sr-aq.csv", ("CO2", "Temperature", "Relative Humidity", "PM2.5", "PM10", "Noise", "AQI"), ("ppm", "degC", "%RH", "ug/m3", "ug/m3", "dBA", "AQI")),
    "energy": DomainSpec("energy", "sr-em.csv", ("Power", "Current", "Voltage", "Frequency", "Power Factor"), ("W", "A", "V", "Hz", "ratio")),
    "water": DomainSpec("water", "wm-wf.csv", ("Flowrate", "Total Flow", "Pressure", "Flow Volume", "Flow Time", "Flow Rate"), ("source-defined", "source-defined", "source-defined", "source-defined", "source-defined", "source-defined")),
    "weather": DomainSpec("weather", "we.csv", ("Solar Radiation", "Temperature", "Relative Humidity", "Wind Speed", "Gust Speed", "Dew Point", "Rain", "Pressure"), ("source-defined", "degC", "%RH", "m/s", "m/s", "degC", "source-defined", "source-defined")),
    "occupancy": DomainSpec("occupancy", "sr_oc.csv", ("Occupancy", "Temperature", "Relative Humidity"), ("people", "degC", "%RH")),
}


def _number(value: str | None) -> float:
    if value is None:
        return math.nan
    text = str(value).strip()
    if not text or text.lower() in {"nan", "null", "none", "na", "n/a"}:
        return math.nan
    try:
        result = float(text)
    except ValueError:
        return math.nan
    return result if math.isfinite(result) else math.nan


def _occupancy(value: str | None) -> float:
    direct = _number(value)
    if math.isfinite(direct):
        return direct
    try:
        parsed = json.loads(value or "")
    except json.JSONDecodeError:
        return math.nan
    if not isinstance(parsed, dict):
        return math.nan
    readings = [_number(str(item)) for item in parsed.values()]
    finite = [item for item in readings if math.isfinite(item)]
    return float(sum(finite)) if finite else math.nan


def load_domain_features(data_dir: Path, domain: str, limit: int | None = None) -> tuple[DomainSpec, np.ndarray]:
    """Read source rows in file order, rejecting rows with too little evidence."""
    if domain not in SPECS:
        raise ValueError(f"Unknown domain {domain!r}; choose from {', '.join(SPECS)}")
    spec = SPECS[domain]
    path = data_dir / spec.filename
    if not path.is_file():
        raise FileNotFoundError(f"Missing required source for {domain}: {path}")
    rows: list[list[float]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            values = [(_occupancy(row.get(field)) if domain == "occupancy" and field == "Occupancy" else _number(row.get(field))) for field in spec.fields]
            if sum(math.isfinite(value) for value in values) >= max(2, len(values) // 2):
                rows.append(values)
            if limit and len(rows) >= limit:
                break
    if len(rows) < 100:
        raise ValueError(f"{domain} supplied only {len(rows)} usable rows; need at least 100 after strict parsing.")
    return spec, np.asarray(rows, dtype=np.float32)
