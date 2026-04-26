# Emily 标注流程 onboarding

> 本指南给**Emily**（或任何加入花泳数据集标注的伙伴）。
> 主指南是 `docs/phase-a-annotation.md`（标注规则 / 操作）— 本指南补
> "在自己的电脑上从零搭起来 + 把标注结果交回总统大人"。
>
> 总指挥（总统大人）的 onboarding 见主指南；Emily 直接看本文即可。

---

## 1. 你需要什么（一次性，~30 分钟）

| 工具 | 干什么 | 安装 |
|---|---|---|
| Docker Desktop（或 OrbStack） | 跑 CVAT | https://docs.docker.com/desktop/install/mac-install/ — 装好之后第一次启动会要 Apple ID 授权 |
| Python 3.10+ | 跑抽帧脚本 | macOS 自带 `python3 --version` 检查；不够新就 `brew install python@3.11` |
| Git | 拉代码 | `xcode-select --install`（如果之前没装过 Xcode tools） |
| 浏览器 | 用 CVAT | Safari / Chrome / Firefox 任选 |

硬件最低要求：
- **8GB RAM**（够 — CVAT 单人用 ~3GB，留 5GB 给系统）
- **20GB 可用磁盘**（CVAT 镜像 ~5GB，标注数据 ~50MB）
- 不需要 GPU（标注是纯 CPU 任务）

---

## 2. 拿到代码 + 视频 + 帧（~5 分钟）

总统大人会把以下三样发给你（推荐用网盘 / AirDrop / 微信文件传输）：

1. **`syncswim-dashboard` 代码仓库的访问权限**
   ```bash
   git clone https://github.com/BilltheChurch/syncswim-dashboard.git
   cd syncswim-dashboard
   git checkout main   # 或者 PR #8 合并后的最新分支
   ```

2. **`phase_a_frames.zip`（~30 MB，~150 张 jpg）**
   总统大人在他自己机器上跑 `python tools/extract_frames.py --per-video 50`
   会得到 `data/training/phase_a/frames/` 目录，~150 张图。**他打 zip 发给你**：
   ```bash
   # （总统大人的命令，不是你的）
   cd data/training/phase_a
   zip -r phase_a_frames.zip frames/
   ```
   你拿到后：
   ```bash
   mkdir -p data/training/phase_a
   unzip ~/Downloads/phase_a_frames.zip -d data/training/phase_a/
   ls data/training/phase_a/frames/ | wc -l   # 应该 ~150
   ```

3. **可选：原视频（~1 GB）**
   只在你想自己抽帧 / 看完整 clip 上下文的时候要。**默认不需要** — 标注只要 jpg。

> **为什么不让你直接 git pull 视频？** 视频文件 1.6 GB，git 仓库扛不住，所以 .gitignore 排除了 `data/raw_videos/` + `data/training/phase_a/frames/`。视频和帧都是文件传输，不是 git 同步。

---

## 3. 启动 CVAT（首次 ~10 分钟，之后 ~30 秒）

```bash
# 找一个固定位置放 CVAT — 推荐 home 目录
cd ~
git clone --depth 1 https://github.com/cvat-ai/cvat
cd cvat

# 设置访问域名为 localhost（默认是 cvat.example.com，会让浏览器拒绝）
export CVAT_HOST=localhost

# 拉镜像 + 启动（首次 ~5-10 分钟，看网速）
docker compose up -d

# 创建你的账号（用户名 / 邮箱 / 密码，密码自己定）
docker exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser'
```

之后每次开机：
```bash
cd ~/cvat
export CVAT_HOST=localhost
docker compose up -d   # ~30 秒
```

打开浏览器访问：**http://localhost:8080**，用刚才创建的账号登录。

> **如果看到 502 Bad Gateway**：等 1-2 分钟，CVAT 后端启动慢；刷新即可。
>
> **如果 docker compose 报端口冲突**：你电脑上有别的服务占用了 8080 端口。运行 `lsof -i :8080` 查谁占着，关掉那个进程或者临时改 CVAT 的端口。

---

## 4. 第一次标注（~1-2 小时）

完整规则在 **`docs/phase-a-annotation.md`** 第 4 步。这里只列**最容易踩的 5 条**：

| 规则 | ✅ 对 | ❌ 错 |
|---|---|---|
| 每个运动员一个 bbox | 5 个运动员 = 5 个框 | 把所有人框成一个大框 |
| **bbox 包水下能看到的身影** | bbox 从脚尖一直拉到水下身影模糊处 | 在水面就停、只框水上腿（这是最常见的错） |
| 紧贴边缘 | 上下左右各 ~3px buffer | 框得很松（buffer 20px+） |
| 露出多少标多少 | 只露脚也要标（但要把水下能看的部分也包进去） | 因为"半身入水看不全"就跳过 |
| 不标无关人 | 教练 / 观众 / 路人 → ❌ | 把岸上的人也框了 |
| 不标反射 | 水面倒影 → ❌ | 把倒影也当一个人 |
| 同帧风格统一 | 5 个 bbox 都偏紧 或 都偏松 | 1、4、5 偏紧，2、3 偏松 |

> **为什么 bbox 一定要包水下身影**：那块暗影是真实像素信号，不包进去 = 告诉模型"那不是运动员"，会导致 (1) Phase B 水下关键点训练失败，(2) 跨帧 bbox 大小跳变 → BYTETracker 把同一人当成新人发新 ID（这就是 dogfood 19.8× ID 通胀的根因）。详见 `docs/phase-a-annotation.md` §"bbox 怎么画 — 核心规则"。

**节奏建议**：
- 前 30 帧最慢（适应期，每帧 ~1 分钟）
- 之后熟练了能跑到 ~20 秒/帧
- 累了就停，CVAT 自动保存
- 每标 30 帧休息 5 分钟（眼睛会累）

**关键操作提醒**（详见 `docs/phase-a-annotation.md` 实测快捷键表）：
- 画 bbox 前**必须先在左侧工具栏点中矩形 ▢ 图标**，否则按 N 会开 Intelligent Scissors（多边形剪刀，不是 bbox）
- 弹窗里 Drawing method 选 **By 2 Points**（不是 4 Points）
- 模式选 **Shape**（不是 Track）— Track 会跨帧自动插值，但我们的帧是 5 秒间隔抽的，插值出来全错
- F = 下一帧，D = 上一帧（CVAT 2.x 改了语义，**D 不再是"复制 bbox"**）

---

## 5. 标完了导出 + 发给总统大人

CVAT 标注界面右上：
1. **Menu → Export task dataset**
2. **Export format**: `YOLO 1.1`
3. **Save images**: ❌ 不勾（节省体积）
4. 点击下载，得到 `task_xxx.zip`

发给总统大人：
- 文件名最好改成 `phase_a_labels_emily_YYYYMMDD.zip`（带你的名字 + 日期方便归档）
- 微信 / AirDrop 都行（zip 包很小，~1 MB）

总统大人收到后会做（你不需要管这步）：
```bash
# （总统大人的命令）
unzip phase_a_labels_emily_20260427.zip -d /tmp/emily_labels
mv /tmp/emily_labels/obj_train_data/*.txt data/training/phase_a/labels/
# 然后 python tools/train_detector.py
```

---

## 6. 协作注意事项

### 跟总统大人怎么对齐

如果你和总统大人**都在标同一批 150 帧**：

- **不推荐**：两人标同一帧，因为风格不一致会引入噪声
- **推荐**：分工 — 总统标 0-74 帧，你标 75-149 帧（按文件名字母序）
  - 你只在 CVAT 里上传**你那一半**的帧，避免重复劳动
  - 最后两人各自导出 labels，总统大人合并

如果**你独立标完一整套 150 帧**作为"Emily 版本"：

- 跟总统标的"v1 版本"形成 cross-check
- 哪些帧两人画法差异大？用来定义标注规范的边界 case
- 这套额外标注虽然花时间，但对模型质量提升很大

### 怎么问问题

标注过程中遇到拿不准的 case（比如"这个半身入水的运动员到底标不标"），**最有效的方式**：

1. CVAT 里截屏（包含运动员位置）
2. 发给总统大人 + 写一句"这种情况标 / 不标？"
3. 总统拍板后，**回到这条 case，给类似 case 标统一**

文档第 4 步的 ✅/❌ 表会随这些 case 持续更新（总统大人维护）。

---

## 7. 常见问题

| 问题 | 解决 |
|---|---|
| Docker Desktop 启动很慢 / 卡 | 给它分 4 GB RAM 起步（Settings → Resources） |
| CVAT 上传 jpg 后看不到图 | 文件名有中文 / 空格？我们的命名 `clip_horizontal_f000028.jpg` 是纯 ASCII，正常应该没事；如果你自己改名注意别加中文 |
| 浏览器一直转圈 | 可能是 CVAT 后台还在初始化 — `docker compose logs cvat_server | tail -20` 看有没有错；通常等 2 分钟 |
| 标错了想撤销 | Ctrl+Z（CVAT 支持多步撤销） |
| 想关 CVAT 省内存 | `cd ~/cvat && docker compose down`（数据保留，下次 up 还在） |
| Mac 风扇狂响 | OrbStack / Docker Desktop 在跑大量后台进程，正常；标注完关掉就好 |
| 想清空所有 CVAT 数据重来 | `docker compose down -v`（**会删除所有标注**，谨慎用） |

---

## 8. Time budget 给你打个气

| 步骤 | 时长 | 你需要操作 |
|---|---|---|
| 装 Docker + Python | 30 分钟 | 一次性 |
| 拿到代码 + 帧 | 5 分钟 | 一次性 |
| 启动 CVAT + 建账号 | 10 分钟 | 一次性 |
| **标注 ~150 帧** | **1-2 小时** | 主要时间 |
| 导出 + 发给总统 | 5 分钟 | 每次 |

**总计：第一次 ~3 小时，第二次起 ~2 小时**（一切已就绪，只剩纯标注）。

谢谢你帮忙！花泳骨架检测的"水下半身识别"问题，靠的就是这一批人工标注 — 模型没法自动学会"哪些是真运动员"，必须有人画框告诉它。

---

## 相关文档

- `docs/phase-a-annotation.md` — **完整标注规则 + 边界 case + CVAT 详细操作**（必读第 4 步）
- `docs/fine-tuning.md` — Phase B（关键点头微调，之后另外做）
- DEVLOG #33 — 为什么这些标注是必须的
- DEVLOG #34 — Phase A 工具链设计
