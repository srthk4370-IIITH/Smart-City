"""Unit tests for SCRCIHubIngestor (SCRC-IHub Data Collection streaming reader)."""

from pathlib import Path

from smart_city_edge.ingestor import SCRCIHubIngestor


def test_scrc_ihub_ingestor_aq_streaming():
    ingestor = SCRCIHubIngestor()
    data_dir = ingestor.data_dir

    if data_dir.is_dir() and (data_dir / "aq.csv").is_file():
        records = list(ingestor.read_aq_csv(limit=5))
        assert len(records) > 0
        rec = records[0]
        assert "record_id" in rec
        assert "indoor_pm25" in rec
        assert "indoor_temp_c" in rec
        assert rec["indoor_temp_c"] > 0


def test_scrc_ihub_ingestor_wf_streaming():
    ingestor = SCRCIHubIngestor()
    data_dir = ingestor.data_dir

    if data_dir.is_dir() and (data_dir / "wm-wf.csv").is_file():
        records = list(ingestor.read_wf_csv(limit=5))
        assert len(records) > 0
        rec = records[0]
        assert "node_id" in rec
        assert "domain_type" in rec
        assert rec["domain_type"] == "water_flow"
