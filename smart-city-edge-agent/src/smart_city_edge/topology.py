"""Campus Topology Registry (Phase 4).

Parses real-time node snapshots (e.g. data/raw/latest.json) to map node IDs
to campus building/zone locations, geolocations, and domain categories.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smart_city_edge.schemas import Domain


@dataclass
class NodeMetadata:
    node_id: str
    name: str
    category: str
    domain: Domain
    latitude: float | None = None
    longitude: float | None = None
    xcor: float | None = None
    ycor: float | None = None
    raw_properties: dict[str, Any] | None = None


CATEGORY_TO_DOMAIN: dict[str, Domain] = {
    "aq": Domain.AIR_QUALITY,
    "wf": Domain.WATER,
    "wd": Domain.WATER,
    "em": Domain.ENERGY,
    "sl": Domain.ENERGY,
    "sr": Domain.WEATHER,
    "wn": Domain.OCCUPANCY,  # Wireless network nodes act as occupancy/presence proxy
}


class TopologyRegistry:
    """Indexed directory of IIIT-H campus smart city nodes."""

    def __init__(self, snapshot_path: Path | str | None = None) -> None:
        self.nodes_by_id: dict[str, NodeMetadata] = {}
        self.nodes_by_category: dict[str, list[NodeMetadata]] = {}
        if snapshot_path:
            self.load_snapshot(snapshot_path)

    def load_snapshot(self, path: Path | str) -> int:
        """Load and index nodes from a snapshot JSON file (e.g. latest.json)."""
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError(f"Topology snapshot file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        count = 0
        if isinstance(data, dict):
            for cat_key, node_list in data.items():
                if not isinstance(node_list, list):
                    continue
                cat_clean = cat_key.lower()
                domain = CATEGORY_TO_DOMAIN.get(cat_clean, Domain.ENERGY)

                for item in node_list:
                    if not isinstance(item, dict):
                        continue
                    node_id = item.get("node_id") or item.get("id")
                    if not node_id:
                        continue

                    node_meta = NodeMetadata(
                        node_id=str(node_id),
                        name=str(item.get("name", node_id)),
                        category=cat_clean,
                        domain=domain,
                        latitude=self._safe_float(item.get("latitude")),
                        longitude=self._safe_float(item.get("longitude")),
                        xcor=self._safe_float(item.get("xcor")),
                        ycor=self._safe_float(item.get("ycor")),
                        raw_properties=item,
                    )

                    self.nodes_by_id[node_meta.node_id] = node_meta
                    self.nodes_by_category.setdefault(cat_clean, []).append(node_meta)
                    count += 1

        return count

    def get_node(self, node_id: str) -> NodeMetadata | None:
        """Lookup node metadata by node ID."""
        return self.nodes_by_id.get(node_id)

    def get_nodes_by_category(self, category: str) -> list[NodeMetadata]:
        """Return all nodes matching a category (e.g., 'aq', 'wf', 'wd')."""
        return self.nodes_by_category.get(category.lower(), [])

    def get_nodes_by_domain(self, domain: Domain | str) -> list[NodeMetadata]:
        """Return all nodes belonging to a specific reasoning domain."""
        target_domain = domain if isinstance(domain, Domain) else Domain(domain)
        return [node for node in self.nodes_by_id.values() if node.domain == target_domain]

    @staticmethod
    def _safe_float(val: Any) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
