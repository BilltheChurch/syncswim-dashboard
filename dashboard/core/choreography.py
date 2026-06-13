"""Choreography Intelligence — automated hybrid-figure (HF) variable measurement.

Automates the 5 score-predicting HF variables from
    Yue et al. 2023, Nature Scientific Reports 13:21303
    "Maximizing choreography and performance in artistic swimming team free
     routines: the role of hybrid figures"
which were originally hand-measured in Kinovea (1-2 weeks of analyst time per
team). We compute them directly from data/<set>/landmarks_multi.jsonl
(per-frame multi-swimmer MP-33 keypoints from HybridSwimmerDetector, mAP@50=0.84).

────────────────────────────────────────────────────────────────────────────
HONESTY FIRST — this module deliberately UNDER-claims. Every algorithm here was
adversarially verified by running it against our real dogfood data (set_002..020).
The verification found that monocular, uncalibrated, heavily-occluded competition
footage does NOT support faithful absolute reproduction of Yue's Kinovea numbers.
What survives, and how, per variable:

  movement_frequency   VALIDATED  — relative cross-clip index (NOT absolute Hz).
                                    Counts smoothed leg direction-reversals with a
                                    frame-time refractory window.
  rotation_frequency   CAVEAT     — paper-faithful aggregation (total rotation
                                    degrees / total tracked duration; NO fudge
                                    constant). Relative only: oblique side view
                                    foreshortens the horizontal-plane rotation and
                                    handheld shake inflates it.
  leg_angle_deviation  CAVEAT     — deviation-from-vertical of legs at the vertical
                                    position, with aspect-ratio correction. ~2x the
                                    paper's absolute degrees (image-vertical != water
                                    horizontal, no horizon calibration). Relative.
  mean_pattern_duration EXPLORATORY — measures rearrangement of *visible* body
                                    centroids, NOT true 8-swimmer team formations
                                    (80%+ of person-slots have zero visible
                                    keypoints). Floor-pinned + camera-orientation
                                    confounded. Do not benchmark vs Yue's 6.15 s.
  leg_height_index     EXCLUDED   — the paper's water-relative AB/AC needs a water
                                    line we do not have. The naive hip-as-waterline
                                    proxy is an anthropometric CONSTANT that is
                                    anti-correlated (r=-0.376) with real leg lift —
                                    it ranks teams BACKWARDS. We compute a
                                    "vertical extension fraction" surrogate for
                                    completeness but EXCLUDE it from any score.

CROSS-CUTTING: we do NOT export an absolute "predicted Yue total score". The
published betas were fit on calibrated Kinovea inputs; our proxies live on a
different unknown scale (and leg_height_index is anti-correlated yet carries the
largest positive beta). Instead, ``rank_sets`` produces a RELATIVE z-score index
across our own clips from the surviving variables only. The scientifically
interesting result is *which* biomechanical markers survive automation from
uncalibrated video and which do not — the negative results are first-class.

See docs/research-roadmap.md (Direction A) + DEVLOG for the full rationale.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Any

import numpy as np

VIS_THRESHOLD = 0.5  # mirror dashboard/core/vision_angles.py
MIN_POOL = 8         # leg_angle_deviation: fewer clean legs than this ⇒ NaN (noise)

# MP-33 indices we use (COCO-17 source fills only these).
NOSE = 0
L_EAR, R_EAR = 7, 8
L_SHOULDER, R_SHOULDER = 11, 12
L_HIP, R_HIP = 23, 24
L_KNEE, R_KNEE = 25, 26
L_ANKLE, R_ANKLE = 27, 28

# Yue 2023 Table 2 benchmarks: international (n=105) | top-5 (n=30) mean.
# Kept for REFERENCE display only — our relative indices are NOT comparable to
# these absolute Kinovea numbers (see module docstring + per-variable caveats).
YUE_BENCHMARK = {
    "leg_height_index":     {"intl": 30.77, "top5": 32.75, "unit": "%",     "beta": +0.393},
    "movement_frequency":   {"intl": 1.82,  "top5": 1.92,  "unit": "Hz",    "beta": +0.345},
    "leg_angle_deviation":  {"intl": 5.34,  "top5": 4.32,  "unit": "deg",   "beta": -0.229},
    "mean_pattern_duration":{"intl": 6.15,  "top5": 5.45,  "unit": "s",     "beta": -0.190},
    "rotation_frequency":   {"intl": 41.77, "top5": 44.95, "unit": "deg/s", "beta": +0.149},
}

# Which variables enter the relative cross-clip composite. Only the ones with a
# defensible directional signal survive (verification verdict). leg_height_index
# (anti-correlated) and mean_pattern_duration (framing-confounded floor) are out.
COMPOSITE_VARIABLES = ("movement_frequency", "rotation_frequency", "leg_angle_deviation")


@dataclass
class HFVariable:
    key: str
    value: float | None          # measured value; None if NaN / unmeasurable
    unit: str
    status: str                  # validated | caveat | exploratory | excluded
    confidence: str              # high | medium | low | n/a
    coverage: dict               # honest support: sample counts / tracked time
    caveat: str                  # human-readable honesty note (shown in UI)
    benchmark_intl: float        # Yue Table 2 international mean (reference only)
    benchmark_top5: float        # Yue Table 2 top-5 mean (reference only)
    paper_beta: float            # Yue Table 3 standardized regression beta
    comparable_to_paper: bool    # False for every relative/exploratory index


# ─────────────────────────────────────────────────────────────────────────
# Loader
# ─────────────────────────────────────────────────────────────────────────

def load_multi_frames(set_dir: str) -> list[dict]:
    """Parse data/<set>/landmarks_multi.jsonl into a list of frame dicts.

    Each dict: {"ts": float, "frame": int, "persons": [[[x,y,vis]x33], ...],
                "ids": [int|null, ...]}. Returns [] if the file is absent/empty.
    """
    path = os.path.join(set_dir, "landmarks_multi.jsonl")
    if not os.path.exists(path):
        return []
    frames: list[dict] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                frames.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return frames


def video_resolution(set_dir: str) -> tuple[int | None, int | None]:
    """Return (width, height) of video.mp4 for aspect-ratio correction, or
    (None, None) if unavailable. Lazy cv2 import so non-video callers don't pay.
    """
    vpath = os.path.join(set_dir, "video.mp4")
    if not os.path.exists(vpath):
        return None, None
    try:
        import cv2
        cap = cv2.VideoCapture(vpath)
        if not cap.isOpened():
            return None, None
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        return (w or None), (h or None)
    except Exception:
        return None, None


def _infer_fps(frames: list[dict], fallback: float = 30.0) -> float:
    ts = np.array([f.get("ts", i / fallback) for i, f in enumerate(frames)], dtype=float)
    if ts.size < 2:
        return fallback
    dt = np.diff(ts)
    dt = dt[dt > 0]
    return float(1.0 / np.median(dt)) if dt.size else fallback


# ─────────────────────────────────────────────────────────────────────────
# The 5 HF variable algorithms (adversarially verified against real data).
# Each returns (value, coverage_dict). value is NaN when unmeasurable.
# ─────────────────────────────────────────────────────────────────────────

def movement_frequency(frames: list[dict], fps: float | None = None,
                       MIN_VALID_SAMPLES: int = 10, MIN_TRACK_SECONDS: float = 1.0,
                       MIN_SEPARATION_SECONDS: float = 0.30,
                       VEL_THRESH_FRAC: float = 0.20, SMOOTH_WIN: int = 5
                       ) -> tuple[float, dict]:
    """Per-swimmer leg-movement frequency (Hz), averaged over track windows.

    Proxy for Yue 2023 movement_frequency. RELATIVE index — the thresholds are
    hand-set, not calibrated to hand counts, so treat absolute Hz as a cross-clip
    relative number, not as Yue's 1.82±0.17 Hz. NaN ⇒ no_data (legs never
    visible). Verified: refractory operates in true frame-time; smoothing is
    edge-padded (no end zero-pull); ids padded defensively (no zip truncation).
    """
    if not frames or len(frames) < 2:
        return float("nan"), {"n_tracks": 0}
    if fps is None:
        fps = _infer_fps(frames)

    def leg_signal(p):
        # Prefer right knee->ankle (26->28), else left (25->27); fall back to
        # mean visible ankle y * 180 to keep velocity on a comparable scale.
        for kI, aI in ((R_KNEE, R_ANKLE), (L_KNEE, L_ANKLE)):
            if p[kI][2] >= VIS_THRESHOLD and p[aI][2] >= VIS_THRESHOLD:
                dx = p[aI][0] - p[kI][0]
                dy = p[aI][1] - p[kI][1]
                return float(np.degrees(np.arctan2(dx, dy)))  # signed from vertical
        ys = [p[i][1] for i in (L_ANKLE, R_ANKLE) if p[i][2] >= VIS_THRESHOLD]
        return (float(np.mean(ys)) * 180.0) if ys else np.nan

    tracks: dict = defaultdict(list)
    for fi, f in enumerate(frames):
        persons = f.get("persons", []) or []
        ids = f.get("ids")
        if not ids or len(ids) != len(persons):
            ids = (list(ids) + [None] * (len(persons) - len(ids))) if ids else [None] * len(persons)
        for pi, (p, pid) in enumerate(zip(persons, ids)):
            if not p or len(p) < 29:
                continue
            key = pid if pid is not None else ("anon", fi, pi)
            tracks[key].append((fi, leg_signal(p)))

    def smooth_ma(v, w):
        if w <= 1 or len(v) < w:
            return v
        pad = w // 2
        vp = np.pad(v, pad, mode="edge")
        return np.convolve(vp, np.ones(w) / w, mode="valid")

    def count_movements(grid_signal):
        if len(grid_signal) < 3:
            return 0
        vel = np.gradient(grid_signal)
        std = float(np.nanstd(vel))
        if std <= 0:
            return 0
        s = np.sign(np.where(np.abs(vel) < VEL_THRESH_FRAC * std, 0.0, vel))
        min_sep = max(1, int(round(MIN_SEPARATION_SECONDS * fps)))
        events, last_sign = [], 0
        for i, si in enumerate(s):
            if si == 0:
                continue
            if last_sign != 0 and si != last_sign:
                events.append(i)
            last_sign = si
        if not events:
            return 0
        kept = [events[0]]
        for e in events[1:]:
            if e - kept[-1] >= min_sep:
                kept.append(e)
        return len(kept)

    rates, used_tracks, total_track_s = [], 0, 0.0
    for v in tracks.values():
        fis = np.array([x[0] for x in v])
        vals = np.array([x[1] for x in v], dtype=float)
        m = ~np.isnan(vals)
        if int(m.sum()) < MIN_VALID_SAMPLES:
            continue
        fv, vv = fis[m], vals[m]
        span_s = (fv[-1] - fv[0]) / fps
        if span_s < MIN_TRACK_SECONDS:
            continue
        grid = np.arange(fv[0], fv[-1] + 1)
        gi = smooth_ma(np.interp(grid, fv, vv), SMOOTH_WIN)
        rates.append(count_movements(gi) / span_s)
        used_tracks += 1
        total_track_s += float(span_s)

    cov = {"n_tracks": used_tracks, "tracked_seconds": round(float(total_track_s), 1)}
    if not rates:
        return float("nan"), cov
    return float(np.nanmean(rates)), cov


def rotation_frequency(frames: list[dict], VIS: float = 0.5, MAX_GAP_S: float = 0.2,
                       MAX_RATE: float = 300.0, MIN_LEN: int = 10, SMOOTH_K: int = 5,
                       MIN_TOTAL_S: float = 0.5) -> tuple[float, dict]:
    """Body-axis rotation frequency (deg/s), paper-faithful aggregation.

    Yue defines rotation_frequency as TOTAL rotation degrees / total HF duration.
    We sum |undirected body-axis change| (shoulder line 11-12, hip line 23-24
    fallback) over all swimmers / sum of the time those changes span. NO fudge
    constant — uncalibrated this lands ~20-40 deg/s vs the paper band 41.77±10.01,
    BUT it is a RELATIVE index: oblique side-view foreshortens horizontal-plane
    rotation and handheld shake inflates it. Weight cross-set use by total_dur_s.
    """
    SHOULDER, HIP = (L_SHOULDER, R_SHOULDER), (L_HIP, R_HIP)

    def axis_orientation(arr):
        for a, b in (SHOULDER, HIP):
            if arr[a, 2] >= VIS and arr[b, 2] >= VIS:
                dx = arr[b, 0] - arr[a, 0]
                dy = arr[b, 1] - arr[a, 1]
                if dx != 0.0 or dy != 0.0:
                    return math.degrees(math.atan2(dy, dx)) % 180.0
        return np.nan

    def moving_median(x, k):
        n = len(x)
        if k <= 1 or n < k:
            return x.copy()
        h = k // 2
        out = x.copy()
        for i in range(n):
            out[i] = np.median(x[max(0, i - h): i + h + 1])
        return out

    series: dict = defaultdict(list)
    for r in frames:
        ts = r.get("ts")
        if ts is None:
            continue
        persons = r.get("persons") or []
        ids = r.get("ids") or [None] * len(persons)
        for slot, p in enumerate(persons):
            arr = np.asarray(p, dtype=float)
            if arr.ndim != 2 or arr.shape[0] < 33 or arr.shape[1] < 3:
                continue
            if not (arr[:, 2] > 0).any():
                continue
            pid = ids[slot] if slot < len(ids) else None
            if pid is None:
                continue
            series[pid].append((float(ts), axis_orientation(arr)))

    total_deg, total_dur, n_swimmers = 0.0, 0.0, 0
    for seq in series.values():
        seq = [(t, a) for (t, a) in seq if a == a]
        if len(seq) < MIN_LEN:
            continue
        seq.sort(key=lambda z: z[0])
        ts = np.array([t for t, _ in seq], dtype=float)
        ang = np.array([a for _, a in seq], dtype=float)
        cont = np.rad2deg(np.unwrap(np.deg2rad(ang * 2.0)) / 2.0)
        cont = moving_median(cont, SMOOTH_K)
        dpos = np.abs(np.diff(cont))
        dt = np.diff(ts)
        good = (dt > 0) & (dt <= MAX_GAP_S)
        if not good.any():
            continue
        dpos, dt = dpos[good], dt[good]
        rate = dpos / dt
        keep = rate <= MAX_RATE
        dpos, dt = dpos[keep], dt[keep]
        if dt.size == 0:
            continue
        total_deg += float(np.sum(dpos))
        total_dur += float(np.sum(dt))
        n_swimmers += 1

    cov = {"n_swimmers": n_swimmers, "tracked_seconds": round(total_dur, 1)}
    if total_dur < MIN_TOTAL_S:
        return float("nan"), cov
    return total_deg / total_dur, cov


def leg_angle_deviation(frames: list[dict], frame_w: int | None = None,
                        frame_h: int | None = None, VIS: float = 0.5,
                        Y_MARGIN: float = 0.02, MAX_VERTICAL_DEV: float = 35.0,
                        PCTL: float = 20.0, min_pool: int = MIN_POOL) -> tuple[float, dict]:
    """Mean deviation-from-vertical (deg) of legs held at the vertical position.

    CAVEATS (verified): we substitute IMAGE-vertical for the paper's true
    water-surface horizontal (no tilt calibration → dominant bias), pool all legs
    instead of averaging the 8 named members, and run ~2x the paper's 5.34±2.33
    deg. Aspect-ratio correction (dx*=W/H) is applied because normalized x,y are
    anisotropic — on our 4:3 / 3:4 footage omitting it biases 1-4 deg with a sign
    that flips between landscape and portrait. RELATIVE index; ranks our own clips
    only. NaN when fewer than MIN_POOL clean legs (e.g. ankles underwater).
    """
    aspect = (float(frame_w) / float(frame_h)) if (frame_w and frame_h) else 1.0
    LEGS = [(L_HIP, L_KNEE, L_ANKLE), (R_HIP, R_KNEE, R_ANKLE)]

    def dev_from_vertical(hx, hy, ax, ay):
        dx = (ax - hx) * aspect
        dy = (ay - hy)
        length = math.hypot(dx, dy)
        if length == 0:
            return np.nan
        c = min(max(abs(dy) / length, -1.0), 1.0)
        return float(np.degrees(math.acos(c)))

    pool = []
    for fr in frames:
        for person in (fr.get("persons") or []):
            if not person or len(person) < 29:
                continue
            for hip_i, knee_i, ank_i in LEGS:
                hip, ank = person[hip_i], person[ank_i]
                if hip[2] < VIS or ank[2] < VIS:
                    continue
                hx, hy = hip[0], hip[1]
                ax, ay = ank[0], ank[1]
                if ay >= hy - Y_MARGIN:  # raised-leg gate (ankle above hip)
                    continue
                knee = person[knee_i]
                if knee[2] >= VIS:       # prefer shank when knee reliable
                    dev = dev_from_vertical(knee[0], knee[1], ax, ay)
                else:
                    dev = dev_from_vertical(hx, hy, ax, ay)
                if np.isnan(dev) or dev > MAX_VERTICAL_DEV:
                    continue
                pool.append(dev)

    cov = {"n_legs": len(pool), "aspect_corrected": (frame_w is not None and frame_h is not None)}
    if len(pool) < min_pool:
        return float("nan"), cov
    arr = np.asarray(pool, dtype=float)
    cutoff = np.nanpercentile(arr, PCTL)
    selected = arr[arr <= cutoff]
    if selected.size == 0:
        selected = arr
    return float(np.nanmean(selected)), cov


def mean_pattern_duration(frames: list[dict], fps: float | None = None, win: int = 11,
                          n_quantiles: int = 12, change_thr: float = 0.18,
                          min_hold_s: float = 2.5, confirm: int = 4, ema: float = 0.08,
                          min_swimmers: int = 3, max_cloud: int = 20,
                          min_boundaries: int = 3) -> tuple[float, dict, str]:
    """EXPLORATORY vision proxy for Yue mean_pattern_duration (seconds).

    Verified NOT comparable to the paper's per-routine 6.15±1.34 s: 80%+ of
    person-slots have zero visible keypoints, <=11% of frames show >=3 swimmers,
    and the value is dominated by camera framing / detection density and by the
    min_hold floor, not by true 8-swimmer planar reconfiguration. Returns
    (value, coverage, confidence). Use only as a rough exploratory signal.
    """
    nan = float("nan")
    if not frames:
        return nan, {"n_boundaries": 0}, "low"
    ts = np.array([float(o.get("ts", i / 30.0)) for i, o in enumerate(frames)], dtype=float)
    if ts.size < 2:
        return nan, {"n_boundaries": 0}, "low"
    if fps is None:
        fps = _infer_fps(frames)

    def person_centroid(p):
        try:
            a = np.asarray(p, dtype=float)
        except (ValueError, TypeError):
            return None
        if a.ndim != 2 or a.shape[0] == 0 or a.shape[1] < 3:
            return None
        m = a[:, 2] >= VIS_THRESHOLD
        if not m.any():
            return None
        x, y = float(np.nanmean(a[m, 0])), float(np.nanmean(a[m, 1]))
        return (x, y) if (np.isfinite(x) and np.isfinite(y)) else None

    def window_signature(fw):
        cs = []
        for o in fw:
            for p in (o.get("persons") or []):
                c = person_centroid(p)
                if c is not None:
                    cs.append(c)
        cs = np.asarray(cs, dtype=float)
        if cs.shape[0] < min_swimmers or cs.shape[0] > max_cloud:
            return None
        n = cs.shape[0]
        iu = np.triu_indices(n, k=1)
        diffs = cs[iu[0]] - cs[iu[1]]
        d = np.sort(np.hypot(diffs[:, 0], diffs[:, 1]))
        s = float(np.median(d))
        if not (s > 1e-9):
            return None
        dn = np.clip(d / s, 0.0, 4.0)
        qs = np.quantile(dn, np.linspace(0.0, 1.0, n_quantiles))
        nrm = np.linalg.norm(qs)
        return qs / nrm if nrm > 0 else qs

    sigs, sig_ts, half = [], [], win // 2
    for i in range(len(frames)):
        sg = window_signature(frames[max(0, i - half): i + half + 1])
        if sg is not None:
            sigs.append(sg)
            sig_ts.append(ts[i])
    if len(sigs) < 10:
        return nan, {"n_boundaries": 0}, "low"
    sigs, sig_ts = np.asarray(sigs), np.asarray(sig_ts)

    boundaries, ref, last, pending = [], sigs[0].copy(), sig_ts[0], 0
    for k in range(1, len(sigs)):
        if np.linalg.norm(sigs[k] - ref) > change_thr:
            pending += 1
            if pending >= confirm and (sig_ts[k] - last) >= min_hold_s:
                boundaries.append(sig_ts[k])
                last = sig_ts[k]
                ref = sigs[k].copy()
                pending = 0
        else:
            pending = 0
            ref = (1.0 - ema) * ref + ema * sigs[k]

    cov = {"n_boundaries": len(boundaries)}
    if len(boundaries) < min_boundaries:
        return nan, cov, "low"
    gaps = np.diff(np.asarray(boundaries, dtype=float))
    val = float(np.nanmean(gaps)) if gaps.size else nan
    if not np.isfinite(val):
        return nan, cov, "low"
    floor = float(min_hold_s)
    if (val <= floor * 1.15) or not (1.0 <= val <= 15.0):
        conf = "low"
    elif len(boundaries) >= 5:
        conf = "medium"
    else:
        conf = "low"
    return val, cov, conf


def leg_vertical_extension(frames: list[dict], VIS: float = 0.5,
                           MIN_LEG_LEN: float = 0.02) -> tuple[float, dict]:
    """EXCLUDED surrogate for Yue leg_height_index.

    The paper's leg_height_index is WATER-RELATIVE (AB/AC; A=water line). We have
    no water line and no scale, and the naive hip-as-waterline proxy is an
    anthropometric CONSTANT anti-correlated (r=-0.376) with real leg lift — it
    ranks teams BACKWARDS. This computes instead the leg's vertical-extension
    fraction = cos(angle from vertical) of the hip->ankle vector, in [0,1]
    (1.0 = perfectly vertical/emerged-direction leg). It is a *different
    construct* from leg_height_index, NOT comparable to the paper's 30.77%, and is
    EXCLUDED from any score — kept only for completeness/exploration.
    """
    LEG_CHAINS = ((L_HIP, L_ANKLE), (R_HIP, R_ANKLE))
    vals = []
    for fr in (frames or []):
        for person in (fr.get("persons") or []):
            if not person or len(person) < 29:
                continue
            for hip_i, ank_i in LEG_CHAINS:
                hip, ank = person[hip_i], person[ank_i]
                if hip[2] < VIS or ank[2] < VIS:
                    continue
                dx, dy = ank[0] - hip[0], ank[1] - hip[1]
                leg_len = math.hypot(dx, dy)
                if leg_len < MIN_LEG_LEN:
                    continue
                vert = hip[1] - ank[1]   # y down; ankle above hip ⇒ >0
                frac = vert / leg_len
                if frac <= 0.0:
                    continue
                vals.append(min(frac, 1.0))
    cov = {"n_legs": len(vals)}
    if not vals:
        return float("nan"), cov
    return float(np.nanmedian(vals) * 100.0), cov


# ─────────────────────────────────────────────────────────────────────────
# Assembly
# ─────────────────────────────────────────────────────────────────────────

def _nan_to_none(x: float) -> float | None:
    return None if (x is None or (isinstance(x, float) and math.isnan(x))) else round(float(x), 3)


def compute_choreography(set_dir: str) -> dict | None:
    """Compute all HF variables for one set with honest status/coverage/caveat.

    Returns a dict ready for JSON serialization, or None if no landmarks_multi.
    Does NOT return an absolute predicted score — see module docstring.
    """
    frames = load_multi_frames(set_dir)
    if not frames:
        return None
    fps = _infer_fps(frames)
    fw, fh = video_resolution(set_dir)

    mf_val, mf_cov = movement_frequency(frames, fps=fps)
    rot_val, rot_cov = rotation_frequency(frames)
    lad_val, lad_cov = leg_angle_deviation(frames, frame_w=fw, frame_h=fh)
    mpd_val, mpd_cov, mpd_conf = mean_pattern_duration(frames, fps=fps)
    lhi_val, lhi_cov = leg_vertical_extension(frames)

    def mk(key, val, cov, status, confidence, caveat, comparable=False):
        b = YUE_BENCHMARK[key]
        return HFVariable(
            key=key, value=_nan_to_none(val), unit=b["unit"], status=status,
            confidence=confidence, coverage=cov, caveat=caveat,
            benchmark_intl=b["intl"], benchmark_top5=b["top5"],
            paper_beta=b["beta"], comparable_to_paper=comparable,
        )

    variables = [
        mk("movement_frequency", mf_val, mf_cov, "validated",
           ("high" if mf_val == mf_val else "n/a"),
           "Relative cross-clip index, not absolute Hz. Thresholds hand-set, not "
           "calibrated to hand counts. NaN ⇒ legs never visible."),
        mk("rotation_frequency", rot_val, rot_cov, "caveat",
           ("low" if rot_val == rot_val else "n/a"),
           "Relative index. Oblique side view foreshortens horizontal-plane "
           "rotation; handheld shake inflates it. Weight by tracked_seconds."),
        mk("leg_angle_deviation", lad_val, lad_cov, "caveat",
           ("low" if lad_val == lad_val else "n/a"),
           "Relative index, ~2x paper's absolute degrees (image-vertical ≠ water "
           "horizontal, no horizon calibration). NaN when <8 clean legs / ankles "
           "underwater."),
        mk("mean_pattern_duration", mpd_val, mpd_cov, "exploratory", mpd_conf,
           "EXPLORATORY only. Measures rearrangement of visible body centroids, "
           "NOT true 8-swimmer formations (80%+ slots have zero visible "
           "keypoints). Floor-pinned + camera-orientation confounded. Not "
           "comparable to Yue's 6.15 s."),
        mk("leg_height_index", lhi_val, lhi_cov, "excluded", "n/a",
           "EXCLUDED. Paper's water-relative AB/AC is unrecoverable without a "
           "water line; the naive proxy is anti-correlated (r=-0.376) with real "
           "leg lift. Value shown is a different 'vertical extension fraction' "
           "construct, NOT leg_height_index, and is excluded from any score."),
    ]

    return {
        "set": os.path.basename(set_dir.rstrip("/")),
        "fps": round(fps, 2),
        "resolution": {"w": fw, "h": fh},
        "n_frames": len(frames),
        "variables": [asdict(v) for v in variables],
        "composite_note": (
            "No absolute 'predicted Yue total score' is exported: the published "
            "betas were fit on calibrated Kinovea inputs on a different scale. "
            "Use rank_sets() for a RELATIVE cross-clip z-score index from the "
            "surviving variables (movement_frequency, rotation_frequency, "
            "leg_angle_deviation) only."
        ),
        "paper": "Yue et al. 2023, Nature Scientific Reports 13:21303 (R²=0.762)",
    }


def rank_sets(data_dir: str, set_names: list[str] | None = None) -> dict:
    """Relative cross-clip composite — z-score each surviving variable across the
    given sets, then a beta-weighted composite (sign per Yue's regression
    direction). This is the ONLY ranking we export, and it is explicitly a
    relative ordering of OUR OWN clips, not a Yue-scale absolute score.
    """
    if set_names is None:
        set_names = sorted(
            d for d in os.listdir(data_dir)
            if d.startswith("set_") and os.path.isdir(os.path.join(data_dir, d))
        )
    per_set: dict[str, dict] = {}
    for name in set_names:
        rep = compute_choreography(os.path.join(data_dir, name))
        if rep is None:
            continue
        vals = {v["key"]: v["value"] for v in rep["variables"]}
        per_set[name] = vals

    # Gather per-variable arrays for z-scoring (only COMPOSITE_VARIABLES).
    cols: dict[str, list] = {k: [] for k in COMPOSITE_VARIABLES}
    for name in per_set:
        for k in COMPOSITE_VARIABLES:
            cols[k].append(per_set[name].get(k))

    stats: dict[str, dict] = {}
    for k, arr in cols.items():
        a = np.array([x if x is not None else np.nan for x in arr], dtype=float)
        mean = float(np.nanmean(a)) if np.isfinite(a).any() else float("nan")
        std = float(np.nanstd(a)) if np.isfinite(a).any() else float("nan")
        stats[k] = {"mean": mean, "std": std}

    ranking = []
    for name, vals in per_set.items():
        z_terms, composite = {}, 0.0
        n_used = 0
        for k in COMPOSITE_VARIABLES:
            v = vals.get(k)
            s = stats[k]
            if v is None or not math.isfinite(s["std"]) or s["std"] <= 0:
                z_terms[k] = None
                continue
            z = (v - s["mean"]) / s["std"]
            # apply Yue's directional sign: positive beta ⇒ higher is better;
            # negative beta (leg_angle_deviation) ⇒ lower is better.
            beta = YUE_BENCHMARK[k]["beta"]
            composite += math.copysign(1.0, beta) * z
            z_terms[k] = round(z, 3)
            n_used += 1
        ranking.append({
            "set": name,
            "z": z_terms,
            "composite": (round(composite, 3) if n_used else None),
            "n_variables_used": n_used,
        })

    ranking.sort(key=lambda r: (r["composite"] is None, -(r["composite"] or 0.0)))
    return {
        "variables": list(COMPOSITE_VARIABLES),
        "n_sets": len(per_set),
        "stats": stats,
        "ranking": ranking,
        "note": ("Relative cross-clip composite (beta-signed z-scores of surviving "
                 "variables). NOT a Yue-scale absolute score. Excludes "
                 "leg_height_index (anti-correlated) and mean_pattern_duration "
                 "(framing-confounded)."),
    }
