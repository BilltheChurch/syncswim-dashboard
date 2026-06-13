# 花泳 AI 分析系统 — 研究方向路线图

> From Vision to Coaching: AI-Driven Biomechanical Assessment and
> Physiological Inference in Artistic Swimming
>
> 本文档记录项目从"水下 IMU 方案"转向"纯视觉 + 可穿戴融合"之后的 5 个研究方向，
> 用于生物医学工程 / 应用 AI 方向的申请与潜在论文。**方向 A 已实现**（见
> `dashboard/core/choreography.py`），B–E 为规划。

---

## 0. 背景与转向

### 为什么放弃水下 IMU
原方案把 IMU 节点绑在运动员身上测水下姿态，但**防水外壳难做、干扰动作、每人一套
不可扩展**。文献也佐证这条路不优：Cao & Sun (2024) 明确写 "Sensors are difficult
to be placed in efficient places... bulky... uncomfortable"。

### 转向：纯视觉为主，IMU 仅作可选锚点
我们已有的资产把"纯视觉"变成现实：
- **自训 `HybridSwimmerDetector`**（YOLOv8，mAP@50 = 0.84）+ ByteTrack/BoT-SORT
  多人追踪 → `data/<set>/landmarks_multi.jsonl`（逐帧多泳者 MP-33 关键点）
- FastAPI 实时 dashboard + WebSocket
- M5 BLE IMU 节点（保留为独立验证通道，不再是主数据源）

### 三篇地基论文
| 论文 | 我们用到什么 |
|---|---|
| **Yue et al. 2023, *Nature Sci. Rep.* 13:21303** | 5 个 HF 变量预测总分 R²=0.762；方向 A 自动化它 |
| **Edriss et al. 2024, *IJCSS*** | MediaPipe 测 leg angle，ICC vs Kinovea；明确 limitation "cannot recognize multiple participants" → 方向 B 闭合它；shoulder-knee r=-0.444 → 方向 C |
| **Cao & Sun 2024（swim start MediaPipe）** | 单人 markerless 可达手工精度；我们做多人 + 倒立 + 半身入水的难场景 |
| Rodriguez-Zamora et al.（apnea/lactate 系列） | apnea 时长/强度 ↔ 血乳酸/VO₂ → 方向 D 非侵入推断 |

---

## ⭐ 验证方法学（本项目的可信度核心）

方向 A 的 5 个算法**不是凭直觉写的**：每个都经过对抗式验证 —— 验证 agent 把候选算法
**实际跑在真实 dogfood 数据上**（set_002…020），用代码证伪。这一步抓出了若不验证就会
进生产的致命错误，例如：

- `leg_height_index` 的"用髋当水线"代理被证明是**解剖学常数**，且与真实抬腿高度
  **反相关 r = −0.376**（会把队伍排名排反），已排除。
- `movement_frequency` 早期版本"所有 set 都落在论文 1.82±0.17 区间"被证明是
  **refractory bug 的假象**，修复后真实值散布 1.2–2.5 Hz。
- `rotation_frequency` 需要的不是"每步角速度中位数"（会在保持图形时塌成 0），而是
  论文定义的**总旋转度数 / 总时长**；改对之后**无需任何拟合常数**即落入论文区间。

> **诚实优先**：负结果（哪些变量无法从单目无标定视频忠实自动化）与正结果同等重要，
> 这本身就是科学贡献。

### 5 个 HF 变量自动化结论表

| 变量 | Yue β | 状态 | 我们能给什么 | 为什么 |
|---|---|---|---|---|
| **movement_frequency** | +0.345 | ✅ validated | 相对跨片索引（非绝对 Hz） | 平滑后腿部方向反转计数，frame-time refractory |
| **rotation_frequency** | +0.149 | ⚠ caveat | 相对索引 | 论文式总度数/时长，无 CALIB；但斜侧视角foreshorten + 手持抖动 |
| **leg_angle_deviation** | −0.229 | ⚠ caveat | 相对索引 | 加长宽比修正；~2× 论文绝对度数（图像垂直≠水面水平，无水平校准） |
| **mean_pattern_duration** | −0.190 | 🔬 exploratory | 仅探索 | 测"可见质心 churn"非 8 人队形（80%+ 槽位零可见关键点），被 floor + 拍摄角度污染 |
| **leg_height_index** | +0.393 | ❌ excluded | 无 | 水线相对量不可恢复；天真代理反相关 r=−0.376 |

**跨切结论**：我们**不导出**绝对"预测 Yue 总分"——betas 是在标定 Kinovea 输入上拟合的，
我们的代理是不同 scale，且 leg_height（反相关）恰好带最大正 β。我们只给 **相对跨片
z-score 综合指数**（`rank_sets`），仅用存活的 3 个变量（movement / rotation /
leg_angle），明确标注为"我们自己片段的相对排序"，非 Yue 绝对分。

### 申请中最站得住的表述

> "I built an automated pipeline (custom YOLOv8 detector, mAP@50=0.84, + COCO-17
> pose tracking) operationalizing the hybrid-figure variables from Yue et al.
> (2023, *Sci. Rep.*), originally hand-measured in Kinovea over 1–2 weeks per
> team. The contribution is not reproducing their absolute scale from
> uncalibrated handheld video — it is deriving a pose-based estimator per
> variable and validating each against the data, reporting where it fails.
> movement_frequency is recoverable as a relative index; rotation_frequency
> becomes paper-faithful once the wrong central statistic (per-step median) is
> replaced with total-degrees-per-second (the uncalibrated output then lands
> inside the published 41.8 deg/s band, so no fudge constant is needed);
> leg_angle_deviation needs an aspect-ratio correction I quantified and stays a
> relative index absent horizon calibration; and critically, the naive
> leg_height_index proxy is anatomically degenerate and anti-correlated
> (r=−0.376) with true leg-lift, so I excluded it rather than ship a misleading
> number. I treat the variables as relative cross-clip indices with explicit
> coverage/confidence flags and deliberately do NOT export an absolute
> regression-predicted score. The honest result — which biomechanical markers
> survive automation from monocular uncalibrated competition video and which do
> not — is the scientifically interesting finding."

---

## A — Choreography Intelligence Engine

- **Status**: ✅ 已实现 — `dashboard/core/choreography.py` + `GET /api/sets/{name}/choreography`
  + `GET /api/choreography/rank` + `tests/test_choreography.py`（13 测试全过）

### Hook / 填补的空白
Yue et al. (2023, *Nature Scientific Reports* 13:21303) 证明**hybrid figures (HF)** 是
团体自由自选中最决定分数的环节：5 个手工测量的 HF 变量多元回归解释 **R² = 0.762** 的
总分。决定性的局限是**方法而非模型**：每个变量都在 Kinovea 里逐帧手工数字化，作者花了
**每队 1–2 周分析师工时**，把研究困在一次性回顾。这条管线无法在训练周内、俱乐部队、
或快到能闭合教练反馈环的速度下运行。这正是本引擎填补的空白：把 1–2 周手工测量变成
**~30 分钟自动化逐 set 报告**。

周边文献佐证机会与难点：Edriss et al. (2024, *IJCSS*) 记录花泳仍以手工记号编码为主，
markerless 多人姿态基本未应用；Cao & Sun (2024) 证明 MediaPipe markerless 运动学能
匹配手工数字化 —— 但只针对单个、完全可见、直立的运动员，不涉及定义我们问题的条件
（3–8 泳者、严重互遮挡、倒立仅腿/脚出水）。Rodriguez-Zamora 等把 HF 段确立为routine
的主导**生理**负荷，使 HF 时间线成为双用途产物：评分工具 + 与可穿戴融合后的非侵入
exertion 代理。

### Method
1. **逐帧多人姿态**（已有）：`fastapi_app/yolo_pose.py` 的 `HybridSwimmerDetector`
   写出 `landmarks_multi.jsonl`。choreography.py 是它的**消费者**，无需新感知模型。
2. **几何原语**：复用 `dashboard/core/vision_angles.py` 的 `_angle_from_vertical()` /
   `calc_angle()` + `VIS_THRESHOLD=0.5` 门控 + `np.nanmean` 聚合（遮挡关节→NaN）。
3. **5 个变量**（每个只在通过可见性门控的帧上计算）—— 详见上方结论表；每个变量带
   `coverage`（样本数 / 追踪秒数）+ `status` + `confidence` + `caveat`。
4. **相对综合**（`rank_sets`）：对存活变量做跨片 z-score，按 Yue 回归方向 sign 加权；
   **不**导出绝对预测分。

### Validation plan（待做）
- **金标准 = 手工 Kinovea 重测**（Yue 协议）由标注员在留出子集上做 → 每变量 **ICC(2,1)**
  + **Bland–Altman** bias/LoA + Pearson/Spearman。目标 ICC ≥ 0.75。
- **评测者内/间信度**：手工测两遍 → 我们的 auto-vs-manual 误差相对人类不可约噪声报告。
- **追踪鲁棒性消融**：扰动/留出 track 看每变量置信度随 `vis` 下降如何退化。
- **可穿戴交叉验证**：M5 IMU 角速度积分 vs dashboard rotation/movement 的并发效度。

### Deliverables（已交付 ✅ / 待做 ⏳）
- ✅ `dashboard/core/choreography.py`、两个 API 端点、`tests/test_choreography.py`
- ⏳ dashboard 前端 Choreography Report 卡片（变量表 vs 基准 + coverage 徽章 + 相对排名）
- ⏳ 手工-vs-自动一致性验证实验（ICC / Bland–Altman），作为方法论文基础

### 生物医学工程框架
本质是把一个**劳力受限、专家专属的生物力学测量协议变成可复现、可扩展的仪器** —— 这是
生物医学仪器学的核心母题：把专家慢速手测的量（这里是水下倒立多人运动员的关节角与
全身运动学）做成带误差界的自动估计器。新颖性具体且学科特定：已发表的水中 markerless
工作处理*单个直立完全可见*运动员，而分数驱动的 Yue 变量必须在打破那些方法的 regime 下
恢复（多人互遮挡、倒立、仅腿出水、无 scale、无水线）。在*那些*约束下解决测量（自归一
scale-free 指数、可见性门控置信加权、track-robust 分割）正是工程贡献。

### Effort & dependencies
中等。感知（难的部分）已存在，几何原语可复用；choreography.py 是集成 + 谨慎门控。
**关键依赖是验证而非代码**：需要标注员的手工 Kinovea 测量做金标准。**坦白风险**：单目
单相机几何（旋转与离面运动是估计非 3D 测量）、无 scale/水线、3–8 人遮挡是主导误差源 ——
全部在报告里 disclose，不藏。

---

## B — Multi-Swimmer Automated Officiating

- **Status**: PLANNED

### Hook / 填补的空白
Edriss et al. (2024, *IJCSS*) 证明单相机 MediaPipe 能测花泳 leg angle 对标 Kinovea，但
明确写 **"MediaPipe cannot recognize multiple participants"** —— 把自动裁判困在一次一人。
这对真实裁判问题是致命的：花泳按*团队同步*评分，执行扣分依赖 HF 中 8 名成员的同时比较。
**空白**：没人自动化*多人同时*扣分评分，因为领域默认姿态骨干是单人结构。我们已清除该
骨干限制 —— `HybridSwimmerDetector`（mAP@50=0.84）+ ByteTrack 产出最多 8 人逐帧关键点。

### Method
1. **先复现 Edriss（单人）确立测量效度** —— 镜像 `vision_angles.py`，leg-line 用 hip→
   knee→ankle，`_angle_from_vertical` 测垂直偏差，`VIS_THRESHOLD` 门控。
2. **扩展到 8 人同时评分** —— 遍历每帧 `persons[]` 按 track `ids[]`，算每泳者相对**队伍
   中位腿向量**（per-frame cohort median，抗相机倾斜/抖动）的偏差，映射 FINA 扣分阶梯
   0–15°→−0.2 / 15–30°→−0.5 / >30°→−1.0；按 track 滚动中位平滑抑制抖动。
3. **dashboard 端点** —— 逐 HF 段返回每泳者扣分表 + 队伍同步热图。

### Validation plan
- **Stage 1（单人 vs 金标准）**：ICC(2,1) + Bland–Altman vs 手工 Kinovea。
- **Stage 2（多人自动扣分 vs 人类裁判）**：加权 Cohen's κ（序数阶梯）+ ICC（队伍总扣分）
  + Bland–Altman；报告 15°/30° 边界混淆；预注册遮挡 floor 下标"不可评分"而非猜。

### Deliverables
`dashboard/core/officiating.py`、`tests/test_officiating.py`、`GET /api/officiating/{set}`、
`tools/eval_officiating.py`（ICC/Bland–Altman/κ）、金标准 + 裁判标注数据集。

### 生物医学工程框架
对**对抗性真实条件下的定量人体运动评估**的应用 AI 贡献 —— 部分遮挡、水面截断、倒立、
无标定，正是生物力学/康复实验室把 markerless 姿态搬出实验室时面对的 hostile regime。
新颖性：(1) 通过*换骨干*而非绕过，闭合文献中命名的结构性限制；(2) 把慢速专家手工测量
重构为实时、多体、同步感知的仪器，用临床测量设备的一致性统计（ICC、Bland–Altman）验证。

### Effort & dependencies
中等。Stage 1 约 1–2 周（靠现有 helper）；Stage 2 约 3–5 周（主要是标注 + 遮挡处理）。
**关键路径风险**：3–8 人重遮挡可能把"不可评分"率推高到只有队伍总扣分可比 —— 如实报告。

---

## C — Real-time Shoulder-Knee Biofeedback

- **Status**: PLANNED

### Hook / 填补的空白
Edriss et al. (2024, *IJCSS*) 最反直觉的发现之一是 **shoulder–knee 对齐角与总分
r = −0.444**（中等负相关）—— 上身躯干与膝盖越在一条直线上，分越高。但他们在
**事后离线实验室**测这个量，**没有实时反馈**。运动学习（motor learning）文献长期表明：
**反馈延迟越短，技能习得越快**；把一个已被证明与分数相关的生物力学量做成闭环实时提示，
是从"赛后分析"跨到"训练中矫正"的关键一步 —— 目前花泳没有这样的工具。

### Method（全部复用现有硬件，不需新传感器）
1. **实时 shoulder–hip–knee 角** —— dashboard 已有逐帧关键点流（`ws_video` /
   `camera_manager`）。复用 `calc_angle(shoulder, hip, knee)`（MP-33: 11/12→23/24→25/26），
   `VIS_THRESHOLD` 门控，按短窗中位平滑。
2. **容差阈值 + 触发** —— 当对齐角偏离教练设定容差（如 >20°）持续 N 帧，触发：
   (a) 屏幕红色警示 overlay；(b) **BLE 触觉反馈** —— 复用现有 M5 节点（`ble_manager`
   已有双向 BLE 通道），向运动员腕/腿节点发振动指令。
3. **延迟预算** —— 目标端到端 < 300 ms（捕获→姿态→判定→触觉），让反馈落在动作仍可
   修正的时间窗内。记录并报告实际延迟分布。

### Validation plan
- **闭环 vs 开环 motor-learning 实验**：两组运动员（有/无实时触觉反馈）练同一图形，
  比较 shoulder–knee 对齐角随 session 收敛速度（混合效应模型，组×时间交互）。
- **延迟测量**：硬件时间戳法测端到端延迟（mean ± SD）。
- **姿态精度**：实时角 vs 离线 Kinovea 金标准 ICC（确认实时管线没牺牲精度）。

### Deliverables
`fastapi_app/realtime_feedback.py`（实时角 + 阈值触发）、`ws_metrics` 推送扩展、BLE 振动
指令协议、dashboard 实时对齐仪表 + 警示 overlay、motor-learning 实验协议 + 结果。

### 生物医学工程框架
这是最贴近**康复工程 / 闭环生物反馈**的方向：把一个已验证与表现相关的生物力学量做成
实时、可穿戴触觉的闭环系统，与中风康复的实时步态反馈、运动训练的 EMG 生物反馈同源。
新颖性：(1) 把 Edriss 的离线相关量*操作化*为实时闭环；(2) 纯复用现有视觉 + BLE 硬件
（零新传感器）实现可穿戴触觉，证明低成本可部署性；(3) 用 motor-learning 实验设计
（而非仅工程 demo）验证学习速率改善 —— 这是行为科学 + 仪器学的交叉。

### Effort & dependencies
中等。实时角 + 阈值 + WS 推送约 1 周（管线已存在）；BLE 振动指令需固件端加接收（M5
`.ino` 改动）+ 节点佩戴位置实验，约 1–2 周。**依赖**：(1) M5 固件加振动驱动 + BLE 写
特征；(2) motor-learning 实验需多名运动员多 session（关键路径）；(3) 延迟需实测验证。
**坦白风险**：水下运动员佩戴触觉节点又回到 IMU 方案的防水难题 —— 触觉反馈可能更适合
水上/岸边阶段或练习时的腕带，需现场确认可行性。

---

## D — Non-Invasive Apnea / Physiological Inference

- **Status**: PLANNED（**最强的生物医学工程角度**）

### Hook / 填补的空白
Yue et al. (2023) 指出运动员约 **50–65% 时间脸朝下倒立水下** —— 一个 choreography 的
*生理*代价对相机运动学变量不可见的 regime。所有运动学 follow-up（Edriss 2024；Cao & Sun
2024）都止步于*外部*负荷：角度、高度、频率，没人恢复*内部*负荷。Rodriguez-Zamora 等
确立 **apnea 时长与强度强耦合于血乳酸累积与 VO₂/摄氧动力学** —— 屏气*就是*代谢应激。
空白：测这个通常需要面罩 capnometer/便携气体分析仪 + 侵入式毛细血乳酸采样，routine 中
不可穿戴、俱乐部不可负担。我们已被动记录了能重建 apnea 结构的信号（头部关键点淹没时序）
**而不接触运动员**。

### Method
1. **每泳者呼吸状态时间序列** —— 用头部关键点（nose idx0, ears 7/8）的**可见性**构建
   "头出水/淹没"二值信号。复用 `VIS_THRESHOLD` 门控 + 滞后 + 短中位滤波抑制单帧丢检。
   **关键洞察**：把*关键点可见性丢失*（通常视为检测失败）当作**气道淹没的信号**。
2. **apnea 段提取** —— apnea 时长、通气频率（出水事件/分钟）、淹没占空比（验证 Yue 的
   "50–65%"*逐运动员*）、apnea 强度代理（按段内并发机械努力加权）。
3. **推力爆发/努力估计** —— (a) 视觉：bbox 质心向上速度/加速度 + 腿部关键点上升率，
   躯干长度归一化去 scale；(b) IMU：M5 6 轴 ~70Hz BLE，按 `sync_recorder` set-number
   时间对齐，段内带限加速度能量给硬件锚定的努力权重。
4. **综合内部负荷代理** —— 融合上述，按 Rodriguez-Zamora apnea↔lactate 耦合；系数*拟合*
   非假设，未标定前标"uncalibrated"。
5. **服务** —— `/physio` 路由 + `ws_metrics` 实时推送，dashboard 显示逐泳者屏气时间线 +
   实时负荷仪表。

> **坦白约束**：M5 节点只有 IMU + 电池，**我们自己硬件无 SpO₂/HR 传感器**。SpO₂/HR 是
> 金标准*参考*（验证用），非管线输入。核心 apnea/通气推断是纯视觉，IMU 是可选努力精修。

### Validation plan
- **apnea 时序（视觉）vs 真值**：手工标淹没 on/off → 逐事件 onset/offset 误差 + ICC(2,1)
  + Bland–Altman；帧级 precision/recall/F1（混淆归因遮挡 vs 真淹没）。
- **内部负荷代理 vs 可穿戴金标准**：运动员戴腕式 HR/SpO₂ 表，相关（Pearson/Spearman）
  代理 vs 段后 HR 恢复 / SpO₂ 去饱和深度；有 sports-science 伙伴则加毛细血乳酸。
- **可靠性**：test-retest ICC；对相机抖动/人数/遮挡的敏感性；视觉 vs 视觉+IMU 消融。
- **诚实护栏**：ICC/LoA 达标前，输出标"research proxy, not a physiological measurement"。

### Deliverables
`fastapi_app/physio_inference.py`、`GET /physio/{set_id}` + WS 扩展、dashboard 屏气面板、
`tools/extract_apnea.py`（批量出 `apnea_metrics.json`）、`tests/test_physio_inference.py`、
Emily 标注规范、验证报告（ICC/Bland–Altman/代理-vs-可穿戴相关）。

### 生物医学工程框架
项目最清晰的生物医学/应用 AI 贡献，因为它从*外部运动学*（所有先前花泳视觉论文测的）
跨到*内部生理负荷*（真正限制运动员的）—— 只用被动 markerless 视频 + 廉价可选 IMU，
无面罩、无探头、无抽血。方法上是对一个潜在生理状态的多模态传感融合估计器（视觉事件
时序 + 惯性努力），用临床级参考 + 标准生物医学一致性统计验证。新颖性：(1) 把*关键点
可见性丢失*当作气道淹没信号；(2) 把已知 apnea→lactate/VO₂ 耦合操作化为实时、可现场
部署的内部负荷监测，用于一项负荷*按定义*藏在水下的运动。若验证成功，是该人群屏气/
缺氧应激的低成本筛查工具。

### Effort & dependencies
中等。纯视觉 apnea/通气推断 + 批量工具 + 测试约 1–2 周（detector/JSONL/BLE-sync/WS
都已存在）；实时面板几天。**依赖**：(1) Emily 标注淹没 on/off（限速器）；(2) ≥1 运动员
≥1 routine 戴腕式 HR/SpO₂（金标准，*非*现有 M5 硬件）；(3) 可选毛细血乳酸；(4) 亚秒级
视频↔IMU 同步再验证。核心推断不需新佩戴硬件。

---

## E — Judge Bias Quantification

- **Status**: PLANNED（生物医学对齐最低，但干净、自包含、可发表的副研究）

### Hook / 填补的空白
每篇定量花泳论文都把*裁判分当作真值*，同时承认它是链条最弱环。Yue et al. (2023) 把 8 个
手测 HF 变量回归到**总分**得 R²=0.762 —— 但那 0.762 上限部分由因变量自身噪声所限：分数是
人类裁判面板共识，论文没给自己结果变量的评测者间信度。**空白：没人量化人类面板自身的
偏差与分歧，也没提出可复现的校正。** 本研究把因变量从假定常数变成被测对象。

### Method（全部复用现有资产，无新硬件）
1. **客观基线（"工具分"）** —— 复用方向 A 的存活变量做确定性可复现参考（非真值主张）。
2. **人类裁判采集** —— dashboard 加轻量评分端点：`GET/POST /judge/{clip_id}`，N≥5 个评测者
   全交叉评同一片集；子集 48h 后重评做评测者内信度。
3. **偏差分解** —— 混合效应：每裁判固定偏移（宽松/严格）+ 片段相关方差；交叉引用每帧
   `visibility_ratio` 检验"人机分歧最大恰在遮挡处"假设。
4. **一致性校正分** —— 按裁判方差反权 + 去固定偏移（向面板+工具共识收缩），带置信区间。

### Validation plan
ICC(2,k) 评测者间 + ICC(3,1) 评测者内 + Bland–Altman（裁判-vs-工具 & 裁判-vs-裁判，
按遮挡/直立-倒立分层）+ 客观分与校正分对原面板的相关。**可证伪成功判据**：用校正分做
因变量重跑 Yue 回归，若同样预测器 R² 升过 0.762，即证原上限部分是因变量噪声。

### Deliverables
`dashboard/core/judge_bias.py`、`GET/POST /judge/{clip_id}` + judgements 表（dev/prod 分离）
+ 评分 UI、`tools/run_judge_bias.py`、`tests/test_judge_bias.py`、结果 notebook。

### 生物医学工程框架
测量科学贡献：把主观临床式评估变成有明示信度与误差模型的量 —— 与生物医学工程师拿
新仪器对标有缺陷的人类参考（自动 ECG 判读 vs 心内科医生、CAD vs 放射科医生）同一学科。
新颖性：(1) 用确定性 CV 估计器 + 独立可穿戴 IMU 做正交参考三角定位人类偏差；(2) 把分歧
因果链接到可测图像属性（遮挡）+ 特定生物力学 regime（倒立 HF）。

### Effort & dependencies
中等。客观基线已存在；净新工作约 1–1.5 工程周。**硬依赖人类评测者**：需 ≥5 裁判
（理想含 ≥1 持证 AS 裁判）评共享片集 —— 招募是关键路径风险，非代码。

---

## 优先级与时间线

| 方向 | 优先级 | 状态 | 关键依赖 |
|---|---|---|---|
| A Choreography Intelligence | 🔴 最高 | ✅ 引擎完成，待前端+验证 | 手工 Kinovea 金标准 |
| D Apnea 生理推断 | 🟠 高（最强生医角度） | 规划 | Emily 标注 + 腕式 HR/SpO₂ |
| B 多人裁判 | 🟡 中 | 规划 | 裁判/Emily 扣分标注 |
| C 实时生物反馈 | 🟡 中 | 规划 | M5 固件振动 + motor-learning 实验 |
| E 裁判偏差 | 🟢 低 | 规划 | ≥5 裁判招募 |

---

## 相关文件
- `dashboard/core/choreography.py` — 方向 A 引擎（5 变量 + 相对排名）
- `fastapi_app/api_routes.py` — `/api/sets/{name}/choreography` + `/api/choreography/rank`
- `tests/test_choreography.py` — 合成几何单元测试
- `docs/phase-a-annotation.md` — 检测器训练标注（上游）
- DEVLOG #35 — 本路线图 + 对抗验证发现的设计回顾
