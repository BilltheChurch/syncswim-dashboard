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
> Tim 老师决定：先把 7.2/7.3/7.4 完整跑通，再上传一些已有的真实训练视频做实地验证 + YOLO 微调。
- [ ] Tim 老师上传若干已录制的真实训练视频到 `data/raw_videos/`
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

### 8.5 录制中打标（E）— PR #6 ✅
- [x] 后端 `/api/sets/{name}/markers` GET/POST/DELETE，写到 `data/set_*/markers.csv`（ts_offset, label, note, created_at）
- [x] 实时页加「标记」按钮 + `M` 键 + `live-marker-badge` 暂存计数
- [x] `_pendingMarkers` 暂存模式（同 8.1 的 pending bindings）：录制中按 M 弹 prompt 输入 label，btn-stop 后批量 POST 到真实 set
- [x] 分析页 video card 下方加 `<div class="vp-marker-strip">` 三角形 + 标签，点击跳转 `video.currentTime`
- [x] 设置页快捷键文档同步：M = 在当前时间点打标记
- [x] FastAPI TestClient 11 assertions 含空批/blank label silently dropped/append/DELETE 清空

### 8.6 自动趋势告警（F）— PR #6 ✅
- [x] 后端 `_ALERT_RULES`：`explosive_power down × 3`、`leg_deviation up × 3`、`overall_score below 6.0 × 2`
- [x] `_apply_rule()` 分 down / up / below 三种 direction；window 不足时 silent skip
- [x] `/api/alerts` 扫所有 athletes 的 binding，按 `_set_date_key` 时间排序，每 athlete × 每 rule 一次评估
- [x] 对比页顶部 `<div id="cmp-alerts-banner">` 告警条：每条含 athlete pill + 消息 + 数值轨迹（`8.7 → 7.9 → 7.2`）
- [x] severity 分 warn (橙) / info (蓝)；空告警时整条 hidden 不显示空白

## 阶段九：YOLO 微调（dogfood 数据 → fine-tune）🚧 进行中

**起因**：第一次 dogfood (3 段真实花泳视频，DEVLOG #33) 发现 zero-cost trick 调到极限后召回率仍只有 ~36%，**5 个运动员 32 秒被发了 99 个 ID（19.8× 通胀）**。bytetrack 给同一运动员每秒换一次身份。tracker 没问题 — detector 召回不够，tracker 必崩。**fine-tune 从 nice-to-have 变成必须**。

### 9.0 dogfood 调参落地 — PR #7 ✅
- [x] `tools/import_video.py` 默认 `--conf 0.15 --imgsz 1280`（offline 用最高质量）
- [x] `fastapi_app/yolo_pose.py` 加 `imgsz` 构造参数（默认 640，向后兼容；live 录制保持 real-time）
- [x] DEVLOG #33（4 档实验数据 + 19.8× ID 通胀根因 + Phase A/B 决策）

### 9.1 Phase A — bbox detector fine-tune
**目标**：召回率 36% → >70%。

#### 9.1.0 工具链 + 标注文档 — PR #8 ✅
- [x] `tools/extract_frames.py`：均匀抽帧（每视频 N 帧，跳首尾 3% fade，无 inference）
- [x] `tools/train_detector.py`：YOLOv8s detect-only 微调封装（默认 imgsz=1280, batch=8, epochs=80, 池子调优 augmentation）
- [x] `tools/eval_detector.py`：与 baseline `yolov8s.pt` 同 val 对比，mAP@50 / 召回 / mAP@50-95，自动判定 ≥0.70 ✅
- [x] `data/training/phase_a/swimmer_det.yaml`：单类 detection（无 kpt_shape），路径相对约定
- [x] `fastapi_app/yolo_pose.py` 加 `HybridSwimmerDetector`（自训 detector + COCO keypoints）+ `create_pose_detector(...)` factory
- [x] `camera_manager.py` + `tools/import_video.py` 切换为 factory；`config.toml` 新增 `swimmer_detector` 注释项 + `yolo_imgsz`
- [x] `docs/phase-a-annotation.md`：CVAT 本地 Docker 部署、bbox 标注规则、快捷键、train/val 拆分约定、上线步骤、常见坑

#### 9.1.1 标注（**人工 1-2 小时**）— Tim 老师本周
- [ ] `python tools/extract_frames.py --per-video 50` → `data/training/phase_a/frames/` ~150 jpg
- [ ] 本地 CVAT Docker 拉起来 + 建项目 `syncswim-detector-phase-a` + 上传帧
- [ ] 标 ~150 帧 bbox（每个运动员 1 框，露出多少标多少；不标观众/教练）
- [ ] Export YOLO 1.1 → 解压到 `data/training/phase_a/labels/`
- [ ] 一行 `ls` 生成 train.txt + val.txt（hold-out 整个 `clip_horizontal`）

#### 9.1.2 训练 + 验证（自动 ~30 min）
- [ ] `python tools/train_detector.py` → `runs/detect/swimmer_det_v1/weights/best.pt`
- [ ] `python tools/eval_detector.py` → 看 mAP@50 是否 ≥ 0.70
- [ ] 不达标：再标 50-100 帧重训；< 0.50：检查标注规范

#### 9.1.3 上线 + 实测（开新 PR）
- [ ] `config.toml` 取消注释 `swimmer_detector = "runs/detect/.../best.pt"`
- [ ] 重新 import 3 dogfood 视频，看 ID 通胀从 19.8× 降到多少（期望 ≤ 3×）
- [ ] 浏览器分析页对比 set_002 (PR #7) vs set_新 (PR #8 后)，截图入 DEVLOG

### 9.2 Phase B — keypoint head fine-tune 🚧 训练管线已打通（2026-07-30，DEVLOG #37）
**目标**：让 keypoint 落到水里运动员**真实位置**（不是 COCO 模型猜的水下幻象）。
- [x] Emily 交接包：`tools/build_emily_phase_b_kit.py` 复用本机已完成的 Phase B crop 标准（橙色 `swimmer`、19 点、COCO Keypoints）。当前发给 Emily 的严格单人包仅保留裁剪范围内没有第二位已确认 swimmer、且有真实本机模型关键点预标注的 53 张 crop（41 个源帧、630 个可见点）；原 bbox 居中并占 crop 的 2/3，附 53 张真实已完成标注样例。
- [x] 本机 53 张 crop 的 19 点标注完成（CVAT job_4 导出 2026-07-16，水下点 visibility=0 规范执行）
- [x] **7/27 首次训练失败验尸**：`runs/pose/swimmer_pose_v1` 100 epochs box mAP 0.911 但 **pose mAP 全程 0**。
  三组探针二分定位根因：ultralytics 的 OKS 指数损失在关键点头全新初始化时梯度饱和
  （17→19 点头必须重建 → 初始预测离人太远 → exp(-e)≈0 → 永远学不动）
- [x] [tools/seed_pose19_head.py](tools/seed_pose19_head.py)：把 17 点预训练 cv4 头逐通道移植进 19 点头，
  脚尖通道用脚踝通道播种 → 探针 pose mAP 0 → **0.995**
- [x] [tools/sanitize_pose_labels.py](tools/sanitize_pose_labels.py)：CVAT 允许点标出 crop 边界，导出坐标越界
  → ultralytics 整图拒收（损失 13/53 张）。清洗：越界点置 invisible、bbox 裁回边界
- [x] [data/training/phase_b/](data/training/phase_b/swimmer_pose19.yaml)：53 crop 数据集（42 train / 11 val，
  整段隔离切分）、kpt_shape [19,3] + flip_idx（含 17↔18 脚尖对）
- [x] `tools/train_pose.py` 加 `--freeze/--patience/--base`（freeze=10 冻 backbone）
- [x] v1（mosaic 配方）早停失败 → 对照实验证明 **mosaic 饿死小数据姿态训练**（train_pose.py 默认已改 mosaic=0）
- [x] **v2 训练完成并部署**（244 epochs 早停；部署 last.pt——fitness 被 box 主导，best.pt 姿态头反而弱）：
  held-out val 肉眼验收通过（倒立/出水/垂直骨架落到真实肢体，COCO 全空白）；
  旧场地 set_008 全帧端到端成立；`[analysis] model` 已指向新权重
- [x] HybridSwimmerDetector 推理裁剪外扩 1.5×（匹配训练 crop 几何，否则 conf 掉出门控）
- [ ] **域差（已确认）**：Emily 新泳池 set_013 骨架仍缺失——训练 crop 全来自旧素材。
  解药 = 9.3：回收 Emily 53 张 + 新泳池素材补标重训
- [ ] 验证：`leg_deviation` / `knee_extension` 这些指标在 dogfood 视频上是否给出合理数值（不再是 NaN/0）

### 9.3 数据扩充
- [x] **新泳池标注包 v2（2026-08-04，DEVLOG #38）**：`emily_phase_b_swimmer19_crops_20260804.zip`
  - v1（94 crop）被总统大人打回：大量地砖误检 + 模糊 crop。教训：面积过滤挡不住大块地砖；
    锐度排序反而偏爱瓷砖缝直线；**QA 只抽两端不看全量 = 没有 QA**
  - v2 过滤管线：v2 检测器逐帧追踪 → 面积 ≥7000px²（新泳池框分布 p75）→ **肤色占比 ≥0.3%
    门控**（地砖/纯水花全部 0.00~0.04%，真人 0.32% 起跳，天然双峰）→ 锐度排序 + 帧间隔
    → **全量 46 张逐一目检通过**（零地砖零水花，含双脚特写等绷脚黄金素材）
  - 46 crop 中 38 张带 Phase B v2 权重预标注（398 个可见点种子，含脚尖）
  - 清晰度天花板 = 素材本身（机位远 + DroidCam 压缩）。**已知改进项：下次录制机位靠近 +
    1080p**，那是数据质量的治本
  - 原料存 `data/training/phase_b_newpool/`（帧+自动框标签，可复现）
- [x] **新泳池 46 张标注已回收（job_6，2026-08-04 总统大人亲标）**：216 点（93 occluded），
  CVAT 1.1 XML → YOLO-19 转换（bbox 取自 crop_manifest 的 `swimmer_bbox_in_crop_pixels`），
  sanitize 后与旧 53 张合并为 `data/training/phase_b_v3/`（99 张，81 train / 18 val，
  val 含 set_016 新泳池整段隔离）
- [x] **v3 训练完成并部署**（159 epoch 早停）：同 val 集对照 **v2 pose mAP50 0.006 → v3 0.110（18×）**，
  `[analysis] model` 已指向 `runs/pose/swimmer_pose19_v3/weights/last.pt`
  （又一次 best.pt 不如 last.pt：0.055 vs 0.110，姿态任务勿信默认 fitness）

### 9.5 detector v3 —— 瓶颈搬家后的补位（2026-08-04，DEVLOG #39）
**发现**：Phase B v3 修好姿态模型后，端到端在新泳池仍然差。逐框诊断 + 40 框目视审计证明
**瓶颈已转移到检测器**：置信度最高的 18 个框（0.72~0.85）全是新泳池的红色泳道浮标，
真运动员只有 0.35~0.67 —— **提高阈值会让系统更糟**（留浮标、丢运动员），目视误检率约 60%。
- [x] 教训入册：代理指标（肤色占比）先后骗了我两次，修正判据后结论完全反转；最终以目视审计为准
- [x] `data/training/phase_a_v3/`：150 旧泳池 + 46 新泳池帧（后者是 Phase B 质检时已人工确认的
  单人框，且每帧都含红浮标作未标注负样本）→ **零额外标注成本**
- [x] **detector v3 训练完成并部署**（69 epoch 早停 / 6.75h）：
  分域评测 **旧泳池 mAP50 0.842→0.880（无退化）、新泳池 0.493→0.867 且精确率 0.463→1.000**；
  40 框目视审计零误检（v2 是最高置信度 18 框全浮标）；`[analysis] swimmer_detector` 已启用
- [x] **端到端双域验收通过**：新泳池 set_013 216/294 帧有骨架、track ID 21→13、
  倒立姿态绿色脚尖点正确；旧泳池 set_008 回归零退化
- [ ] ⚠️ 教训：v2 的 350 帧训练素材已丢失（`swimmer_det_local.yaml` 也不在），
  **训练数据必须与权重一起进版本管理**
- [ ] （可选）交接包里 6 位帧号的旧素材"待标 53 张"——优先级低于新泳池
- [ ] Tim 老师下次去泳池录 5-10 段，覆盖：不同时段、不同泳池、不同动作（ballet leg / barracuda / 转体 / 出水）
- [ ] 重新跑 9.1 + 9.2 → 期望 mAP 大幅提升 + 真正可用的 generalize

## 阶段十：研究方向（IMU→纯视觉转向后）🚧 进行中
> 完整路线图见 `docs/research-roadmap.md`。地基论文：Yue 2023 (*Nature Sci.Rep.*)、
> Edriss 2024 (*IJCSS*)、Cao&Sun 2024、Rodriguez-Zamora apnea 系列。

### 10.A Choreography Intelligence — 自动化 Yue 2023 的 5 个 HF 变量 ✅ 引擎完成
- [x] `dashboard/core/choreography.py`：5 算法（对抗验证过）+ coverage/status/caveat + `rank_sets`
- [x] `GET /api/sets/{name}/choreography` + `GET /api/choreography/rank`
- [x] `tests/test_choreography.py`（13 测试全过）
- [x] **诚实结论**：movement_freq ✅validated / rotation+leg_angle ⚠caveat（相对索引）/
      pattern_duration 🔬exploratory / leg_height ❌excluded（反相关 r=−0.376）；不导出绝对预测分
- [ ] 前端 Choreography Report 卡片（变量表 vs 基准 + coverage 徽章 + 相对排名）
- [ ] 手工 Kinovea 金标准验证（ICC / Bland–Altman）

### 10.B 多人自动裁判 — 闭合 Edriss 2024 "cannot recognize multiple participants"
- [ ] 复现单人 leg-angle（ICC vs Kinovea）→ 扩展 8 人同时 FINA 扣分（队伍中位参考轴）

### 10.C 实时 shoulder-knee 生物反馈 — Edriss r=−0.444 离线 → 实时闭环
- [ ] 实时角 + BLE 振动（复用 M5）+ motor-learning 实验

### 10.D 非侵入 apnea/生理推断 — 最强生医角度
- [ ] 头部关键点可见性→淹没时序；apnea 时长/通气/努力；vs 腕式 HR/SpO₂ 验证

### 10.E 裁判偏差量化 — 把因变量变成被测对象
- [ ] N≥5 裁判评分 + Bland–Altman/ICC + 一致性校正分

### 9.4 Emily v2 实测反馈修复（2026-07-29）— DEVLOG #36
**起因**：Emily 用 v2 部署包实测 6 个 Set（set_011~016），反馈"大部分骨架错 + 预览/录制非常卡"。
逐帧量化：有效帧率仅 1.9~4.1 fps（名义 25，重复帧 6~14×）；set_015/016 关键点 conf 中位 ≈0
（v2 detector 框稳 → track ID 通胀已解决 ✅，但 COCO pose 在 crop 内输出幻觉/全零）。

**骨架错 = Phase B 未训（主因，见 9.2）+ crop pose conf=0.1 无下游过滤 + 前端 0.3 阈值过松。**
**卡 = 同步架构（预览/录制帧率=推理帧率）+ Intel Mac 无 MPS 回落 CPU + hybrid 每帧多次推理。**

- [x] [camera_manager.py](fastapi_app/camera_manager.py) 录制/推理解耦：帧通路（MJPEG seq → 旋转 → JPEG → `_latest`）跟满相机帧率；`_infer_loop` 独立线程只消费最新帧；后端 init 失败不再影响预览/录制；`_latest` 新增 `frame_seq/frame_ts/pose_seq/pose_ts`
- [x] 评审补丁（13-agent 多视角评审，8 条确认全修）：generation 令牌防重启竞态；`pose_rot` 朝向戳防旧基骨架；JSONL 加 `frame_seq/pose_seq` 溯源；tracker yaml 缺失回退+警告；`import_video --kpt-min-conf`；`pose_error` 透传 + 前端"姿态后端故障" badge；标签锚点阈值统一
- [ ] ⚠️ 打 kit 前必须 `git add data/tracker_configs/`（swimmer_botsort.yaml 目前 untracked，git archive 不会带上）
- [x] [yolo_pose.py](fastapi_app/yolo_pose.py) `_apply_kpt_gate()`：conf < `kpt_min_conf`(0.35) 的关键点源头置零（双 detector 类 + factory 均接线），幻觉不落盘、不污染 Phase B 预标注
- [x] [app.js](fastapi_app/static/app.js) `BONE_MIN_VIS=0.45` / `DOT_MIN_VIS=0.35` 常量化，替换 6 处散落阈值
- [x] [config.toml](config.toml) 新增 `kpt_min_conf` + Intel Mac `yolo_device="cpu"` 指引注释
- [x] 保留 writer 25Hz 固定节拍（视频 wall-clock 与 IMU 对齐的前提，阶段三 8.8ms 同步精度不能破坏）
- [x] [tests/test_camera_decouple.py](tests/test_camera_decouple.py) 6 项：门控 3 + 解耦 3；全套件 3 连跑稳定（16 个失败均为改动前已存在）
- [ ] Emily 侧：config 显式 `yolo_device = "cpu"`，打 kit v3 zip 推送更新
- [ ] 骨架真正落对位置：等 9.2 Phase B keypoint 微调（唯一根治方案）

## 阶段十一：架构转向 — 实时只留画面 + IMU，视觉全部离线后处理 ✅（2026-07-30）

**总统大人拍板的重大角色改变**（详见 DEVLOG #37）：抛弃所有实时段推理和分析。
前端实时页只展示摄像头画面和 IMU 数据；视觉方案移到录制结束后的分析阶段——
可以跑更重的权重、更久的时间，确保准确性。

**实测支撑**（Emily set_013，294 帧）：录制时实时推理（COCO@640）只有 29.6% 帧检出；
离线重配置（hybrid v2 + imgsz 1280）检出率 98%（conf 0.35 时 95.6%、误检更少），
在 M 系机器上 56 秒跑完，离线完全可接受。

### 11.1 后端
- [x] [offline_vision.py](fastapi_app/offline_vision.py)：`analyze_set()` 对 video.mp4 逐帧跑重模型，
  **原子重写** vision.csv / landmarks.csv / landmarks_multi.jsonl（tmp + os.replace，失败不碰原文件）
- [x] **时间戳锚点**：复用录制时 vision.csv 的 wall-clock 时间戳（DEVLOG #13 的 1:1 不变量），
  IMU↔视觉对齐在重分析后完整保留；无时间戳的旧/导入 set 回退合成时间轴
- [x] 后台任务注册表：单进程同时只跑一个分析（重模型吃满 CPU，保护录制/面板响应），进度可查
- [x] `POST /api/sets/{name}/analyze` + `GET /api/sets/{name}/analyze/status`（含路径越权保护）
- [x] `config.toml [analysis]` 段：imgsz 1280 默认；conf 智能默认（hybrid→0.35 / 单模型→0.15，实测校准）
- [x] [camera_manager.py](fastapi_app/camera_manager.py) `pose_backend = "none"`（新默认）：
  不再拉起推理线程，帧通路照常满帧率
- [x] 录制期间 writer 照常写 video + 空 landmarks 行（时间戳载体，离线分析的对齐锚）

### 11.2 前端
- [x] 实时页隐藏所有视觉组件（`pose_backend=none` 时）：骨架 badge / 实时评分环 /
  三维条 / 队员实时绑定 / 详细标注 / 原图快照——只留画面 + 录制控制 + 标记 + BLE
- [x] 分析页视频卡新增「视觉分析」按钮：启动离线分析 → 按钮实时显示进度 % →
  完成后自动刷新报告；页面重进可恢复进行中的进度显示
- [x] 队员绑定保留在分析页（7.2 模态），离线分析产出 track ID 后照常可用

### 11.3 测试与验证
- [x] [tests/test_offline_vision.py](tests/test_offline_vision.py) 10 项：文件重写+时间戳保留 /
  无时间戳回退 / 行数漂移全合成 / 撕裂尾行保留前缀 / 部分解码拒绝提交 / 垃圾视频拒绝提交 /
  失败原子性 / 缺视频报错 / 任务注册表生命周期 / 并发互斥
- [x] test_camera_decouple 新增 backend=none 用例（不拉推理线程、帧照常流动）
- [x] 真实数据端到端：Emily set_013 离线重分析成功，检出率 29.6% → 98%
- [x] 15-agent 多视角评审：确认 8 项全部修复，其中 **critical**——`pose_backend=none`
  的新录制（角度恒 0）令相关系数出 NaN → 报告接口 500 → 分析页全挂（scoring.py 已加
  visible 过滤 + 零方差/有限性守卫）；其余：分析任务完成时（而非开始时）失效 sessions
  缓存、录制中禁止启动分析（409）、轮询器跨 set 不再劫持按钮
- [ ] Emily 侧验证：新 kit 部署后录一组 → 分析页点「视觉分析」→ 检查骨架/角度

### 11.5 Emily kit 交付链路修复（2026-08-06，DEVLOG #41）
打包 v3 双模型时发现三个"静默不生效"的断点，全部修复并模拟验证：
- [x] `build-emily-kit.sh` 改打**工作树**而非 `git archive HEAD`（否则未提交的修复全漏掉）
- [x] `models/` 作为部署权重规范位置（开发机硬链接 → runs/，kit 里是真文件）；
  config 改指 `models/swimmer_det_v3.pt` / `models/swimmer_pose19_v3.pt`
- [x] kit 分 `models/`（底座，不覆盖）与 `vision_models/`（自训权重，**必须覆盖**）；
  原 `cp -n` 会导致新模型永远装不上
- [x] **分层配置**：`config.local.toml`（机器相关，永不进包）深度合并覆盖 `config.toml`；
  `update.command` 首次自动迁移 + 按 `uname -m` 判定 cpu/mps（Emily 的 Intel Mac 终于对了）
- [x] 模拟 Emily 处境跑完整更新流程验证 + 10 条 `tests/test_config_local.py`
- [x] 产出 `emily_kit_20260806.zip`（含两个 v3 权重）
- [ ] ⚠️ 本次改动仍未提交 git（kit 打的是工作树）。**建议尽快 commit**，
  否则换机器 / 回滚会丢失这几天的全部成果

### 11.4 被本阶段取代/降级的旧能力
- 实时骨架叠加、实时评分环、实时队员绑定（8.1）→ 仅 `pose_backend != "none"` 的 legacy 模式保留
- 9.4 的录制/推理解耦仍是地基（帧通路 = 现在的唯一实时通路；推理线程 = legacy 模式）

## 硬件配置
- M5StickC Plus2 x2 (NODE_A1 前臂 / NODE_A2 小腿)
- IMU: 内置 MPU6886, 实测 72.5Hz（零丢包零重复）
- BLE 协议: 二进制批量打包，3 读数/通知，52 字节/包
- BLE UUID: SERVICE=12345678-1234-1234-1234-123456789abc, CHAR=abcd1234-ab12-cd34-ef56-abcdef123456
