"""Tests for the 2026-07 dogfood fixes (Emily's v2 field test):

1. ``yolo_pose._apply_kpt_gate`` — hallucinated low-conf keypoints are
   zeroed at the source so they never reach the recorder or frontend.
2. ``CameraManager`` frame/inference decoupling — preview + recording
   frames keep flowing at camera rate even when the pose backend is
   slow or fails to initialise entirely.
"""

import time

import numpy as np
import pytest

from fastapi_app import camera_manager as cm
from fastapi_app.yolo_pose import (
    _apply_kpt_gate, _kpts_to_mp33, _Landmark, _empty_mp33,
)


# ---------------------------------------------------------------------------
# 1. keypoint confidence gate
# ---------------------------------------------------------------------------

def test_gate_zeroes_low_conf_points():
    mp33 = _empty_mp33()
    mp33[11] = _Landmark(0.5, 0.5, 0.9)    # confident shoulder — keep
    mp33[25] = _Landmark(0.4, 0.8, 0.05)   # hallucinated knee — drop
    mp33[27] = _Landmark(0.3, 0.9, 0.34)   # just under gate — drop
    out = _apply_kpt_gate(mp33, 0.35)
    assert out[11].visibility == 0.9
    assert (out[25].x, out[25].y, out[25].visibility) == (0.0, 0.0, 0.0)
    assert (out[27].x, out[27].y, out[27].visibility) == (0.0, 0.0, 0.0)


def test_gate_keeps_exact_threshold_and_empty_points():
    mp33 = _empty_mp33()
    mp33[12] = _Landmark(0.2, 0.2, 0.35)   # exactly at gate — keep
    out = _apply_kpt_gate(mp33, 0.35)
    assert out[12].visibility == 0.35
    # untouched empty slots stay zero and don't get replaced objects
    assert out[0].visibility == 0.0


def test_gate_disabled_when_min_conf_zero():
    mp33 = _empty_mp33()
    mp33[25] = _Landmark(0.4, 0.8, 0.01)
    out = _apply_kpt_gate(mp33, 0.0)
    assert out[25].visibility == 0.01


def test_kpts_to_mp33_maps_17_and_19_point_models():
    """Stock COCO (17) and Phase B swimmer-19 keypoints both map into
    the MP-33 layout; foot_index lands on MP slots 31/32."""
    w, h = 200, 100
    kp19 = np.zeros((19, 2), dtype=np.float32)
    kp19[0] = (100, 10)     # nose
    kp19[16] = (120, 80)    # right_ankle
    kp19[17] = (60, 95)     # left_foot_index
    kp19[18] = (140, 95)    # right_foot_index
    conf = np.full(19, 0.9, dtype=np.float32)
    mp33 = _kpts_to_mp33(kp19, conf, w, h)
    assert mp33[0].x == pytest.approx(0.5)          # nose
    assert mp33[28].y == pytest.approx(0.8)         # right_ankle → MP 28
    assert mp33[31].x == pytest.approx(0.3)         # L foot_index → MP 31
    assert mp33[32].x == pytest.approx(0.7)         # R foot_index → MP 32

    # 17-kpt input: foot slots stay empty
    mp33_17 = _kpts_to_mp33(kp19[:17], conf[:17], w, h)
    assert mp33_17[31].visibility == 0.0
    assert mp33_17[32].visibility == 0.0

    # crop offset shifts back to full-frame coords
    shifted = _kpts_to_mp33(kp19, conf, w, h, x_offset=20, y_offset=5)
    assert shifted[0].x == pytest.approx(0.6)
    assert shifted[0].y == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# 2. CameraManager decoupling
# ---------------------------------------------------------------------------

class _FakeStream:
    """Drop-in for _MjpegStreamReader: synthesises frames at ~100 fps."""

    def __init__(self, url):
        self.url = url
        self.connected = True
        self.running = True
        self.seq = 0
        self._frame = np.zeros((48, 64, 3), dtype=np.uint8)
        import threading
        self._t = threading.Thread(target=self._tick, daemon=True)
        self._t.start()

    def _tick(self):
        while self.running:
            self._frame = np.random.randint(
                0, 255, (48, 64, 3), dtype=np.uint8
            )
            self.seq += 1
            time.sleep(0.01)

    def read(self):
        return True, self._frame.copy()

    def read_seq(self):
        return True, self._frame.copy(), self.seq

    def release(self):
        self.running = False


class _StubDetector:
    """Pose backend stub: one person, slow enough to lag the camera."""

    def __init__(self, delay=0.05):
        self.delay = delay
        self.calls = 0
        self._device = "stub"   # _infer_loop logs detector._device

    def detect(self, frame, w, h):
        self.calls += 1
        time.sleep(self.delay)
        mp33 = _empty_mp33()
        mp33[11] = _Landmark(0.4, 0.3, 0.9)
        mp33[12] = _Landmark(0.6, 0.3, 0.9)
        return [mp33], [7]

    def reset_tracking(self):
        pass


@pytest.fixture
def fake_stream(monkeypatch):
    monkeypatch.setattr(cm, "_MjpegStreamReader", _FakeStream)


def _wait_for(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_frames_flow_when_pose_backend_fails(fake_stream, monkeypatch):
    """Missing model weights must not take down preview/recording."""
    monkeypatch.setattr(cm, "load_config", lambda: {"hardware": {
        "pose_backend": "yolo",
        "yolo_model": "/nonexistent/never-downloaded.pt",
    }})
    mgr = cm.CameraManager(camera_url="fake://", rotation=0)
    mgr.start()
    try:
        assert _wait_for(lambda: mgr.get_latest() is not None)
        first = mgr.get_latest()
        assert first["jpeg"]
        assert first["raw_frame"] is not None
        # pose fields present but empty (backend init failed)
        assert first["landmarks"] == []
        assert first["person_count"] == 0
        assert first["angles"] is None
        # frames keep advancing — the whole point of decoupling
        seq0 = first["frame_seq"]
        assert _wait_for(lambda: mgr.get_latest()["frame_seq"] > seq0 + 5)
    finally:
        mgr.stop()


def test_slow_inference_does_not_block_frames(fake_stream, monkeypatch):
    """Camera at ~100fps + 50ms/frame inference: frame_seq must advance
    much faster than pose_seq, and the stale pose must stay attached."""
    monkeypatch.setattr(cm, "load_config", lambda: {"hardware": {
        "pose_backend": "yolo",
    }})
    import fastapi_app.yolo_pose as yp
    stub = _StubDetector(delay=0.05)
    monkeypatch.setattr(yp, "create_pose_detector", lambda **kw: stub)
    mgr = cm.CameraManager(camera_url="fake://", rotation=0)
    mgr.start()
    try:
        # wait until at least one pose landed
        assert _wait_for(
            lambda: (mgr.get_latest() or {}).get("person_count") == 1
        )
        data = mgr.get_latest()
        assert data["track_ids"] == [7]
        assert data["landmarks"][11][2] == 0.9
        assert data["pose_seq"] >= 0

        # Measure over a short window. The stub takes 50ms per detect,
        # so at most ~20 inferences fit in 1s — while the fake camera
        # produces ~100 frames. Decoupling means every camera frame
        # reaches _latest without waiting for an inference slot:
        # frames advanced must clearly exceed inferences performed.
        d0 = mgr.get_latest()
        calls0 = stub.calls
        time.sleep(1.0)
        d1 = mgr.get_latest()
        inferences = stub.calls - calls0
        frames_advanced = d1["frame_seq"] - d0["frame_seq"]
        assert frames_advanced > 30, frames_advanced   # ~100fps camera
        assert 0 < inferences <= 25, inferences        # bounded by 50ms delay
        assert frames_advanced > inferences * 2        # frames outpace inference
        # the pose attached to the newest frame may lag but never leads
        assert d1["pose_seq"] <= d1["frame_seq"]
    finally:
        mgr.stop()


def test_backend_none_skips_inference_entirely(fake_stream, monkeypatch):
    """DEVLOG #37 pivot: pose_backend='none' → camera+IMU only. Frames
    flow at camera rate, no inference thread is ever spawned, pose
    fields stay empty and error-free."""
    monkeypatch.setattr(cm, "load_config", lambda: {"hardware": {
        "pose_backend": "none",
    }})
    mgr = cm.CameraManager(camera_url="fake://", rotation=0)
    mgr.start()
    try:
        assert _wait_for(lambda: mgr.get_latest() is not None)
        data = mgr.get_latest()
        assert data["jpeg"]
        assert data["landmarks"] == []
        assert data["person_count"] == 0
        assert data["pose_error"] is None
        assert mgr._infer_thread is None       # never spawned
        seq0 = data["frame_seq"]
        assert _wait_for(lambda: mgr.get_latest()["frame_seq"] > seq0 + 5)
        mgr.reset_tracking()                   # safe no-op
    finally:
        mgr.stop()


def test_stop_is_clean(fake_stream, monkeypatch):
    monkeypatch.setattr(cm, "load_config", lambda: {"hardware": {
        "pose_backend": "yolo",
        "yolo_model": "/nonexistent/never-downloaded.pt",
    }})
    mgr = cm.CameraManager(camera_url="fake://", rotation=0)
    mgr.start()
    assert _wait_for(lambda: mgr.get_latest() is not None)
    mgr.stop()
    assert mgr.get_latest() is None
    # reset_tracking after stop must be a safe no-op
    mgr.reset_tracking()
