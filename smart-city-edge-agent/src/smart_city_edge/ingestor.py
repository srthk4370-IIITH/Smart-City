"""SCRC IHub Dataset Ingestion & Streaming Adapter (Phase 5 & 6).

Streams and parses the raw CSV datasets from 'SCRC-IHub-Data Collection'
(aq, em, sl, sr_ac, sr_aq, sr_em, sr_oc, we, wm-wd, wm-wf, wm-wl, wn)
into unified SensorRecord and FeatureWindow objects.
"""

from __future__ import annotations

import csv
import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from smart_city_edge.schemas import SensorRecord


class SCRCIHubIngestor:
    """High-throughput chunked reader for SCRC-IHub CSV data files."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            # Check standard workspace paths
            possible_paths = [
                Path(__file__).parents[3] / "SCRC-IHub-Data",
                Path(__file__).parents[3] / "SCRC-IHub-Data Collection",
                Path(__file__).parents[2] / "SCRC-IHub-Data",
                Path(__file__).parents[2] / "SCRC-IHub-Data Collection",
                Path("/home/rishit-nanda/Documents/esw/SCRC-IHub-Data"),
                Path("/home/rishit-nanda/Documents/esw/SCRC-IHub-Data Collection"),
            ]
            self.data_dir = next((p for p in possible_paths if p.is_dir()), possible_paths[0])

    def read_aq_csv(
        self, limit: int | None = None
    ) -> Generator[dict[str, Any], None, None]:
        """Stream parsed records from aq.csv (Air Quality)."""
        file_path = self.data_dir / "aq.csv"
        if not file_path.is_file():
            return

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                parsed = self._parse_aq_row(row)
                if parsed:
                    yield parsed
                    count += 1
                    if limit and count >= limit:
                        break

    def read_wf_csv(
        self, limit: int | None = None
    ) -> Generator[dict[str, Any], None, None]:
        """Stream parsed records from wm-wf.csv (Water Flow)."""
        file_path = self.data_dir / "wm-wf.csv"
        if not file_path.is_file():
            return

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                parsed = self._parse_generic_row(row, domain_type="water_flow")
                if parsed:
                    yield parsed
                    count += 1
                    if limit and count >= limit:
                        break

    def read_em_csv(
        self, limit: int | None = None
    ) -> Generator[dict[str, Any], None, None]:
        """Stream parsed records from em.csv (Energy Meters)."""
        file_path = self.data_dir / "em.csv"
        if not file_path.is_file():
            return

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                parsed = self._parse_generic_row(row, domain_type="energy")
                if parsed:
                    yield parsed
                    count += 1
                    if limit and count >= limit:
                        break

    def _parse_aq_row(self, row: dict[str, str]) -> dict[str, Any] | None:
        """Parse raw row from aq.csv into structured dict."""
        try:
            node_id = row.get("Node_id", "").strip()
            ts_str = row.get("Timestamp", "").strip()
            data_str = row.get("data", "").strip()

            if not node_id or not ts_str or not data_str:
                return None

            dt = self._parse_timestamp(ts_str)
            raw_vals = ast.literal_eval(data_str) if data_str.startswith("[") else []
            vals = [self._safe_float(v) for v in raw_vals]

            # Indexing according to meta data.xlsx for aq.csv:
            # val[1]: PM2.5, val[3]: PM10, val[5]: Temp, val[7]: Humidity
            pm25 = vals[1] if len(vals) > 1 else 0.0
            pm10 = vals[3] if len(vals) > 3 else 0.0
            temp = vals[5] if len(vals) > 5 else 25.0
            humidity = vals[7] if len(vals) > 7 else 50.0

            return {
                "record_id": f"rec_aq_{row.get('id', '0')}",
                "timestamp": dt,
                "building_id": node_id.split("-")[1] if "-" in node_id else "Campus",
                "zone_id": node_id,
                "indoor_pm25": max(0.0, pm25),
                "indoor_co2": max(0.0, pm10 * 10.0),  # Derived/proxy for CO2 if unavailable
                "indoor_temp_c": temp,
                "indoor_humidity": min(100.0, max(0.0, humidity)),
            }
        except Exception:
            return None

    def _parse_generic_row(self, row: dict[str, str], domain_type: str) -> dict[str, Any] | None:
        """Parse generic CSV row into key-value structure."""
        try:
            node_id = row.get("Node_id", row.get("node_id", "Campus")).strip()
            ts_str = row.get("Timestamp", row.get("timestamp", "")).strip()
            dt = self._parse_timestamp(ts_str) if ts_str else datetime.now(timezone.utc)

            return {
                "node_id": node_id,
                "timestamp": dt,
                "domain_type": domain_type,
                "raw_fields": {k: self._safe_float(v) for k, v in row.items() if k not in ("Node_id", "Timestamp", "id")},
            }
        except Exception:
            return None

    @staticmethod
    def _parse_timestamp(ts_str: str) -> datetime:
        try:
            if ts_str.isdigit():
                return datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
            return datetime.fromisoformat(ts_str)
        except Exception:
            return datetime.now(timezone.utc)

    @staticmethod
    def _safe_float(val: Any) -> float:
        if val is None:
            return 0.0
        try:
            s = str(val).strip().replace("°C", "").replace("%", "").replace("µg/m³", "").replace("ppm", "").replace("m³/h", "").replace("m³", "")
            return float(s)
        except (ValueError, TypeError):
            return 0.0
