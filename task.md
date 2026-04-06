# 单设备完整流程 - 任务跟踪

## 项目目标
一个人戴一个 IMU 节点，手机拍视频，电脑端实时接收两路数据，能录制、能回放、能看到 IMU 和视觉的角度对比。

## 阶段一：数据采集管道（Python端 BLE 接收+存储） ✅ 已完成
- [x] BLE 扫描脚本 (scan_ble.py)
- [x] BLE 接收脚本 (receive_ble.py)
- [x] 固件频率优化 (~31Hz → ~86Hz → 72.5Hz 无重复)
- [x] 固件 volatile 修复 BLE 连接状态显示
- [x] 固件 BLE 断开后自动重新广播
- [x] 二进制批量协议（3 读数/包，丢包率 0%）
- [x] 定时采样门控（消除 33.9% 重复数据）
- [x] 完整录制脚本 (recorder.py)
  - [x] BLE 数据接收（二进制协议解析）
  - [x] REC/IDLE 状态自动分段
  - [x] 每个 Set 存独立 CSV（文件名带组号+时间戳）
  - [x] 终端仪表盘（连接状态、组号、录制时长、实时速率）
  - [x] 断线自动重连
  - [x] 丢包检测
  - [x] 优雅退出（signal handler）
- [x] 端到端验证：按 Button A 开始/停止，自动生成干净 CSV
- **最终指标**：72.5Hz / 0% 丢包 / 0% 重复 / 最大间隔 23ms

## 阶段二：视觉采集管道（IP摄像头 + MediaPipe 骨骼） ✅ 已完成
- [x] DroidCam (iOS) → MJPEG 手动流解析（绕过 OpenCV macOS ARM HTTP 限制）
- [x] MediaPipe PoseLandmarker (tasks API, lite 模型)
- [x] 计算右肘关节角度（shoulder→elbow→wrist）
- [x] 画面叠加骨骼线 + 关节角度数值
- [x] 按 R 录制，每帧角度数据存 CSV
- [x] 按 F 旋转画面适配手机竖放
- [x] 独立验证：~26 FPS，角度范围 74°-153°，全程可见
- **最终指标**：26 FPS / 全程骨骼检测 / 微秒级时间戳

## 阶段三：双源同步录制 ✅ 已完成
- [x] BLE 线程 + 视频线程合并到 sync_recorder.py
- [x] 两路数据用电脑本地时间戳标记
- [x] Button A 触发两路同时录制/停止
- [x] 同一 Set 文件夹存 IMU CSV + 视觉 CSV
- [x] OSD 显示双源状态（BLE 连接、录制、频率、角度）
- **同步精度**：起始偏移 8.8ms，时长差 17.6ms

## 阶段四：基础分析验证 ✅ 已完成
- [x] 读取 Set 的 IMU CSV + 视觉 CSV (analyze.py)
- [x] 基于本地时间戳对齐（两路共享 time.time()）
- [x] IMU 加速度计 → 倾斜角，MediaPipe → 肘关节角度
- [x] 归一化叠加对比曲线 + 相关系数
- [x] 三图输出 + analysis.png 保存
- **验证结果**：相关系数 -0.497（负相关，符合物理：肘角↑ = 前臂倾斜↓），两路信号同步响应同一动作

## 数据目录结构
```
data/
  set_001_20260319_143025/
    imu_NODE_A1.csv      # 阶段一
    vision.csv           # 阶段二
    sync_log.csv         # 阶段三
  set_002_20260319_143112/
    ...
```

## 阶段五：花泳姿态检测升级（双IMU + 视觉融合） ✅ 已完成
- [x] 双 IMU 数据加载器（NODE_A1 前臂 + NODE_L1 小腿）
  - [x] load_imu(set_dir, node=) 支持按节点加载
  - [x] load_all_imus(set_dir) 扫描所有 IMU 文件
  - [x] build_sessions_index 自动检测所有 IMU 节点
  - [x] config.toml 新增 imu_nodes 和 node_placement
- [x] 视觉角度计算模块 (vision_angles.py)
  - [x] calc_leg_deviation_vision — Hip→Ankle 与垂直线夹角
  - [x] calc_knee_extension — Hip→Knee→Ankle 膝盖伸直度
  - [x] calc_shoulder_knee_angle — Shoulder→Hip→Knee 身体对齐
  - [x] calc_leg_symmetry — 左右腿偏差角之差
  - [x] calc_trunk_vertical — Shoulder→Hip 躯干垂直度
- [x] 分指标 FINA 扣分阈值
  - [x] compute_deduction 支持 metric= 参数
  - [x] 正向指标（偏差越小越好）和反向指标（角度越大越好）自动识别
  - [x] config.toml 新增 5 个分指标阈值配置
- [x] 8 指标评分引擎
  - [x] compute_set_report 支持 4 路数据源（前臂IMU、小腿IMU、视觉、骨骼）
  - [x] 新增指标：knee_extension、trunk_vertical、leg_symmetry
  - [x] 缺失数据源优雅降级（代理值 / 默认值）
  - [x] 双 IMU 融合：smoothness 和 stability 合并双节点数据
- [x] 双节点 IMU 波形图
  - [x] build_imu_waveform 支持第二节点叠加（虚线 + 不同颜色）
- [x] 训练页面 4-Tab 重构
  - [x] 概览：8 指标仪表盘（2行×4列）+ 阶段时间线
  - [x] 腿部分析：偏差角/伸直度/对称性时序图 + 小腿IMU融合
  - [x] 手臂分析：肩膝对齐/躯干垂直 + 骨骼叠加 + 前臂IMU融合
  - [x] 传感器融合：双节点波形叠加 + 数据质量 + 高级融合预留
- **测试覆盖**：91 个测试全部通过

## 硬件配置
- M5StickC Plus2 x1 (NODE_A1)
- IMU: 内置 MPU6886, 实测 72.5Hz（零丢包零重复）
- BLE 协议: 二进制批量打包，3 读数/通知，52 字节/包
- BLE UUID: SERVICE=12345678-1234-1234-1234-123456789abc, CHAR=abcd1234-ab12-cd34-ef56-abcdef123456
