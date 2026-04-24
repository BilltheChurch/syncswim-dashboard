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

## 阶段六：Coach Workstation 完善（Dashboard 大升级） ✅ 已完成

目标：把 FastAPI "Coach Workstation" 打造成**专业级训练分析面板** — 实时监看、详细回放、多维评分、一站式管理。

### 6.1 后端 API 扩展
- [x] `/api/sets/{name}/report` 扩展字段：`imu_summary`, `duration`, `fps_mean`, `frame_count`, `vision_rows`, `score_breakdown`, `has_video`, `has_landmarks`
- [x] `/api/sets/{name}/timeseries` 返回重采样曲线（IMU 倾角 × N 节点 + 视觉角度 × 5 指标 + 肘关节）
- [x] `/api/sets/{name}/frame/{time_sec}` 按秒提取带骨架 JPEG
- [x] `/api/sets/{name}/video` 视频流（HTTP Range 请求支持）
- [x] `/api/sets/{name}/keyframes/{index}?count=3|6` 灵活关键帧
- [x] `DELETE /api/sets/{name}` 删除 Set（路径越权保护）
- [x] `/api/camera/snapshot?skeleton=0|1` 实时截图（服务端二次绘制骨架）
- [x] `POST /api/camera/test` 摄像头连接诊断（探测 JPEG 起始标记）
- [x] `/api/config` GET/POST 完整配置读写（三段深度合并）
- [x] `/api/ble/reconnect` 手动触发重连
- [x] `/api/data/stats` 数据目录统计（Set 数 / 总大小）

### 6.2 前端实时页增强
- [x] "快照"按钮（S 键，含 / 不含骨架，自动下载带时间戳文件名）
- [x] BLE 详细统计（频率 · 包数 · 倾角，双节点 A1+A2）
- [x] 实时综合评分环（SVG ring，动态渐变色）
- [x] 迷你三维条（姿态 / 平稳 / 对称）
- [x] 视频右下角「姿态检测中 / 无人」badge
- [x] 视频左上角实时 FPS 显示
- [x] 头部时钟 + BLE/CAM 状态点

### 6.3 前端分析页大升级
- [x] 5 格摘要头（时长 / 节点数 / 包数+丢包 / 帧数+FPS / 相关系数）
- [x] 视频播放器（Range-aware 流） + 骨架叠加开关
- [x] 时序折线图（Canvas 2D，多指标图例可点击切换）
- [x] 关键帧 3 ⇄ 6 切换
- [x] 多维评分分组卡（姿态 / 伸展 / 对称 / 运动）
- [x] 详细指标 8 项（含 FINA 扣分显示）
- [x] IMU 传感器数据卡（每节点 6 项统计 + 丢包率）
- [x] 一键删除（带确认模态框）
- [x] 加载骨架屏

### 6.4 新增「历史」Tab — Set 管理
- [x] Set 卡片网格（缩略图 / 评分 badge / 时长 / 日期 / 数据源 chips）
- [x] 实时搜索 + 排序（日期 / 时长 升降）
- [x] 单卡删除（模态框确认）
- [x] 点击进入分析页

### 6.5 前端设置页完善
- [x] 预填当前值（GET /api/config + GET /api/data/stats）
- [x] 相机「测试连接」按钮
- [x] FINA 阈值可视化编辑器（5 × 3 阈值，正/反向自动标记）
- [x] 数据目录统计（Set 数 / 总大小 / 路径）
- [x] BLE 节点名编辑
- [x] 键盘快捷键表

### 6.6 UI 视觉升级
- [x] 加载骨架屏（shimmer 动画）
- [x] Toast 通知系统（success/error/warn/info 四色 + 自动消失 + 手动关闭）
- [x] 模态框（Escape 取消 + 遮罩点击取消）
- [x] 键盘快捷键：`1/2/3/4` 切 Tab、`R` 录制、`Space` 停止、`S` 快照、`Esc` 关模态
- [x] 动画过渡：ring 填充 0.6s、bar 填充 0.4s、toast 滑入 0.3s、modal pop-in
- [x] 响应式：≥1100 / 860 / 680px 三档断点

### 6.7 文档
- [x] task.md 阶段六（本节）
- [x] DEVLOG 记录问题 #11（前后端契约）、#12（视频 Range）

### 6.8 回放修复（2026-04-22）
- [x] 修复分析页骨架比视频快的 drift（DEVLOG #13）
  - 根因：`main.py` 在未检测到姿态时跳过 `write_landmarks`，但视频帧仍在写；导致 `landmarks.csv` 比 `video.mp4` 少若干行，按比例映射后骨架提前。
  - 修复：`_vision_writer_loop` 现在每个视频帧都调用一次 `write_landmarks`（无姿态时写空行），保持 1:1 对齐。
- [x] 分析页支持多人骨架回放
  - 新增 `landmarks_multi.jsonl`：JSONL 格式，每行对应一帧，记录所有被检测到的运动员 landmarks。
  - `/api/sets/{name}/landmarks` 扩展返回 `all_frames` 字段。
  - 前端 `setupSkeletonOverlay` 使用与实时视图相同的 `TEAM_COLORS` 调色盘，绘制 P2/P3... 标签。
- [x] 时长 0s 回退
  - `/api/sets/{name}/report` 中若 IMU 无数据，依次回退到 vision.csv → landmarks.csv → `frame_count / fps`。无 IMU 的训练组也能显示真实时长。

## 阶段七：多人追踪 + 跨 Set 对比 + 微调前置 🚧 进行中

目标：把 Coach Workstation 从「单场会话」升级为「同一队员在多场训练间的纵向画像」。

**前提共识**：阶段六的 UI 全部基于离线想象 + 论文先验设计，没有真实泳池数据校验。所以本阶段的隐藏前置是 **7.0 真实数据采集**，第一场实训只囤素材不分析。

### 7.0 真实训练数据采集（推后到 7.2/7.3/7.4 准备工作完成后）
> 总统大人决定：先把 7.2/7.3/7.4 完整跑通，再上传一些已有的真实训练视频做实地验证 + YOLO 微调。
- [ ] 总统上传若干已录制的真实训练视频到 `data/raw_videos/`
- [ ] 整理 fine-tuning 流程文档（半监督预标注 → CVAT 修正 → ultralytics 训练 → OKS 评估）—— 由 7.4 一起产出

### 7.1 多人独立追踪（ByteTrack） — PR #2 ✅
- [x] [yolo_pose.py](fastapi_app/yolo_pose.py)：`.predict()` → `.track(persist=True, tracker='bytetrack.yaml')`，`detect()` 返回 `(persons, track_ids)`；新增 `reset_tracking()` 防 ID 跨 Set 泄漏
- [x] [camera_manager.py](fastapi_app/camera_manager.py)：在帧字典中新增 `track_ids: list[int]`，与 `all_landmarks` 平行；含防御性长度对齐
- [x] [recorder.py](fastapi_app/recorder.py)：`write_landmarks_multi(local_ts, frame, all_landmarks, track_ids=None)`；JSONL 每行新增并行 `ids` 字段（旧文件无 ids 也兼容）
- [x] [main.py](fastapi_app/main.py)：`_vision_writer_loop` 把 `data["track_ids"]` 透传；`start_recording()` 后调 `reset_tracking()`
- [x] [api_routes.py](fastapi_app/api_routes.py)：`/api/sets/{name}/landmarks` 返回 `all_ids`；`ws_video.py` 实时推送 `track_ids`
- [x] 前端 `setupSkeletonOverlay`：色板按 `track_id % len(TEAM_COLORS)`，标签 `#3`；与实时页 `drawSkeletonOnCanvas` / `drawSecondaryPose` 共享三层 fallback
- [x] 实时页骨架覆盖层：主角头顶 `#3` 角标；队友按 ID 配色 + `#id` 标签
- [x] DEVLOG #25 记录"为什么追踪 ID 是横向对比的前提"

### 7.2 运动员名 ↔ track_id 映射 — PR #2 ✅
- [x] `data/athletes.json`：`{id, name, color, bindings: [{set, track_id}], created_at}` + 原子写 + threading.Lock + forward-compat
- [x] `/api/athletes` GET / POST / PATCH / DELETE / bind / unbind（unbind 用 POST 而不是 DELETE-with-body，避开 httpx + 代理兼容性坑）
- [x] `/api/sets/{name}/landmarks` 额外返回 `athlete_map: {track_id_str: {athlete_id, name, color}}`
- [x] 分析页「队员管理」模态：聚合本 set 出现过的所有 unique track_id → 选 athlete or 新建 → bind/unbind
- [x] 三层 fallback `colourFor / labelFor`：athlete binding > track_id 配色 > 数组顺序
- [x] in-place `_activeOverlay.landmarks.athlete_map` mutation 避免 setupSkeletonOverlay 重入累计事件
- [x] athlete_store 单元 smoke（9 边界场景）+ FastAPI TestClient 集成 smoke（11 assertions）
- [x] DEVLOG #26

### 7.3 跨 Set 趋势对比页 — PR #2 ✅
- [x] `/api/compare?sets=name1,name2,...` 多 Set 批量获取 slim report（最多 20 个，phantom set 单独标 error 不阻塞）
- [x] `/api/athletes/{id}/sets` 列出运动员的所有 binding
- [x] 前端新增第 4 个 Tab「对比」（原设置由 4 → 5）：
  - [x] 顶部筛选：运动员下拉（"全部"/已注册队员）+ 最近 N 组（5/10/20）
  - [x] Set chips 多选（默认前 6 个，避免雷达图过于拥挤）
  - [x] 雷达图叠加：取所有选中 Set 的共有指标（intersect），每组一个多边形 + 图例
  - [x] 单指标平行折线：可切换指标（综合评分 / 任一交集指标），横轴按录制时间升序
  - [x] 颜色策略：同一运动员的多场训练用 athlete.color 形成视觉聚簇
- [x] 键盘快捷键 1/2/3/4/5 映射更新；设置页快捷键文档同步
- [x] DEVLOG #27

### 7.4 微调 YOLO — 准备工作完成 ✅，实际训练等 7.0
- [x] [tools/preannotate.py](tools/preannotate.py) — 半监督预标注（每 N 帧抽样、`--conf 0.3` 让 borderline 也进入预标）
- [x] [tools/train_pose.py](tools/train_pose.py) — 包装 ultralytics yolo pose train，augmentation 已针对水中场景调（mosaic 0.5、degrees 5、hsv_v 0.5）
- [x] [tools/eval_pose.py](tools/eval_pose.py) — 包装 yolo pose val，输出 mAP@50/50-95，注释里写明"评估集必须来自训练集没见过的场地"
- [x] [data/training/syncswim.yaml](data/training/syncswim.yaml) — ultralytics 配置（17 个 COCO keypoints + flip_idx 左右镜像）
- [x] [docs/fine-tuning.md](docs/fine-tuning.md) — 完整流程：囤素材 → 预标 → CVAT 修正 → 手动拆 train/val（避免 auto-split 把同视频相邻帧分两边）→ 训练 → 评估 → 部署
- [x] `.gitignore` 排除 `data/raw_videos/`、`data/training/{images,labels}/`、`runs/` 但保留 `syncswim.yaml`
- [x] DEVLOG #28
- [ ] **等 7.0 真实素材**：跑一次完整流程出第一个 `best.pt`，然后切换 `config.toml` 部署

## 阶段八：dogfood 前置 + 小型 UX/运维增强 🚧 进行中

目标：把"预录制视频"也能进系统；再补一批 dogfood 前后教练必用的小特性。

### 8.0 视频导入工具 — PR #3 ✅
- [x] [tools/import_video.py](tools/import_video.py)：mp4/mov/avi → 完整 set 包
- [x] 与 Recorder 共享 schema（_compute_angles、LANDMARK_NAMES、IMU_HEADER、VISION_HEADER），避免 drift
- [x] 产出：video.mp4（H.264 + faststart）+ vision.csv + landmarks.csv (1:1 video) + landmarks_multi.jsonl + 空 IMU CSV（触发 duration 回退链）
- [x] set 编号共享 live 空间；目录名加 `_imported_` 后缀一眼辨识
- [x] 端到端 smoke：5 不变量（6 文件齐全 / IMU header-only / vision 行数 / landmarks 1:1 video / JSONL 奇偶 detection 两路径均覆盖）
- [x] DEVLOG #29

### 8.1 实时页录制时绑定 athlete（A）— PR #4 ✅
- [x] [app.js](fastapi_app/static/app.js) 实时页加「队员」按钮 + `live-pending-badge` 计数
- [x] 模块级 `_liveSeenTrackIds` + `_pendingLiveBindings`：ws_video onmessage 聚合所有 unique track_id
- [x] `openLiveAthleteManager()` 复用 7.2 模态结构，绑定写到 pending 而非立即 POST
- [x] btn-stop 拿 `set_dir` basename → `flushLiveBindings()` 批量 POST `/api/athletes/{id}/bind`
- [x] btn-start 时清空 pending，badge 同步更新
- [x] DEVLOG #30

### 8.2 数据备份脚本（B）— PR #4 ✅
- [x] [tools/backup.py](tools/backup.py)：自动选 rsync / rclone backend，3 级 target 配置（CLI > env > `data/.backup_target`）
- [x] **永远 exit 0** + log 到 `data/.backup.log`，cron 不报错
- [x] rsync 用 `--delete-after --partial`：失败半途不丢数据
- [x] [docs/backup.md](docs/backup.md)：3 个常见方案（外置盘 / 云 / NAS）+ 监控 + 常见坑

### 8.3 历史 set 备注字段（C）— PR #4 ✅
- [x] `data/set_NNN_*/note.md`：free-form markdown
- [x] `/api/sets/{name}/note` GET / PUT（PUT 空文本 = 删除文件，保持"file 存在 = 有内容"不变量）
- [x] 原子写（tmp + os.replace）防写到一半进程崩
- [x] [app.js](fastapi_app/static/app.js) 分析页顶部加备注卡：textarea + 保存/还原按钮 + meta 显示更新时间
- [x] FastAPI TestClient 7 assertions（phantom 404 / empty 默认 / PUT-GET 往返 / whitespace 删除 / 空 idempotent / 原子写不留 .tmp）

### 8.4 PDF 报告导出（D）— PR #5 ✅
- [x] [tools/export_pdf.py](tools/export_pdf.py)：standalone CLI，3 页 A4（封面+雷达 / 详细指标+关键帧 / 备注+IMU）
- [x] **不引入 weasyprint** — 用项目已有的 matplotlib PdfPages，避开 `brew install pango/cairo` 等 native deps
- [x] CJK 字体 fallback 链：Heiti TC → Hiragino Sans GB → Songti SC → Noto Sans CJK SC → Microsoft YaHei → sans-serif
- [x] `_normalize_for_radar()` 与前端 JS `normalizeForRadar` 对齐，PDF 雷达图与 dashboard 一致
- [x] `GET /api/sets/{name}/report.pdf` 端点：lazy import + ValueError → 404 + ImportError → 503
- [x] 分析页视频卡片头部加 `<a id="vp-pdf-btn">PDF</a>`（绿色 hover），新窗口下载
- [x] FastAPI TestClient smoke：phantom 404 + real set 返回 130 KB application/pdf
- [x] DEVLOG #31

### 8.5 录制中打标（E）— PR #7
- [ ] 实时页按 `M` → 在当前时间点插一个标记
- [ ] `data/set_*/markers.csv`：`timestamp, label, note`
- [ ] 回放时间轴上显示标记点，点击跳转

### 8.6 自动趋势告警（F）— PR #7 或独立
- [ ] 规则引擎：指标连续 N 场单调下降 / 超出阈值 → 告警
- [ ] 告警面板（对比页 / 历史页入口）
- [ ] 可选：Slack / Telegram webhook 推送（配置在 settings）

## 硬件配置
- M5StickC Plus2 x2 (NODE_A1 前臂 / NODE_A2 小腿)
- IMU: 内置 MPU6886, 实测 72.5Hz（零丢包零重复）
- BLE 协议: 二进制批量打包，3 读数/通知，52 字节/包
- BLE UUID: SERVICE=12345678-1234-1234-1234-123456789abc, CHAR=abcd1234-ab12-cd34-ef56-abcdef123456
