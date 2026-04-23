# YOLOv8-pose 微调流程

> 阶段 7.4 产出。等阶段 7.0（教练上传真实素材）到位后跑一次完整流程。

## 为什么要微调

通用 `yolov8s-pose.pt` 在 COCO 上训练，**COCO 不含水中游泳运动员**这种特殊场景。基于阶段 6/7 的离线推断，它在以下场景大概率失效：

- 半身入水时关键点丢失
- 翻身瞬间左右骨架反转
- 水花遮挡误检
- 泳帽 + 黑泳衣对比度过低
- 水面折射造成关键点偏移

针对这些场景微调，行业经验值能把 OKS 从 ~0.55 提升到 0.75+，关键场景能用了。

## 流程概览

```
data/raw_videos/                 ← 教练上传 mp4 / mov
        ↓ tools/preannotate.py
data/training/
   images/*.jpg                  ← 抽帧（默认每 5 帧 1 张）
   labels/*.txt                  ← 半监督预标注（YOLO pose format）
        ↓ CVAT / Label Studio (人工修正 — 这是最耗时的一步)
   labels/*.txt                  ← 最终标签（覆盖原 pre-annotation）
   train.txt + val.txt           ← 手动拆分（后面会讲为什么不能 auto split）
        ↓ tools/train_pose.py
runs/pose/syncswim_v1/weights/best.pt
        ↓ config.toml: yolo_model = "runs/pose/.../best.pt"
   生产：dashboard 用新权重，pipeline 不变
        ↓ tools/eval_pose.py（在新场地的留出 set 上）
   报告：mAP@50, OKS
```

## 第 0 步：囤素材

1. 把已有的训练录像（手机 / GoPro / 任何摄像机）放到 `data/raw_videos/`
2. **多样性 > 数量**。优先囤：
   - 不同泳池（深水位、浅水位、室内、室外）
   - 不同光照（晴天、阴天、人工灯、水下灯）
   - 不同时段（晨练、白天、夜训）
   - 不同动作（Ballet Leg、Barracuda、转体、出水）
   - **2–8 个运动员同框**（COCO 不擅长多人遮挡，这正是花泳的核心场景）
3. 每个视频 30s–2min 即可，不要一上来就 10min 长片，标注效率会暴跌。

## 第 1 步：半监督预标注

```bash
python tools/preannotate.py --interval 5
```

参数：
- `--interval 5`：每 5 帧抽 1 帧。25 fps 的视频每秒得到 5 帧。30s 视频 = 150 帧待标。
- `--conf 0.3`：检测信心阈值。**故意调低**，让 borderline 检测也进入预标 — 人工修正比从空白开始快得多。
- `--device mps`：M 系芯片用 Metal，nvidia 用 cuda，没显卡用 cpu。
- `--max-persons 10`：每帧最多检测 10 个人，避免泳池岸边路人混入。

输出：
```
data/training/images/clip01_f000000.jpg
data/training/labels/clip01_f000000.txt
clip01_f000005.jpg
clip01_f000005.txt
...
```

每个 `.txt` 一行一个 person，YOLO pose 格式：
```
0 cx cy w h  kx1 ky1 v1  kx2 ky2 v2  ...  kx17 ky17 v17
```

`v` 是 visibility：0=未标注/出框、1=遮挡、2=清晰。

## 第 2 步：人工修正（CVAT 或 Label Studio）

**这是整个流程最耗时也最关键的一步**。预标注省下了 5–10× 的"画"的功夫，但**修错**的功夫无法省。

### CVAT 推荐设置

1. New Project → Skeleton points (17 nodes, COCO layout)
2. Upload `data/training/images/` 作为 task
3. Import annotations → 选 YOLO 1.1 → 上传 `labels/` 整个文件夹
4. 重点修正：
   - 水中半身入水的关键点（很多被通用模型乱画到水面）
   - 翻身瞬间的左右关键点反转
   - 多人遮挡时的 ID 混淆
5. Export → YOLO 1.1 → 替换原 `labels/`

### 数据量起点建议

| 帧数 | 用途 |
|---|---|
| 200–500 | 跑通完整流程，看 mAP 趋势是否健康 |
| 2000+ | 接近"生产可用" |
| 5000+ | 接近 SOTA |

## 第 3 步：拆分训练 / 验证集

ultralytics 默认 80/20 自动拆分。**但自动拆分是按文件名 hash 的**，会让同一个视频的相邻帧分在两边 — val mAP 虚高，无意义。

**正确做法**：手动拆分。在 `data/training/` 下建：

```bash
# train.txt：除了某一个视频之外的所有帧
ls data/training/images/clip01_*.jpg data/training/images/clip02_*.jpg \
   > data/training/train.txt

# val.txt：完全没出现在 train 里的"留出视频"的所有帧
# 这个视频应该来自训练集没见过的场地 / 光照 / 运动员组合
ls data/training/images/clip_holdout_*.jpg \
   > data/training/val.txt
```

然后修改 `data/training/syncswim.yaml`：

```yaml
train: train.txt
val: val.txt
```

## 第 4 步：训练

```bash
python tools/train_pose.py --epochs 100 --batch 16
```

参数说明（已针对水中场景优化）：

| 参数 | 默认 | 为什么 |
|---|---|---|
| `epochs` | 100 | 起步够；如果 val mAP 还在升再加 |
| `imgsz` | 640 | YOLO 默认；M 芯片上 ~30s/epoch 100 张 |
| `batch` | 16 | M2 16GB 上限；M3 Pro 可上 32 |
| `mosaic` | 0.5 | 低于默认 1.0 — 多人镜头本身已有"自然 mosaic" |
| `mixup` | 0.1 | 少量混合保留单人特征 |
| `degrees` | 5.0 | 限制旋转 — 花泳动作有明显方向语义 |

监控：训练完后看 `runs/pose/syncswim_v1/results.png`（loss 曲线）、`PR_curve.png`（精度）。

## 第 5 步：评估

**关键守门：评估集必须是训练集没见过的场地**。这一点决定你的微调到底是真改善了泛化能力，还是过拟合到训练池。

```bash
python tools/eval_pose.py
```

输出：
```
mAP@50      : 0.7842   (baseline yolov8s-pose ≈ 0.55 on swim)
mAP@50–95   : 0.5311
per-class   : {'person': 0.5311}
```

**对照基准**：通用 `yolov8s-pose.pt` 在我们的留出泳池数据上 mAP@50 大约 0.55。**只要超过 0.55 就是真改善**。

## 第 6 步：部署

修改 `config.toml`：

```toml
[hardware]
yolo_model = "runs/pose/syncswim_v1/weights/best.pt"
```

dashboard 重启即生效。前端、recorder、tracker 全部不变 — 唯一变化是检测精度。

## 数据隐私 & 体积

- `data/raw_videos/`、`data/training/images/`、`data/training/labels/`、`runs/` 都已加入 `.gitignore`
- `data/training/syncswim.yaml` 入仓（小，是配置不是数据）
- 单个真实训练视频可能有运动员肖像权问题 — 上传给云端 CVAT 前**必须**确认所有出现的人都签过授权
- 推荐用本地 CVAT 容器（[官方安装](https://docs.cvat.ai/docs/administration/basics/installation/)），数据不离开本机

## 常见坑

| 现象 | 原因 | 修复 |
|---|---|---|
| val mAP 比 train 还高 | 自动拆分把同视频相邻帧分两边 | 用第 3 步的手动拆分 |
| 训练 loss 不降 | learning rate 不匹配 imgsz | 加 `--imgsz 320` 重试 |
| 推理慢 | 用了 m / l / x 大模型 | 切回 s 级别（22MB） |
| 多人场景反而变差 | 训练集只有单人 | 补 2–8 人样本 |
| `--device mps` 报错 | torch 没装 metal 后端 | 装 `torch>=2.0` 或 fallback `cpu` |

## 相关文件

- `tools/preannotate.py` — 半监督预标注脚本
- `tools/train_pose.py` — ultralytics 训练包装
- `tools/eval_pose.py` — ultralytics 评估包装
- `data/training/syncswim.yaml` — 数据集配置
- `fastapi_app/yolo_pose.py` — 生产推理路径，部署后切换 `yolo_model` 即可
- DEVLOG #28 — 7.4 设计回顾

## 路线图

- [x] 7.4 完成：脚本 + 文档（本文）
- [ ] 7.0 完成：教练上传 200–500 帧真实素材
- [ ] 7.4 实训：跑一次完整流程出第一个 `best.pt`
- [ ] 后续：每月迭代，加新数据继续训
