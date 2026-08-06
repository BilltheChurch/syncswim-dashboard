"""Tests for config.local.toml layering (DEVLOG #41).

Why this matters: the Emily kit overwrites config.toml wholesale on every
update (that's how she gets new model paths), so anything machine-specific
— camera URL, CPU-vs-Metal device — has to live in a file the kit never
ships. These tests pin the merge semantics that make that safe.
"""

from pathlib import Path

import pytest

from dashboard.config import _deep_merge, load_config


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------

def test_deep_merge_overrides_single_key_not_whole_table():
    base = {"hardware": {"camera_url": "http://tim", "num_poses": 8}}
    over = {"hardware": {"camera_url": "http://emily"}}
    out = _deep_merge(base, over)
    assert out["hardware"]["camera_url"] == "http://emily"
    assert out["hardware"]["num_poses"] == 8, "sibling keys must survive"


def test_deep_merge_adds_missing_tables():
    out = _deep_merge({"a": {"x": 1}}, {"b": {"y": 2}})
    assert out == {"a": {"x": 1}, "b": {"y": 2}}


def test_deep_merge_nests_recursively():
    base = {"a": {"b": {"c": 1, "d": 2}}}
    out = _deep_merge(base, {"a": {"b": {"c": 9}}})
    assert out["a"]["b"] == {"c": 9, "d": 2}


def test_deep_merge_does_not_mutate_inputs():
    base = {"hardware": {"camera_url": "http://tim"}}
    over = {"hardware": {"camera_url": "http://emily"}}
    _deep_merge(base, over)
    assert base["hardware"]["camera_url"] == "http://tim"


def test_deep_merge_replaces_non_dict_wholesale():
    # a list/scalar in the override replaces, never merges element-wise
    out = _deep_merge({"a": [1, 2, 3], "b": 1}, {"a": [9], "b": {"x": 1}})
    assert out["a"] == [9]
    assert out["b"] == {"x": 1}


# ---------------------------------------------------------------------------
# load_config layering
# ---------------------------------------------------------------------------

def _write(p: Path, text: str) -> Path:
    p.write_text(text)
    return p


def test_local_overrides_base(tmp_path):
    base = _write(tmp_path / "config.toml",
                  '[hardware]\ncamera_url = "http://tim"\nnum_poses = 8\n'
                  '[analysis]\ndevice = "mps"\n')
    local = _write(tmp_path / "config.local.toml",
                   '[hardware]\ncamera_url = "http://emily"\n'
                   '[analysis]\ndevice = "cpu"\n')
    cfg = load_config(config_path=base, local_config_path=local)
    assert cfg["hardware"]["camera_url"] == "http://emily"
    assert cfg["hardware"]["num_poses"] == 8
    assert cfg["analysis"]["device"] == "cpu"


def test_missing_local_is_fine(tmp_path):
    base = _write(tmp_path / "config.toml", '[hardware]\nnum_poses = 4\n')
    cfg = load_config(config_path=base,
                      local_config_path=tmp_path / "nope.toml")
    assert cfg["hardware"]["num_poses"] == 4


def test_broken_local_is_ignored_not_fatal(tmp_path):
    """A corrupt local override must never take the dashboard down."""
    base = _write(tmp_path / "config.toml", '[hardware]\nnum_poses = 4\n')
    bad = _write(tmp_path / "config.local.toml", "this is not = valid toml [[[")
    cfg = load_config(config_path=base, local_config_path=bad)
    assert cfg["hardware"]["num_poses"] == 4


def test_explicit_config_path_does_not_pick_up_real_local_file(tmp_path):
    """Tests that pass their own config must not inherit the developer's
    machine-local overrides (which would make them environment-dependent)."""
    base = _write(tmp_path / "config.toml", '[hardware]\ncamera_url = "http://test"\n')
    cfg = load_config(config_path=base)
    assert cfg["hardware"]["camera_url"] == "http://test"
    # real config.local.toml (if the dev has one) must not have leaked in
    assert set(cfg.keys()) == {"hardware"}


def test_defaults_used_when_base_missing_but_local_still_applies(tmp_path):
    local = _write(tmp_path / "config.local.toml",
                   '[hardware]\ncamera_url = "http://emily"\n')
    cfg = load_config(config_path=tmp_path / "absent.toml",
                      local_config_path=local)
    assert cfg["hardware"]["camera_url"] == "http://emily"
    # defaults still present for untouched keys
    assert "ble_device_name" in cfg["hardware"]
