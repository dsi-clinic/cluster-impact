"""Storage I/O collection and privacy gate tests."""

from pathlib import Path
from unittest.mock import MagicMock

from collector import config as config_module
from collector.cli import _build_storage, _fetch_storage_io
from collector.runner import FixtureRunner
from collector.sources.prometheus import PrometheusSource
from collector.transform import privacy

CONFIG_DIR = Path(__file__).parent / "config"


def _make_prometheus(read_bytes, write_bytes):
    prom = MagicMock(spec=PrometheusSource)
    prom.configured = True

    def _integral(query, start, end):
        if "read" in query:
            return read_bytes, None
        return write_bytes, None

    prom.integral_bytes.side_effect = _integral
    return prom


def test_build_storage_disabled_returns_no_io():
    cfg = config_module.load(CONFIG_DIR)
    runner = FixtureRunner(Path(__file__).parent / "fixtures")
    doc, warnings = _build_storage(cfg, runner, fixture_mode=False, prometheus=None)
    assert doc["available"] is False


def test_fetch_storage_io_no_queries_returns_unavailable():
    prom = _make_prometheus(1_000_000, 2_000_000)
    doc, warnings = _fetch_storage_io(prom, {})
    assert doc["io_available"] is False
    assert any("storage_read_bytes" in w for w in warnings)


def test_fetch_storage_io_returns_bytes_when_prometheus_configured():
    prom = _make_prometheus(5_000_000_000, 3_000_000_000)
    settings = {
        "queries": {
            "storage_read_bytes": 'rate(node_disk_read_bytes_total{job="storage"}[5m])',
            "storage_write_bytes": 'rate(node_disk_written_bytes_total{job="storage"}[5m])',
        }
    }
    doc, warnings = _fetch_storage_io(prom, settings)
    assert doc["io_available"] is True
    assert doc["io_read_bytes"] == 5_000_000_000
    assert doc["io_write_bytes"] == 3_000_000_000
    assert "io_window_start" in doc
    assert "io_window_end" in doc
    assert not warnings


def test_fetch_storage_io_degrades_when_prometheus_returns_none():
    prom = _make_prometheus(None, None)
    settings = {
        "queries": {
            "storage_read_bytes": 'rate(node_disk_read_bytes_total{job="storage"}[5m])',
            "storage_write_bytes": 'rate(node_disk_written_bytes_total{job="storage"}[5m])',
        }
    }
    doc, warnings = _fetch_storage_io(prom, settings)
    assert doc["io_available"] is False


def test_privacy_gate_accepts_storage_io_doc(tmp_path):
    cfg = config_module.load(CONFIG_DIR)
    io_doc = {
        "available": True,
        "filesystems": [],
        "total_tib": 100.0,
        "used_tib": 40.0,
        "total_pib": 0.098,
        "io_available": True,
        "io_window_start": "2026-07-28",
        "io_window_end": "2026-07-29",
        "io_read_bytes": 5_000_000_000,
        "io_write_bytes": 3_000_000_000,
    }
    import json

    (tmp_path / "storage.json").write_text(json.dumps(io_doc))
    privacy.reset_allowed_strings()
    checked = privacy.verify_tree(tmp_path, cfg.groups, cfg.sources.k_anonymity)
    assert checked >= 1


def test_privacy_gate_accepts_storage_io_unavailable(tmp_path):
    cfg = config_module.load(CONFIG_DIR)
    no_io_doc = {
        "available": True,
        "filesystems": [],
        "total_tib": 100.0,
        "used_tib": 40.0,
        "total_pib": 0.098,
        "io_available": False,
    }
    import json

    (tmp_path / "storage.json").write_text(json.dumps(no_io_doc))
    privacy.reset_allowed_strings()
    checked = privacy.verify_tree(tmp_path, cfg.groups, cfg.sources.k_anonymity)
    assert checked >= 1
