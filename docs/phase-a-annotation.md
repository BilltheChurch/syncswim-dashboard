# Phase A — 检测器（bbox）微调标注指南

> 阶段 9.1 产出。先把 ~150 帧花泳运动员的 bbox 标好 → 训练专用 detector → 解决 dogfood 暴露的 19.8× ID 暴增问题。
>
> Phase B（关键点头微调）放到 `docs/fine-tuning.md`，本指南只管 bbox。

## 为什么先做 Phase A

DEVLOG #33 量化了 dogfood 结果：5 个运动员的 90 秒视频被 YOLO COCO 检测出 99 个不同的 track ID（19.8× 暴增）。根本原因不是 tracker 烂，而是**检测器召回率太低**：

- COCO YOLO 没见过水中花泳，水花、半身入水、泳帽几乎全 miss
- 检测器一会儿检到、一会儿丢，BYTETracker 拿不到连续观测就会"开新 ID"
- 哪怕用 `imgsz 1280 + conf 0.15` 的 trick 也只能从 ~7% 召回拉到 ~30%

Phase A 用 ~150 帧自定义标注，把单类 detector 训到 mAP@50 ≥ 0.70，预期：

- 召回 70%+ → 同一个运动员能被连续检测到
- BYTETracker 拿到稳定观测 → ID 几乎不漂
- 关键点暂时还是 COCO 通用的 — 还有问题，但比 ID 乱跳容易容忍很多
- Phase B（之后另起 PR）再训关键点头

**预期工作量**：
| 步骤 | 自动 / 人工 | 时长 |
|---|---|---|
| 抽帧 | 自动 | ~10 秒 |
| CVAT 上传 + 项目搭建 | 人工 | ~10 分钟（首次）/ ~3 分钟（之后） |
| **bbox 标注 ~150 帧** | **人工（最关键）** | **1-2 小时** |
| 拆分训练 / 验证集 | 自动（一行 ls） | ~10 秒 |
| 训练 | 自动 | M2 16GB 上 ~30 分钟 |
| 验证 + 上线 | 半自动 | ~5 分钟 |

合计：**人工占 1-2 小时**，机器跑 30 分钟。一个晚上能做完。

---

## 第 0 步：准备帧

```bash
# 把训练视频放到 data/raw_videos/（已经有 3 个 clip 了）
ls data/raw_videos/
# clip_horizontal.mp4
# clip_portrait_1.mp4
# clip_portrait_2.mp4

# 抽帧（每个视频抽 50 帧，3 × 50 = 150）
python tools/extract_frames.py --per-video 50

# 输出在 data/training/phase_a/frames/
# 文件名：clip_horizontal_f000123.jpg
ls data/training/phase_a/frames/ | head
```

参数：
- `--per-video 50`：每个视频均匀抽 50 帧（不是每 N 帧抽 1 帧 — 均匀分布跨整个 clip 多样性更好）
- `--edge-skip-pct 0.03`：丢掉首尾 3%（fade-in/out + 还没下水的镜头）

**为什么不预标注？** 我们已经知道 COCO YOLO 在花泳上召回 ~7%，预标注会漏掉 93%，标注员还得手画 — 等于双倍工作量。Phase A 直接从空白画 bbox 反而快。

---

## 第 1 步：选 CVAT 部署方式

| 方式 | 优点 | 缺点 | 推荐 |
|---|---|---|---|
| **本地 Docker**（推荐） | 数据不离开本机，无肖像权风险 | 首次装 ~15 分钟 | ⭐ 默认选这个 |
| 云端 cvat.ai 免费版 | 5 分钟开干 | 视频会上传到云 — 必须确认所有出现的运动员都签过授权 | 仅在测试时用 |
| Label Studio | 同样能干 | 关键点支持差，bbox 还行 | 有 Tim 老师偏好可选 |

### 本地 CVAT（首次安装）

```bash
git clone https://github.com/cvat-ai/cvat
cd cvat
export CVAT_HOST=localhost
docker compose up -d

# 创建超级用户
docker exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser'
# 用户名: admin，邮箱随便，密码自己定

# 浏览器打开
open http://localhost:8080
```

之后每次开机：
```bash
cd ~/cvat && docker compose up -d   # ~30 秒启动
open http://localhost:8080
```

---

## 第 2 步：建 CVAT 项目

1. 登录后右上角 **+** → **Create new project**
2. Project name: `syncswim-detector-phase-a`
3. Labels:
   - 点 **Add label**
   - Label name: `person`
   - Type: **Rectangle**（bbox，不是 polygon、不是 skeleton）
   - 颜色：随便，建议红色
4. **Submit & Open**

---

## 第 3 步：上传帧

1. 项目页 → 右下 **+** → **Create new task**
2. Task name: `syncswim-150-frames`
3. **Select files** → **My computer** → 把 `data/training/phase_a/frames/` 目录里**所有 jpg** 一起拖进去（Cmd+A 全选）
   - 不要打 zip — CVAT 直接吃文件夹
   - 150 张 jpg ~30MB，1 秒上传
4. Advanced configuration（保持默认就行）：
   - Image quality: `70` ✓
   - Chunk size: `36` ✓
   - Sorting: `lexicographical` ✓（按文件名排，相邻帧相邻）
5. **Submit**
6. 等 ~30 秒处理完，点 task → **Job #1** 进入标注界面

---

## 第 4 步：标注规则（**最关键，认真读**）

### 标 / 不标

✅ **要标**：
- 任何**正在练习的花泳运动员**，哪怕只露出脚 / 手 / 头
- **包含水下能看到轮廓的身体部分**（详见下方"水下身影怎么处理"）
- 多人重叠 — **每人一个独立 bbox**，IoU 高没关系（YOLO 训练时会处理）

❌ **不要标**：
- 教练（站在岸边）
- 观众
- 路过的工作人员
- 岸边的器材、椅子
- 队友的影子或水面反射

### bbox 怎么画 — 核心规则

**bbox 边缘 = 你能看到的运动员身体边缘**，无论它在水面以上还是以下。

**水面不是 bbox 的天然下边界**。看到水下身影就往下拉到身影末端。

#### 为什么这条最关键

只框水面以上（"只标腿"）有 3 个真实代价：

1. **扔掉水下像素信号** — 那团暗影是真实信号，不框等于告诉模型"那不是运动员"。Phase B 关键点（双髋等水下点）的训练直接依赖这块区域。
2. **跨帧 bbox 大小跳变** — 同一运动员一会儿全身浮、一会儿只露腿，bbox 高差 3×，BYTETracker 会判定"不是同一个人"重发 ID。**dogfood 19.8× ID 通胀的根因之一**就是这个。
3. **跨帧不一致 = 训练数据噪声** — 同一帧里 5 个运动员有的标紧、有的标松，模型学到"swimmer 高度随机"，mAP 撑不上去。

#### 具体怎么判断水下边界

```
顶部边缘 ━━━━━━ 脚尖（最高的脚趾上方 ~3px buffer）
    │
    │  ← 水上腿部
    │
─ ─ ─水面 ─ ─ ─  （照穿过去，不要在这里停）
    │
    │  ← 水下能看到的暗色身影
    │
底部边缘 ━━━━━━ 身影模糊到看不清的地方
```

**"看不清"判定**：你眯着眼睛看，能不能确认那个像素属于运动员？

- 能 → 包进 bbox
- 不能 → bbox 边缘停在这里

**保守原则**：宁可框小一点（少包 30 px），也不要框到纯水里 — 纯水进 bbox 就是噪声。

#### 其他细节

- **侧面 buffer**：左右各留 ~3px，不要过松（紧框 + 准位置比松框更利于训练）
- **完全淹没的运动员**：如果你能看到水下完整身影，标；如果连身影都看不清（深度太大或水太浊），跳过整个对象
- **统一性 > 完美性**：同一帧、同一距离的运动员 bbox 高度比例应该接近 — **整体偏紧或整体偏松，但不要混着来**（不同景深距离差别大没关系）

### 遮挡（occlusion）规则 — 团队运动核心场景

花泳几乎每一帧都有运动员重叠。判断标准很清楚：

#### 完全遮挡：跳过

✅ **完全看不到 = 不标**
- 只剩水花、连个轮廓都看不到 → **不要框**
- 你猜测位置即使猜对了，那个区域的像素全是别人的身体 → 模型学到"别人的身体也是 swimmer" → 严重污染数据
- COCO 官方规则就是这条
- **唯一例外**：能看到一点水花、手指尖、衣物边缘 → 框那个可见部分（哪怕只有 20×30 px）

#### 部分遮挡：照常标，bbox 重叠完全 OK

✅ **bbox 可以大幅重叠**
- IoU 0.7+ 都正常 — 团队运动场景的 ground truth 本来就长这样
- COCO 行人 / 球员数据集里 IoU > 0.8 的样本一堆
- YOLO 训练的 NMS 机制就是为多人重叠设计的，不会冲突

✅ **画到"能看到的这个运动员的边缘"**
- 露头 → 框头
- 露肩 → 框到肩边
- 水下能看到**她自己的**身影 → 包进去
- **就算 bbox 跟另一人重叠 60%，也照画**

❌ **不要画到"猜她应该在的位置"**
- 她的胸应该在另一个运动员后面 → 不要延伸过去（你看到的那块像素是另一个人，框过去 = 把别人的身体也标成她）
- 不要延伸进纯水区域

#### 距离造成的尺寸差不算"不一致"

斜视角 / 远近景深差大的镜头，bbox 高度可以差 2-3×（远的小、近的大），**这是真实的几何**，不算违反"统一性"。统一性指的是"同一距离的运动员要画风一致"，不是"所有运动员都一样大"。

### CVAT 2.63+ 快捷键（实测，不是猜的）

| 键 | 动作 |
|---|---|
| **F** | 下一帧 |
| **D** | **上一帧**（注意：不是"复制 bbox"，CVAT 2.x 改了语义） |
| **N** | "新建当前选中工具的对象" — **必须先在左侧工具栏点中矩形 ▢ 图标**，N 才会画 bbox；如果选中的是 Intelligent Scissors，N 就开剪刀 |
| **Tab** | 在已有 bbox 之间循环切换 |
| **Delete** | 删除选中 bbox |
| **Ctrl+B** | Propagate（复制当前帧 bbox 到后面 N 帧，弹窗选 N） |
| **Ctrl+C / Ctrl+V** | 复制 / 粘贴 bbox 到当前帧 |
| **Ctrl+S** | 保存（CVAT 也每 30s 自动保存） |
| **Esc** | 取消当前操作 |
| 右键 bbox → Propagate | Ctrl+B 的菜单入口 |

### 重要：Drawing method 永远选 "By 2 Points"

弹出 "Draw new rectangle" 时：

- **By 2 Points** ✅ — 点对角两个点，拖出轴对齐矩形（**我们的场景就用这个**）
- By 4 Points ❌ — 给带角度倾斜物体（车牌 / 倾斜船只）画旋转包围盒，游泳运动员用不上

### 重要：Shape 而不是 Track

弹窗下面有 ┃Shape┃ ┃Track┃ 两个按钮：

- **Shape** ✅ — 单帧 bbox，**只在当前这张图上**。我们要的就是这个。
- **Track** ❌ — 跨帧自动插值。但我们的 150 帧是 5 秒间隔抽的，5 秒后运动员位置完全变了，插值出来全是错的 → YOLO 训练吃进去就是噪声 → mAP 反而下降。

如果不小心点了 Track，右侧 Objects 面板那条会显示 "RECTANGLE TRACK"（带 ◀ ▶ 帧导航按钮）。**立刻删掉重画成 Shape**。

### 节奏建议

- 我们的场景每帧间隔 ~5 秒，运动员位置变化大 → **每帧从零画**比 propagate 快
- 一次画完同帧所有运动员（4-5 个 bbox）→ F 跳下一帧 → 重新画
- 累了就停，CVAT 自动保存，下次接着干

预期速度：**前 30 帧 ~1 分钟/帧（适应期），之后 ~20 秒/帧**。150 帧总计 1-2 小时。

---

## 第 5 步：导出标注

1. 项目页 → **Actions** → **Export task dataset**
2. Export format: **YOLO 1.1**
3. ✗ **Save images**（不要勾，节省 30MB 而且我们已经有原图了）
4. 点击下载，得到 `task_syncswim-150-frames.zip`

解压：
```bash
unzip ~/Downloads/task_syncswim-150-frames.zip \
      -d data/training/phase_a/labels_raw/
# CVAT 的 YOLO 1.1 zip 里 labels 在 obj_train_data/ 子目录
mv data/training/phase_a/labels_raw/obj_train_data/*.txt \
   data/training/phase_a/labels/
rm -rf data/training/phase_a/labels_raw/
```

验证：
```bash
ls data/training/phase_a/labels/ | wc -l    # 应该约等于 150
head -1 data/training/phase_a/labels/clip_horizontal_f000123.txt
# 0 0.512345 0.678901 0.123456 0.234567
# (class cx cy w h，全部归一化到 [0,1])
```

如果看到 `0 0.5 0.5 0.1 0.1` 这种整齐数字，说明 bbox 没正确标注（可能选了"导出空标"）—  回 CVAT 检查。

---

## 第 6 步：拆分 train / val

**死规矩：val 必须是训练集没见过的视频**。如果把 `clip_portrait_1` 的相邻帧分到两边，val mAP 会虚高 30%，毫无参考价值。

我们 3 个 clip：
- `clip_horizontal.mp4` → **val**（横屏 + 不同视角，最适合做 hold-out）
- `clip_portrait_1.mp4` → train
- `clip_portrait_2.mp4` → train

```bash
cd data/training/phase_a

# val.txt：clip_horizontal 的全部帧
ls frames/clip_horizontal_*.jpg | sed 's|^|./|' > val.txt

# train.txt：除此之外的全部帧
ls frames/clip_portrait_1_*.jpg frames/clip_portrait_2_*.jpg \
   | sed 's|^|./|' > train.txt

# 检查
wc -l train.txt val.txt
# 100 train.txt
#  50 val.txt
```

> **注意**：`./` 前缀让 ultralytics 从 `swimmer_det.yaml` 的 `path:` 字段（`../../data/training/phase_a`）开始解析。

---

## 第 7 步：训练

```bash
python tools/train_detector.py
```

默认参数（已针对水中场景优化）：
- `epochs=80` — 150 帧 × 80 epoch ≈ 12000 step，小数据集合适
- `imgsz=1280` — DEVLOG #33 实证：水中小目标在 640 下消失，1280 下能稳检
- `batch=8` — M2 16GB 上限（1280 imgsz 比 640 多用 4× 显存）
- `device=mps` — Apple Metal；NVIDIA 加 `--device cuda`

M2 16GB 训练时间：~30 分钟。期间可以去喝咖啡。

训练完输出：
```
runs/detect/swimmer_det_v1/
├── weights/
│   ├── best.pt    ← 这是要用的
│   └── last.pt
├── results.png   ← loss / mAP 曲线
├── PR_curve.png  ← 精度-召回曲线
└── val_batch0_pred.jpg  ← 验证集第一批的预测可视化（**先看这个**）
```

第一时间打开 `val_batch0_pred.jpg` —— 如果框基本贴脸，训练成功；如果框乱飞，回去检查标注。

---

## 第 8 步：验证

```bash
python tools/eval_detector.py
```

输出：
```
[trained]
  mAP@50      : 0.7842
  mAP@50-95   : 0.5311
  recall      : 0.8124

[baseline yolov8s.pt at imgsz 1280]
  mAP@50      : 0.0834   ← 在花泳上几乎瞎
  recall      : 0.0721

[delta]
  mAP@50      : +0.7008
  recall      : +0.7403   ← 这就是我们要的

[verdict]
  ✅ mAP@50 = 0.7842 ≥ 0.70 — Phase A target hit.
```

判定：
- **mAP@50 ≥ 0.70** → 上线，开 PR
- **0.50 ≤ mAP@50 < 0.70** → 能用但 ID 还是会稍漂，**再标 50-100 帧**重训
- **mAP@50 < 0.50** → 标注质量有问题，重看 §第 4 步规则

---

## 第 9 步：上线 + 量化验证（Phase 9.1.3）

### 9a. config.toml 接入

编辑 `config.toml`：
```toml
[hardware]
swimmer_detector = "runs/detect/swimmer_det_v1/weights/best.pt"
```

### 9b. 重 import 3 段 dogfood 视频，看 ID 通胀降到多少

这一步是判断 Phase A 真正成败的"现场实测"。`tools/import_video.py` 加了 `--expected-swimmers` 选项，结束会自动打印 ID 通胀比：

```bash
# 重 import clip_horizontal（你知道里面有 5 个运动员）
python tools/import_video.py data/raw_videos/clip_horizontal.mp4 \
  --expected-swimmers 5

# 输出会有这一段：
#   [id-stats]
#     frames analyzed         : 961
#     frames with ≥1 detection: 850 (88.5%)  ← recall proxy
#     unique track IDs total  : 12
#     max simultaneous IDs    : 5
#     expected swimmers       : 5
#     ID inflation ratio      : 2.4× (baseline DEVLOG #33: 19.8×)
#     verdict                 : ✅ acceptable (≤3×) — Phase A target hit
```

**判定标准**：

| ratio | 判定 | 行动 |
|---|---|---|
| ≤ 3× | ✅ Phase A 成功 | 决定要不要做 Phase B（关键点） |
| 3-10× | ⚠ 改善了但不够 | 标 50-100 帧加训，**或**做 Phase 9.3 数据扩充 |
| > 10× | ❌ 几乎没改善 | 检查 mAP@50、标注一致性 — 标注质量肯定有问题 |

3 个 dogfood 视频都跑一遍，3 个 ratio 都 ≤ 3 才算稳定通过。

### 9c. dashboard 实时观感

```bash
# 在你的终端（不是 claude 沙箱）
python -m fastapi_app
```

`fastapi_app/yolo_pose.py` 自动检测到 `swimmer_detector` 参数，加载混合模式：
- **bbox 检测**：用你刚训的 `best.pt`（高召回）
- **关键点**：还是用 `yolov8s-pose.pt`（COCO 通用，等 Phase B 替换）

浏览器看新 import 的 set 的分析页：
- ✅ ID 颜色不闪烁、运动员名称不跳变 → Phase A 真正落地
- ⚠ ID 还是变（但比之前好） → 9.1.3 verdict 要记录下来，决定是 Phase B 还是 9.3 数据扩充

---

## 数据隐私

- `data/raw_videos/`、`data/training/phase_a/frames/`、`data/training/phase_a/labels/`、`runs/` 都已在 `.gitignore` — 视频和帧不会被提交
- **本地 CVAT 强烈推荐** — 云端 cvat.ai 免费版会把视频上传到第三方
- 如果一定要用云端：先在出现的所有运动员身上获得书面授权
- 训练好的 `best.pt` 是模型权重，**不含原图**，理论上可分享 — 但花泳社群是熟人圈，建议保密

---

## 常见坑

| 现象 | 原因 | 修复 |
|---|---|---|
| `train.txt` 里有 jpg 文件名但 `.txt` 标注找不到 | CVAT 跳过了无标注的帧 | 删掉 `train.txt` 里对应行（或用 `find` 自动配对） |
| 训练 loss 一直高，mAP 不动 | 标注质量太差（框很松、框错对象） | 抽 10% 帧人工 review，统一标注规范 |
| `val_batch0_pred.jpg` 全是虚警 | val 集和 train 集分布差太远 | 改用同一池子但不同时段的视频做 val |
| `mps` 报错 OOM | imgsz 1280 + batch 8 超 16GB | 降到 `--batch 4 --imgsz 960` |
| CVAT 上传 jpg 后看不到图 | 文件名包含中文或特殊字符 | 重命名（extract_frames.py 输出本身是纯 ASCII，应该没事） |

---

## 相关文件

- `tools/extract_frames.py` — 抽帧脚本（本指南第 0 步）
- `tools/train_detector.py` — 训练脚本（本指南第 7 步）
- `tools/eval_detector.py` — 验证脚本（本指南第 8 步）
- `data/training/phase_a/swimmer_det.yaml` — 数据集配置
- `fastapi_app/yolo_pose.py` — 生产推理路径（本指南第 9 步上线点）
- `docs/fine-tuning.md` — Phase B（关键点头微调），等 Phase A 落地后再做
- DEVLOG #33 — 为什么必须 fine-tune 的实证
- DEVLOG #34 — Phase A 工具链落地（本 PR）

## 时间表

- [x] 9.1.0 工具链 + 文档（本 PR）
- [ ] 9.1.1 Tim 老师本周内完成 ~150 帧标注（**1-2 小时人工**）
- [ ] 9.1.2 跑训练（~30 分钟自动）
- [ ] 9.1.3 验证 mAP ≥ 0.70（~5 分钟）
- [ ] 9.1.4 上线 + dashboard 实测（开新 PR）
- [ ] 9.2 Phase B 关键点头微调（之后另开 PR）
- [ ] 9.3 数据扩充（5-10 个新池子的视频，跨 venue 验证）
