"""Tests for dashboard/config.py — TOML configuration read/write."""
import os
import tempfile
from pathlib import Path

import pytest


def test_get_defaults_keys():
    """get_defaults returns dict with fina, hardware, dashboard keys."""
    from dashboard.config import get_defaults

    defaults = get_defaults()
    assert "fina" in defaults
    assert "hardware" in defaults
    assert "dashboard" in defaults


def test_get_defaults_fina_values():
    """Default FINA thresholds match spec."""
    from dashboard.config import get_defaults

    fina = get_defaults()["fina"]
    assert fina["clean_threshold_deg"] == 15
    assert fina["minor_deduction_deg"] == 30


def test_load_config_returns_dict():
    """load_config returns dict with expected keys."""
    from dashboard.config import load_config

    config = load_config()
    assert isinstance(config, dict)
    assert "fina" in config
    assert "hardware" in config
    assert "dashboard" in config


def test_load_config_missing_file_returns_defaults():
    """When config file doesn't exist, return defaults."""
    from dashboard.config import load_config

    config = load_config(config_path=Path("/tmp/nonexistent_config_12345.toml"))
    assert "fina" in config
    assert config["fina"]["clean_threshold_deg"] == 15


def test_save_and_load_roundtrip():
    """save_config then load_config returns identical data."""
    from dashboard.config import load_config, save_config

    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
        tmp_path = Path(f.name)

    try:
        original = {
            "fina": {"clean_threshold_deg": 20, "minor_deduction_deg": 35},
            "hardware": {"camera_url": "http://test:1234/video"},
            "dashboard": {"default_role": "Athlete"},
        }
        save_config(original, config_path=tmp_path)
        loaded = load_config(config_path=tmp_path)
        assert loaded == original
    finally:
        os.unlink(tmp_path)


def test_save_config_creates_file():
    """save_config creates a new TOML file."""
    from dashboard.config import save_config

    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
        tmp_path = Path(f.name)
    os.unlink(tmp_path)  # ensure it doesn't exist

    try:
        save_config({"test": {"key": "value"}}, config_path=tmp_path)
        assert tmp_path.exists()
        content = tmp_path.read_text()
        assert "key" in content
    finally:
        if tmp_path.exists():
            os.unlink(tmp_path)


def test_config_toml_exists_at_root():
    """config.toml exists at project root with expected sections."""
    root = Path(__file__).parent.parent / "config.toml"
    assert root.exists()
    content = root.read_text()
    assert "[fina]" in content
    assert "[hardware]" in content
    assert "[dashboard]" in content
    assert "clean_threshold_deg = 15" in content
    assert 'camera_url = "http://192.168.66.169:4747/video"' in content
    assert 'default_role = "Coach"' in content
