"""Configuration module for SyncSwim Dashboard.

Uses tomllib (stdlib, read-only) and tomli_w (write) for TOML round-trip.
Config file lives at project root: config.toml
"""
import tomllib
from pathlib import Path

import tomli_w

# Resolve config.toml relative to this file's parent's parent (project root)
CONFIG_PATH = Path(__file__).parent.parent / "config.toml"


def get_defaults() -> dict:
    """Default configuration values."""
    return {
        "fina": {
            "clean_threshold_deg": 15,
            "minor_deduction_deg": 30,
            "clean_deduction": 0.0,
            "minor_deduction": 0.2,
            "major_deduction": 0.5,
        },
        "hardware": {
            "camera_url": "http://192.168.66.169:4747/video",
            "ble_device_name": "NODE_A1",
            "ble_char_uuid": "abcd1234-ab12-cd34-ef56-abcdef123456",
        },
        "dashboard": {
            "default_role": "Coach",
            "data_dir": "data",
        },
    }


def load_config(config_path: Path | None = None) -> dict:
    """Read config.toml. Returns dict.

    Falls back to defaults if file does not exist.

    Args:
        config_path: Override path for testing. Defaults to CONFIG_PATH.
    """
    path = config_path or CONFIG_PATH
    if not path.exists():
        return get_defaults()
    with open(path, "rb") as f:
        return tomllib.load(f)


def save_config(config: dict, config_path: Path | None = None) -> None:
    """Write config dict back to config.toml.

    Args:
        config: The full configuration dict to write.
        config_path: Override path for testing. Defaults to CONFIG_PATH.
    """
    path = config_path or CONFIG_PATH
    with open(path, "wb") as f:
        tomli_w.dump(config, f)
