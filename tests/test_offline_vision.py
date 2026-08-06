"""Tests for the offline vision analysis pipeline (DEVLOG #37 pivot:
no live inference — all vision runs post-recording via analyze_set)."""

import csv
import json
import os
import time

import cv2
import numpy as np
import pytest

from fastapi_app import offline_vision
from fastapi_app.yolo_pose import _Landmark, _empty_mp33

N_FRAMES = 10
FPS = 25.0


def _make_set(tmp_path, with_vision_csv=True, base_ts=1000.0):
    """Synthetic set dir: tiny video + recorder-style vision.csv."""
    set_dir = tmp_path / "set_099_test"
    set_dir.mkdir()
    vw = cv2.VideoWriter(str(set_dir / "video.mp4"),
                         cv2.VideoWriter_fourcc(*"mp4v"), FPS, (64, 48))
    for i in range(N_FRAMES):
        frame = np.full((48, 64, 3), i * 20, dtype=np.uint8)
        vw.write(frame)
    vw.release()

    if with_vision_csv:
        with open(set_dir / "vision.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp_local", "frame", "joint", "angle_deg",
                        "visible", "fps"])
            for i in range(N_FRAMES):
                w.writerow([f"{base_ts + i / FPS:.6f}", i + 1, "R_Elbow",
                            "0.00", 0, f"{FPS:.1f}"])
    return set_dir


class _StubDetector:
    """One person with a confident right arm (elbow angle computable)."""

    def __init__(self, fail_at_frame=None):
        self.calls = 0
        self.fail_at_frame = fail_at_frame
        self.reset_calls = 0

    def reset_tracking(self):
        self.reset_calls += 1

    def detect(self, frame, w, h):
        self.calls += 1
        if self.fail_at_frame is not None and self.calls == self.fail_at_frame:
            raise RuntimeError("boom")
        mp33 = _empty_mp33()
        mp33[12] = _Landmark(0.60, 0.30, 0.95)   # right shoulder
        mp33[14] = _Landmark(0.65, 0.45, 0.90)   # right elbow
        mp33[16] = _Landmark(0.60, 0.60, 0.85)   # right wrist
        return [mp33], [5]


def test_analyze_rewrites_files_and_keeps_timestamps(tmp_path):
    set_dir = _make_set(tmp_path, base_ts=1000.0)
    stub = _StubDetector()
    summary = offline_vision.analyze_set(str(set_dir), detector=stub)

    assert summary["frames"] == N_FRAMES
    assert summary["detection_pct"] == 100.0
    assert summary["unique_track_ids"] == 1
    assert summary["timestamps_reused"] is True
    assert stub.reset_calls == 1

    # vision.csv: 1:1 rows, ORIGINAL wall-clock timestamps preserved
    # (the IMU-alignment anchor), elbow now visible.
    rows = list(csv.DictReader(open(set_dir / "vision.csv")))
    assert len(rows) == N_FRAMES
    assert float(rows[0]["timestamp_local"]) == pytest.approx(1000.0)
    assert float(rows[9]["timestamp_local"]) == pytest.approx(1000.0 + 9 / FPS)
    assert rows[0]["visible"] == "1"
    assert float(rows[0]["angle_deg"]) > 0

    # landmarks.csv: 1:1 with frames, stub keypoints present
    lm_rows = list(csv.DictReader(open(set_dir / "landmarks.csv")))
    assert len(lm_rows) == N_FRAMES

    # JSONL: one row per frame with the stub's person + track id
    recs = [json.loads(l) for l in open(set_dir / "landmarks_multi.jsonl")]
    assert len(recs) == N_FRAMES
    assert all(len(r["persons"]) == 1 for r in recs)
    assert all(r["ids"] == [5] for r in recs)

    # atomicity: no tmp litter
    assert not [p for p in os.listdir(set_dir) if p.endswith(".tmp")]


def test_analyze_without_recorded_timestamps(tmp_path):
    set_dir = _make_set(tmp_path, with_vision_csv=False)
    summary = offline_vision.analyze_set(str(set_dir),
                                         detector=_StubDetector())
    assert summary["timestamps_reused"] is False
    rows = list(csv.DictReader(open(set_dir / "vision.csv")))
    assert len(rows) == N_FRAMES
    # synthetic timeline starts at 0 and steps by 1/fps
    assert float(rows[1]["timestamp_local"]) == pytest.approx(1 / FPS)


def test_analyze_failure_leaves_original_files_untouched(tmp_path):
    set_dir = _make_set(tmp_path, base_ts=2000.0)
    before = open(set_dir / "vision.csv").read()
    with pytest.raises(RuntimeError, match="boom"):
        offline_vision.analyze_set(str(set_dir),
                                   detector=_StubDetector(fail_at_frame=3))
    assert open(set_dir / "vision.csv").read() == before
    assert not (set_dir / "landmarks.csv").exists()  # never existed
    assert not [p for p in os.listdir(set_dir) if p.endswith(".tmp")]


def test_timestamp_row_count_mismatch_synthesizes(tmp_path):
    """vision.csv rows drifted far from video frames → per-index reuse
    would mis-stamp frames; the whole timeline must be synthesized
    from the first known wall-clock stamp instead."""
    set_dir = _make_set(tmp_path, with_vision_csv=False)
    with open(set_dir / "vision.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_local", "frame", "joint", "angle_deg",
                    "visible", "fps"])
        for i in range(30):   # 3× the video's 10 frames
            w.writerow([f"{2000.0 + i / FPS:.6f}", i + 1, "R_Elbow",
                        "0.00", 0, f"{FPS:.1f}"])
    summary = offline_vision.analyze_set(str(set_dir),
                                         detector=_StubDetector())
    assert summary["timestamps_reused"] is False
    rows = list(csv.DictReader(open(set_dir / "vision.csv")))
    assert len(rows) == N_FRAMES
    # synthesized from the first recorded stamp, monotonic 1/fps steps
    assert float(rows[0]["timestamp_local"]) == pytest.approx(2000.0)
    assert float(rows[3]["timestamp_local"]) == pytest.approx(2000.0 + 3 / FPS)


def test_torn_last_row_keeps_timestamp_prefix(tmp_path):
    set_dir = _make_set(tmp_path, base_ts=3000.0)
    with open(set_dir / "vision.csv", "a", newline="") as f:
        f.write("garbage-not-a-float,")   # torn final line (crash mid-flush)
    summary = offline_vision.analyze_set(str(set_dir),
                                         detector=_StubDetector())
    assert summary["timestamps_reused"] is True
    rows = list(csv.DictReader(open(set_dir / "vision.csv")))
    assert float(rows[0]["timestamp_local"]) == pytest.approx(3000.0)


class _TruncatingCapture:
    """Wraps a real VideoCapture but fails decode after N frames —
    simulates a video with a corrupt tail (declared frames > decodable)."""

    def __init__(self, real_cap_cls, path, decode_limit=6):
        self._cap = real_cap_cls(path)
        self._limit = decode_limit
        self._served = 0

    def isOpened(self):
        return self._cap.isOpened()

    def get(self, prop):
        return self._cap.get(prop)

    def read(self):
        if self._served >= self._limit:
            return False, None
        self._served += 1
        return self._cap.read()

    def release(self):
        self._cap.release()


def test_partial_decode_refuses_to_overwrite(tmp_path, monkeypatch):
    """A video whose tail fails to decode (3 of 10 declared frames —
    beyond the max(5, 2%) drift tolerance) must NOT commit short files
    over the set's only copy of recorded landmarks (1:1 invariant,
    DEVLOG #13)."""
    set_dir = _make_set(tmp_path, base_ts=5000.0)
    before = open(set_dir / "vision.csv").read()
    real_cap_cls = cv2.VideoCapture   # capture BEFORE patching (shared module)
    monkeypatch.setattr(
        offline_vision.cv2, "VideoCapture",
        lambda path: _TruncatingCapture(real_cap_cls, path, decode_limit=3),
    )
    with pytest.raises(RuntimeError, match="decoded only 3/10"):
        offline_vision.analyze_set(str(set_dir), detector=_StubDetector())
    assert open(set_dir / "vision.csv").read() == before
    assert not [p for p in os.listdir(set_dir) if p.endswith(".tmp")]


def test_unreadable_video_refuses_to_overwrite(tmp_path):
    set_dir = _make_set(tmp_path, base_ts=4000.0)
    (set_dir / "video.mp4").write_bytes(b"not a real mp4 file")
    before = open(set_dir / "vision.csv").read()
    with pytest.raises(RuntimeError):
        offline_vision.analyze_set(str(set_dir), detector=_StubDetector())
    assert open(set_dir / "vision.csv").read() == before
    assert not [p for p in os.listdir(set_dir) if p.endswith(".tmp")]


def test_analyze_missing_video_raises(tmp_path):
    empty = tmp_path / "set_100_novideo"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        offline_vision.analyze_set(str(empty), detector=_StubDetector())


def _wait_for(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_job_registry_lifecycle(tmp_path, monkeypatch):
    set_dir = _make_set(tmp_path)
    monkeypatch.setattr(
        offline_vision, "analyze_set",
        lambda sd, progress_cb=None, **kw: (
            progress_cb and progress_cb(N_FRAMES, N_FRAMES),
            {"frames": N_FRAMES, "detection_pct": 100.0},
        )[1],
    )
    started, _ = offline_vision.start_job("set_099_test", str(set_dir))
    assert started
    assert _wait_for(
        lambda: offline_vision.job_status("set_099_test")["state"] == "done"
    )
    st = offline_vision.job_status("set_099_test")
    assert st["progress"] == 100
    assert st["summary"]["frames"] == N_FRAMES
    assert offline_vision.job_status("set_phantom") == {"state": "idle"}


def test_job_registry_rejects_concurrent_runs(tmp_path, monkeypatch):
    set_dir = _make_set(tmp_path)
    release = {"go": False}

    def slow_analyze(sd, progress_cb=None, **kw):
        while not release["go"]:
            time.sleep(0.01)
        return {"frames": 1}

    monkeypatch.setattr(offline_vision, "analyze_set", slow_analyze)
    started, _ = offline_vision.start_job("set_a", str(set_dir))
    assert started
    started2, reason = offline_vision.start_job("set_b", str(set_dir))
    assert not started2
    assert "set_a" in reason
    release["go"] = True
    assert _wait_for(
        lambda: offline_vision.job_status("set_a")["state"] == "done"
    )
