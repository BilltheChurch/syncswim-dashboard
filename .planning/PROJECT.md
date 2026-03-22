# SyncSwim Dashboard — 花泳运动捕捉分析平台

## What This Is

基于 IMU + 视觉双源传感器融合的花泳训练分析系统。已完成数据采集管道（BLE IMU 72.5Hz + MediaPipe 骨骼 26fps + 双源同步录制 + 基础分析验证），现在要建一个 Streamlit Web Dashboard，将采集到的数据转化为教练和学员可理解的实时反馈、量化评分和 AI 训练建议。目标用户是花泳教练（全局视角）和学员（细节视角），泳池边任何设备（iPad/笔记本/手机）都能访问。

## Core Value

**让传感器数据变成教练和学员看得懂、用得上的训练反馈。** 技术再好，如果呈现出来的东西教练看不懂或觉得没用，就白做了。Dashboard 是整个系统价值感的最终载体。

## Requirements

### Validated

<!-- 已有代码已实现并验证的能力 -->

- ✓ BLE 数据采集管道 — Phase 1（72.5Hz / 0% 丢包 / 0% 重复）
- ✓ 视觉骨骼检测管道 — Phase 2（MediaPipe 26fps / 关节角度计算）
- ✓ 双源同步录制 — Phase 3（起始偏移 8.8ms / 时长差 17.6ms）
- ✓ 基础分析验证 — Phase 4（IMU 倾斜角 vs 肘关节角度相关性 -0.497）
- ✓ M5StickC Plus2 固件 — BLE 二进制批量协议 / 采样门控 / 断线重广播
- ✓ MJPEG 手动流解析 — 绕过 OpenCV macOS ARM HTTP 限制

### Active

<!-- 当前 Dashboard 建设的完整需求 -->

**View 1: 实时监控面板（训练进行时）**
- [ ] 实时骨骼叠加视频 — MediaPipe 骨骼线覆盖在摄像头画面上
- [ ] 关节颜色编码 — 绿色=合格 / 黄色=轻微偏差 / 红色=超阈值
- [ ] 实时关节角度仪表盘 — 腿偏离垂直角度 / 肩膝对齐 / 髋关节屈伸，带 FINA 扣分区间
- [ ] IMU 实时波形 — 加速度/角速度滚动曲线 + 融合角度值显示
- [ ] 状态栏 — 当前组号 / 动作名 / 录制时长 / BLE 连接状态

**View 2: 单组动作分析报告（停止后自动生成）**
- [ ] 动作时间线 — 横轴时间 + 阶段标注（准备/入水/推举/展示/下降）+ 阶段质量评级
- [ ] 关键帧对比 — 展示期骨骼姿态 vs 标准姿态模板，偏差角度标注
- [ ] 量化评分卡 — 腿部垂直偏差 / 腿高指数 / 肩膝对齐度 / 平滑度(Jerk) / 展示期稳定性
- [ ] FINA 扣分规则映射 — 偏 15° 扣 0.2 / 偏 30° 扣 0.5 / >30° 扣 1
- [ ] AI 教练建议 — Claude API 生成自然语言改进建议

**View 3: 多组对比与进步追踪（课后复盘）**
- [ ] 趋势图 — X=组号 Y=各项指标，显示课内进步/疲劳退步
- [ ] 雷达图对比 — 选两组动作叠加六维对比
- [ ] 历史记录表 — 按日期/动作类型筛选，支持 CSV 导出

**View 4: AI 深度分析**
- [ ] 动作同步性分析（DTW）— 多人动作时间序列距离可视化
- [ ] 动作模式识别 — K-Means/DBSCAN 聚类 + PCA 2D 散点图
- [ ] 异常检测 — 自动标记角度剧变帧
- [ ] AI 训练计划建议 — 基于多次课数据的阶段性建议

**View 5: 团队同步性（3人 IMU+视觉融合）**
- [ ] 同步性热力图 — 时间×运动员，颜色=偏离团队节拍程度
- [ ] 配对 DTW 矩阵 — N×N 两人同步性距离
- [ ] 关键时刻对齐图 — 展示期垂直位置到达时间偏差
- [ ] 节奏曲线叠加 — 所有人腿部角度曲线重叠对比
- [ ] AI 同步性报告 — 具体到哪个运动员在哪个阶段掉链子

**基础设施**
- [ ] Streamlit Web 应用骨架 — 多页面结构 + 教练/学员视角切换
- [ ] 数据加载层 — 读取现有 CSV 数据目录结构
- [ ] Claude API 集成 — AI 分析的 prompt 模板和调用封装
- [ ] 多人 BLE 连接扩展 — 3人×2节点=6台 M5StickC Plus2 同时连接
- [ ] MediaPipe 多人检测 — 多人骨骼提取 + ID 追踪
- [ ] 校准流程 — 开始前的站位校准 + IMU-视觉人员映射

### Out of Scope

- React/Next.js 前端重构 — Streamlit MVP 先行，后期再考虑
- 云端部署 — 当前局域网本地运行即可
- 移动端 App — Web 天然跨平台，不需要原生 App
- 实时视频推流到 Dashboard — 先做录制后回放分析
- 水下 IMU 防水方案 — 微科研范围内先做水面以上
- 超过 3 人的 BLE 多连接 — BLE 适配器 6 设备是合理上限

## Context

- 这是一个面向英国大学申请的微科研项目（PS/面试展示用途）
- 花泳团队同步性是 FINA 三大评分维度之一，目前教练没有量化工具
- 已有 4 个阶段代码全部在 `test_rec/` 单目录下，无框架、无数据库，CSV 文件存储
- 现有代码用 Python 3.10 + bleak + OpenCV + MediaPipe + matplotlib
- 硬件：M5StickC Plus2（内置 MPU6886 IMU），iOS DroidCam 做 IP 摄像头
- 三篇花泳相关论文提供了评分标准和分析方法的学术依据
- AI 教练用 Claude API（非自训练模型），因为训练数据少且自然语言输出对终端用户价值更高

## Constraints

- **Tech Stack**: Python + Streamlit — 和现有代码库一致，不引入 JS 前端框架
- **Hardware**: 最多 6-8 台 M5StickC Plus2，总预算 ¥900-1000
- **BLE Limit**: 单台笔记本 BLE 同时连接上限 ~6 设备
- **Camera**: DroidCam MJPEG 流，需手动解析（macOS ARM OpenCV 限制）
- **AI API**: Claude API 需要网络连接和 API key
- **Performance**: MediaPipe 多人检测在水面环境精度会下降，主要覆盖水面以上展示阶段

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Streamlit 而非 React | 和现有 Python 代码库一致，快速出 MVP | — Pending |
| Claude API 而非自训练模型 | 训练数据少 + 自然语言输出价值高 + 不需要大量数据 | — Pending |
| 3 人同步性而非 8 人 | BLE 6 设备上限 + 微科研可行性，论文讨论扩展方案 | — Pending |
| 视觉+IMU 融合而非单一传感器 | 两个不完美传感器互补，和 PS 叙事线一致 | — Pending |
| 教练端触发录制 | 运动员水中不便操作，教练岸上操作更自然 | — Pending |

---
*Last updated: 2026-03-22 after initialization*
