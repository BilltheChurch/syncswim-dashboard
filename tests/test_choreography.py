"""Tests for dashboard/core/choreography.py — automated HF variable measurement.

Synthetic poses with known geometry verify each variable computes correctly
before trusting it on real noisy data. We assert DIRECTION + honest no-data
behavior, not exact absolute values (the variables are explicitly relative
indices — see the module docstring / docs/research-roadmap.md Direction A).
"""

import json
import math

import numpy as np
import pytest

from dashboard.core import choreography as ch


# ── helpers ────────────────────────────────────────────────────────────

def _empty_person() -> list:
    return [[0.0, 0.0, 0.0] for _ in range(33)]


def _set_pt(person, idx, x, y, vis=1.0):
    person[idx] = [float(x), float(y), float(vis)]


def _inverted_leg_person(theta_deg: float, hip_x: float = 0.5, hip_y: float = 0.6,
                         leg_len: float = 0.3, side: str = "right") -> list:
    """One swimmer with an inverted leg tilted theta_deg from vertical.

    y increases downward; an inverted (raised) leg has the ankle ABOVE the hip
    (smaller y). Knee is placed colinear so hip->ankle and knee->ankle agree.
    """
    p = _empty_person()
    hip_i, knee_i, ank_i = (
        (ch.R_HIP, ch.R_KNEE, ch.R_ANKLE) if side == "right"
        else (ch.L_HIP, ch.L_KNEE, ch.L_ANKLE)
    )
    th = math.radians(theta_deg)
    dx = leg_len * math.sin(th)
    dy = -leg_len * math.cos(th)        # up = negative y
    ax, ay = hip_x + dx, hip_y + dy
    kx, ky = hip_x + dx / 2, hip_y + dy / 2   # midpoint (colinear)
    _set_pt(p, hip_i, hip_x, hip_y)
    _set_pt(p, knee_i, kx, ky)
    _set_pt(p, ank_i, ax, ay)
    return p


def _frame(ts, persons, ids=None):
    return {"ts": float(ts), "frame": int(ts * 30) + 1, "persons": persons,
            "ids": ids if ids is not None else list(range(len(persons)))}


# ── leg_angle_deviation ────────────────────────────────────────────────

def test_leg_angle_deviation_vertical_is_near_zero():
    # 10 frames, each with 2 perfectly vertical legs (square frame → aspect 1)
    frames = []
    for i in range(10):
        p = _inverted_leg_person(0.0, side="right")
        # add a left leg too for pool size
        lp = _inverted_leg_person(0.0, hip_x=0.4, side="left")
        for idx in (ch.L_HIP, ch.L_KNEE, ch.L_ANKLE):
            p[idx] = lp[idx]
        frames.append(_frame(i / 30.0, [p], ids=[1]))
    val, cov = ch.leg_angle_deviation(frames, frame_w=720, frame_h=720)
    assert cov["n_legs"] >= ch.MIN_POOL
    assert val is not None and val == val  # not NaN
    assert val < 3.0, f"perfectly vertical legs should deviate ~0, got {val}"


def test_leg_angle_deviation_tilted_recovers_angle():
    # all legs tilted 25deg from vertical, square frame so no aspect distortion
    frames = [
        _frame(i / 30.0,
               [_inverted_leg_person(25.0, side="right"),
                _inverted_leg_person(25.0, hip_x=0.3, side="right")],
               ids=[1, 2])
        for i in range(8)
    ]
    val, cov = ch.leg_angle_deviation(frames, frame_w=600, frame_h=600)
    assert cov["n_legs"] >= ch.MIN_POOL
    # 20th-percentile of a constant-25deg pool ≈ 25deg
    assert 22.0 <= val <= 28.0, f"expected ~25deg, got {val}"


def test_leg_angle_deviation_too_few_legs_is_nan():
    # only 2 legs total < MIN_POOL → honest NaN, not a confident number
    frames = [_frame(0.0, [_inverted_leg_person(10.0)], ids=[1])]
    val, cov = ch.leg_angle_deviation(frames, frame_w=720, frame_h=720)
    assert cov["n_legs"] < ch.MIN_POOL
    assert math.isnan(val)


def test_leg_angle_deviation_aspect_ratio_matters():
    # same tilted legs measured under portrait vs square aspect → different value
    frames = [
        _frame(i / 30.0,
               [_inverted_leg_person(20.0), _inverted_leg_person(20.0, hip_x=0.3)],
               ids=[1, 2])
        for i in range(8)
    ]
    sq, _ = ch.leg_angle_deviation(frames, frame_w=600, frame_h=600)
    portrait, _ = ch.leg_angle_deviation(frames, frame_w=720, frame_h=960)
    assert abs(sq - portrait) > 0.5, "aspect correction should shift the angle"


# ── movement_frequency ─────────────────────────────────────────────────

def test_movement_frequency_static_leg_is_low():
    # a single still leg held vertical for 3s → ~0 direction reversals
    frames = [_frame(i / 30.0, [_inverted_leg_person(0.0)], ids=[1]) for i in range(90)]
    val, cov = ch.movement_frequency(frames, fps=30.0)
    assert val is not None and val == val
    assert val < 0.5, f"static leg should have ~0 movement frequency, got {val}"


def test_movement_frequency_oscillating_leg_is_positive():
    # leg angle oscillates +/-20deg with a ~1s period for 4s → clear reversals
    frames = []
    for i in range(120):
        t = i / 30.0
        theta = 20.0 * math.sin(2 * math.pi * 1.0 * t)
        frames.append(_frame(t, [_inverted_leg_person(theta)], ids=[1]))
    val, cov = ch.movement_frequency(frames, fps=30.0)
    assert val is not None and val == val
    assert val > 0.5, f"oscillating leg should register movements, got {val}"
    assert cov["n_tracks"] == 1


def test_movement_frequency_no_legs_is_nan():
    frames = [_frame(i / 30.0, [_empty_person()], ids=[1]) for i in range(30)]
    val, cov = ch.movement_frequency(frames, fps=30.0)
    assert math.isnan(val)
    assert cov["n_tracks"] == 0


# ── rotation_frequency ─────────────────────────────────────────────────

def test_rotation_frequency_steady_spin_recovers_rate():
    # shoulder line rotates 2deg/frame at 30fps = 60deg/s, steady, one swimmer
    frames = []
    cx, cy, r = 0.5, 0.5, 0.1
    for i in range(60):
        ang = math.radians(2.0 * i)
        p = _empty_person()
        _set_pt(p, ch.L_SHOULDER, cx - r * math.cos(ang), cy - r * math.sin(ang))
        _set_pt(p, ch.R_SHOULDER, cx + r * math.cos(ang), cy + r * math.sin(ang))
        frames.append(_frame(i / 30.0, [p], ids=[7]))
    val, cov = ch.rotation_frequency(frames)
    assert val is not None and val == val
    assert 45.0 <= val <= 75.0, f"expected ~60deg/s, got {val}"
    assert cov["n_swimmers"] == 1


def test_rotation_frequency_static_is_low():
    frames = []
    for i in range(40):
        p = _empty_person()
        _set_pt(p, ch.L_SHOULDER, 0.45, 0.5)
        _set_pt(p, ch.R_SHOULDER, 0.55, 0.5)
        frames.append(_frame(i / 30.0, [p], ids=[7]))
    val, cov = ch.rotation_frequency(frames)
    assert val is not None and val == val
    assert val < 5.0, f"static body should have ~0 rotation, got {val}"


# ── leg_height_index (excluded surrogate) ──────────────────────────────

def test_leg_vertical_extension_vertical_is_high():
    frames = [_frame(i / 30.0, [_inverted_leg_person(0.0)], ids=[1]) for i in range(5)]
    val, cov = ch.leg_vertical_extension(frames)
    # perfectly vertical → cos(0)=1 → ~100%
    assert val is not None and val > 95.0


# ── honest no-data + JSON ──────────────────────────────────────────────

def test_compute_choreography_empty_returns_none(tmp_path):
    assert ch.compute_choreography(str(tmp_path)) is None


def _write_set(tmp_path, name, frames):
    d = tmp_path / name
    d.mkdir()
    with open(d / "landmarks_multi.jsonl", "w") as fh:
        for f in frames:
            fh.write(json.dumps(f) + "\n")
    return str(d)


def test_compute_choreography_json_serializable(tmp_path):
    frames = [
        _frame(i / 30.0,
               [_inverted_leg_person(15.0), _inverted_leg_person(15.0, hip_x=0.3)],
               ids=[1, 2])
        for i in range(30)
    ]
    sd = _write_set(tmp_path, "set_synthetic_a", frames)
    rep = ch.compute_choreography(sd)
    assert rep is not None
    # must serialize cleanly (no numpy scalar leakage)
    json.dumps(rep)
    keys = {v["key"] for v in rep["variables"]}
    assert keys == set(ch.YUE_BENCHMARK.keys())
    # statuses are honest
    by = {v["key"]: v for v in rep["variables"]}
    assert by["leg_height_index"]["status"] == "excluded"
    assert by["movement_frequency"]["status"] == "validated"
    assert by["mean_pattern_duration"]["status"] == "exploratory"
    # no variable claims to be comparable to the paper's absolute scale
    assert all(not v["comparable_to_paper"] for v in rep["variables"])


def test_rank_sets_direction_and_serializable(tmp_path):
    # set A: legs tilted 30deg (worse deviation); set B: 5deg (better).
    # leg_angle_deviation has negative beta → lower is better → B should
    # out-rank A on that term.
    def legset(theta):
        return [
            _frame(i / 30.0,
                   [_inverted_leg_person(theta), _inverted_leg_person(theta, hip_x=0.3)],
                   ids=[1, 2])
            for i in range(20)
        ]
    _write_set(tmp_path, "set_aaa", legset(30.0))
    _write_set(tmp_path, "set_bbb", legset(5.0))
    rk = ch.rank_sets(str(tmp_path))
    json.dumps(rk)
    order = [r["set"] for r in rk["ranking"]]
    assert order.index("set_bbb") < order.index("set_aaa"), \
        "lower leg-angle-deviation clip should rank higher"
    assert rk["variables"] == list(ch.COMPOSITE_VARIABLES)
