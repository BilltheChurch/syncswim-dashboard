"""Configuration module for SyncSwim Dashboard.

Uses tomllib (stdlib, read-only) and tomli_w (write) for TOML round-trip.
Config file lives at project root: config.toml
"""
import tomllib
from pathlib import Path

import tomli_w

# Resolve config.toml relative to this file's parent's parent (project root)
CONFIG_PATH = Path(__file__).parent.parent / "config.toml"

# Machine-specific overrides, layered ON TOP of config.toml and never
# committed / never shipped in a kit (DEVLOG #41). This is what lets
# Emily's camera URL and CPU-only device survive a kit update: the kit
# overwrites config.toml wholesale (that's how she gets new model paths),
# but config.local.toml is hers.
LOCAL_CONFIG_PATH = Path(__file__).parent.parent / "config.local.toml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` (override wins).

    Only dicts are merged; every other type is replaced wholesale, so a
    local ``[hardware] camera_url`` overrides just that key and leaves
    the rest of ``[hardware]`` from config.toml intact.
    """
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


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


def load_config(config_path: Path | None = None,
                local_config_path: Path | None = None) -> dict:
    """Read config.toml, then layer config.local.toml on top.

    Falls back to defaults if config.toml does not exist. A missing or
    unreadable config.local.toml is simply ignored — a broken local
    override must never take the dashboard down.

    Args:
        config_path: Override path for testing. Defaults to CONFIG_PATH.
        local_config_path: Override local path for testing. Defaults to
            LOCAL_CONFIG_PATH; only consulted when ``config_path`` is
            also left at its default, so tests that point at a temp
            config don't accidentally pick up the real local file.
    """
    path = config_path or CONFIG_PATH
    cfg = get_defaults() if not path.exists() else tomllib.load(open(path, "rb"))

    if local_config_path is None:
        # Don't leak the machine's local overrides into tests that pass
        # an explicit config_path.
        local_path = LOCAL_CONFIG_PATH if config_path is None else None
    else:
        local_path = local_config_path
    if local_path is not None and local_path.exists():
        try:
            with open(local_path, "rb") as f:
                cfg = _deep_merge(cfg, tomllib.load(f))
        except Exception as e:
            print(f"[config] ignoring broken {local_path.name}: {e}")
    return cfg


def save_config(config: dict, config_path: Path | None = None) -> None:
    """Write config dict back to config.toml.

    Args:
        config: The full configuration dict to write.
        config_path: Override path for testing. Defaults to CONFIG_PATH.
    """
    path = config_path or CONFIG_PATH
    with open(path, "wb") as f:
        tomli_w.dump(config, f)
