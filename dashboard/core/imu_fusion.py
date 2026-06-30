"""IMU 融合 — 脚踝/小腿传感器校准 + 腿部动力学指标 + 视觉补盲。

为什么需要(项目灵魂):
  花样游泳视觉最崩的就是倒立/入水段(检测器找不到头肩锚点),而那一刻腿正好
  出水、戴着脚踝/小腿 IMU。IMU 测的是真实物理运动(加速度/角速度),**完全
  不受水下折射影响**,在视觉盲区里反而最可靠。

本模块:
  1. calibrate_from_rest  — 从一次静止站立标定算 校准参数(去陀螺零偏 + 把重力
     方向旋到解剖系竖直长轴);校准方法此前在 set_004 验证过。
  2. apply_calibration    — 把原始 IMU 旋到解剖系 + 去重力得线性加速度。
  3. leg_dynamics         — 算花游有意义、视觉测不准的腿部指标:打腿/踩水频率、
     摆动幅度、动作强度。

约定:解剖系 +Z = 沿小腿竖直长轴(站立时),X/Y 为水平面(yaw 未标定,见下方注释)。
"""
from __future__ import annotations

import numpy as np

# 站立标定的默认值(总统大人测的脚踝/小腿传感器:重力在 +Y,陀螺静止零偏)。
# 实际使用时应每次录制前重新标定 5 秒静止,覆盖这两个常量。
DEFAULT_REST_ACC = (-0.02, 0.98, 0.09)
DEFAULT_REST_GYRO = (1.8, 0.5, -1.8)


def _rot_align(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """最短旋转(Rodrigues):把单位向量 a 旋到 b。"""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    s = np.linalg.norm(v)
    if s < 1e-9:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1 - c) / (s * s))


def calibrate_from_rest(rest_acc=DEFAULT_REST_ACC,
                        rest_gyro=DEFAULT_REST_GYRO) -> dict:
    """从静止站立读数算校准参数。

    Args:
        rest_acc:  (ax,ay,az) 静止时加速度(重力方向,单位 g)。
        rest_gyro: (gx,gy,gz) 静止时陀螺读数(理论应为 0,即零偏)。
    Returns:
        {"gyro_bias": (3,), "R": (3,3)}  R 把传感器系旋到解剖系(+Z=竖直长轴)。
    """
    g = np.asarray(rest_acc, dtype=float)
    R = _rot_align(g / np.linalg.norm(g), np.array([0.0, 0.0, 1.0]))
    return {"gyro_bias": np.asarray(rest_gyro, dtype=float), "R": R}


def apply_calibration(acc: np.ndarray, gyro: np.ndarray, calib: dict):
    """把原始 IMU 旋到解剖系、去陀螺零偏、去重力。

    Args:
        acc:  (N,3) 原始加速度(g)。
        gyro: (N,3) 原始角速度(deg/s)。
        calib: calibrate_from_rest 的返回。
    Returns:
        acc_anat (N,3), gyro_anat (N,3, 已去偏), lin_acc (N,3, 已去重力)。
    """
    R = calib["R"]
    acc_a = (R @ np.asarray(acc, float).T).T
    gyro_a = (R @ (np.asarray(gyro, float) - calib["gyro_bias"]).T).T
    lin = acc_a - np.array([0.0, 0.0, 1.0])
    return acc_a, gyro_a, lin


def leg_dynamics(gyro_anat: np.ndarray, lin_acc: np.ndarray,
                 fps: float) -> dict:
    """腿部动力学指标(视觉测不准、IMU 准)。

    - kick_freq_hz:  打腿/踩水频率 = 主摆动轴角速度的主频(FFT 去直流后峰值)。
    - peak_rate_dps: 最大摆速 = 主轴角速度峰值(°/s)。
    - rms_rate_dps:  平均剧烈度 = 主轴角速度 RMS(°/s)。
    - intensity_g:   动作强度 = 线性加速度模长 RMS。
    - main_axis:     主摆动轴(fwd/lat/vert)。

    注:幅度刻意用角速度统计而非积分出的角度——稀疏/断连采样下积分会漂移、
    不可信(set_004 的 511° 就是这么来的);峰值/RMS 不漂移,且直接反映力度。
    """
    g = np.asarray(gyro_anat, float)
    n = len(g)
    if n < 8 or fps <= 0:
        return {"kick_freq_hz": 0.0, "peak_rate_dps": 0.0, "rms_rate_dps": 0.0,
                "intensity_g": 0.0, "main_axis": "n/a"}
    main = int(np.argmax(g.var(axis=0)))   # 方差最大轴 = 主摆动平面
    w = g[:, main]
    # 频率:Hann 窗 FFT,忽略 <0.3Hz 的漂移
    w0 = (w - w.mean()) * np.hanning(n)
    spec = np.abs(np.fft.rfft(w0))
    freqs = np.fft.rfftfreq(n, 1.0 / fps)
    valid = freqs > 0.3
    freq = (float(freqs[valid][np.argmax(spec[valid])])
            if valid.any() and spec[valid].size else 0.0)
    peak_rate = float(np.abs(w).max())
    rms_rate = float(np.sqrt((w ** 2).mean()))
    intensity = float(np.sqrt((np.asarray(lin_acc, float) ** 2).sum(axis=1).mean()))
    return {"kick_freq_hz": round(freq, 2),
            "peak_rate_dps": round(peak_rate, 0),
            "rms_rate_dps": round(rms_rate, 0),
            "intensity_g": round(intensity, 2),
            "main_axis": ["fwd", "lat", "vert"][main]}
