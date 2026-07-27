"""Configuration module for SyncSwim Dashboard.

Uses tomllib (stdlib, read-only) and tomli_w (write) for TOML round-trip.
Config file lives at project root: config.toml
"""
import json
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
        cfg = get_defaults()
    else:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    _apply_runtime_overrides(cfg, path)
    return cfg


def _override_path(cfg: dict, config_path: Path) -> Path:
    """运行时覆盖文件路径：<data_dir>/camera_override.json。

    放在 data/ 而不是 config.toml —— Emily 的 kit 更新会用 code.zip 覆盖
    config.toml，但从不动 data/(录制数据区)。这样"在网页设置页改摄像头 URL"
    改一次就永久生效，不会被下次更新冲回模板值。
    """
    data_dir = cfg.get("dashboard", {}).get("data_dir", "data")
    return config_path.parent / data_dir / "camera_override.json"


# 允许网页运行时覆盖的 hardware 字段白名单(防止 override 文件塞入无关字段)。
# camera_url/rotation = 现场摄像头;swimmer_detector_enabled = 泳池 v2/通用模型切换;
# num_poses = 单人/多人。都放 data/ 覆盖层,改一次不被 kit 更新冲。
_OVERRIDABLE = {
    "camera_url", "camera_rotation", "swimmer_detector_enabled", "num_poses",
}


def _apply_runtime_overrides(cfg: dict, config_path: Path) -> None:
    """把用户在网页存的运行时覆盖(白名单内的 hardware 字段)合并进 config。"""
    override = _override_path(cfg, config_path)
    if not override.exists():
        return
    try:
        o = json.loads(override.read_text(encoding="utf-8"))
    except Exception:
        return
    hw = cfg.setdefault("hardware", {})
    for k in _OVERRIDABLE:
        if k in o and o[k] is not None:
            hw[k] = o[k]


def save_runtime_override(config_path: Path | None = None, **fields) -> None:
    """把白名单内的 hardware 字段持久化到 data/camera_override.json(不受 kit 更新影响)。

    与 save_config() 互补：save_config 写 config.toml(会被 code.zip 更新覆盖)，这里写
    data/ 下的覆盖文件(更新从不碰 data/)。网页设置改一次就永久生效。
    """
    path = config_path or CONFIG_PATH
    cfg = get_defaults()
    if path.exists():
        try:
            with open(path, "rb") as f:
                cfg = tomllib.load(f)
        except Exception:
            pass
    override_path = _override_path(cfg, path)
    override_path.parent.mkdir(parents=True, exist_ok=True)
    current: dict = {}
    if override_path.exists():
        try:
            current = json.loads(override_path.read_text(encoding="utf-8"))
        except Exception:
            current = {}
    for k, v in fields.items():
        if k in _OVERRIDABLE and v is not None:
            current[k] = v
    override_path.write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def save_camera_override(camera_url: str | None = None,
                         camera_rotation: int | None = None,
                         config_path: Path | None = None) -> None:
    """向后兼容的薄封装 —— 摄像头设置走通用的 save_runtime_override。"""
    save_runtime_override(
        config_path=config_path,
        camera_url=camera_url,
        camera_rotation=camera_rotation,
    )


def save_config(config: dict, config_path: Path | None = None) -> None:
    """Write config dict back to config.toml.

    Args:
        config: The full configuration dict to write.
        config_path: Override path for testing. Defaults to CONFIG_PATH.
    """
    path = config_path or CONFIG_PATH
    with open(path, "wb") as f:
        tomli_w.dump(config, f)
