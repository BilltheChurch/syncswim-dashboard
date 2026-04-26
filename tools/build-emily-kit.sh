#!/bin/bash
# build-emily-kit.sh — 一行命令打包给 Emily 的完整工作包
#
# 跑一次会输出 ./emily_kit_YYYYMMDD.zip，包含：
#   ├── README.md                       ← 给 Tim 老师的现场装机清单
#   ├── 密码模板.txt                     ← 留给 Tim 老师填 Emily 的 CVAT 密码
#   ├── setup/
#   │   └── setup-system.command       ← Tim 老师双击：一次性装全套
#   ├── desktop/
#   │   ├── 1-update.command           ← Emily 桌面：拉最新
#   │   ├── 2-start-cvat.command       ← Emily 桌面：启 CVAT 标注
#   │   ├── 3-start-dashboard.command  ← Emily 桌面：启 dashboard 训练
#   │   └── cheatsheet.html            ← Emily 桌面：标注速查表
#   ├── models/
#   │   ├── yolov8s-pose.pt            ← YOLO pose 模型（22MB）
#   │   └── pose_landmarker_lite.task  ← MediaPipe 备选模型（5MB）
#   ├── videos/
#   │   └── raw_videos.zip             ← 3 段花泳训练视频（~11MB）
#   └── frames/
#       └── phase_a_frames_150.zip     ← Phase A 待标 ~150 张帧（~20MB）
#
# 总大小约 60MB，AirDrop / 微信文件 都扛得住。
#
# 用法：
#   bash tools/build-emily-kit.sh
#   # 然后 AirDrop / 微信发 emily_kit_*.zip 给 Emily

set -e

# ────────── 找仓库根 + venv ──────────
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
    echo "[error] 必须在 git 仓库内执行（找不到仓库根）"
    exit 1
fi
cd "$REPO_ROOT"

# venv 路径：worktree 用的是父仓库的 .venv（参考 docs/phase-a-annotation.md 第 0 步）
PY="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
    PY="/Users/billthechurch/Downloads/test_rec/.venv/bin/python"
fi
if [ ! -x "$PY" ]; then
    echo "[error] 找不到 venv: 试过 $REPO_ROOT/.venv 和主仓库 .venv"
    exit 1
fi

# ────────── 必备文件检查（fail fast）──────────
required=(
    "yolov8s-pose.pt"
    "pose_landmarker_lite.task"
    "data/raw_videos"
    "tools/setup-system.command"
    "tools/start-cvat.command"
    "tools/start-dashboard.command"
    "tools/update.command"
    "docs/emily-cheatsheet.html"
)
missing=()
for f in "${required[@]}"; do
    if [ ! -e "$f" ]; then
        missing+=("$f")
    fi
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "[error] 缺以下文件，请先准备好再打包："
    for f in "${missing[@]}"; do
        echo "  - $f"
    done
    echo ""
    echo "提示：raw_videos / yolov8s-pose.pt 通常在 worktree，需要先 cp 到主仓库根。"
    exit 1
fi

# requirements.txt 不强制，但缺会用最小依赖集，提醒一下
if [ ! -f requirements.txt ]; then
    echo "[warn] 主仓库根没有 requirements.txt"
    echo "       Emily 装机时会用最小依赖集（fastapi/uvicorn/opencv/ultralytics/mediapipe/bleak）"
    echo "       推荐：在主仓库 venv 里跑 'pip freeze > requirements.txt' 确保依赖一致"
    echo ""
fi

# ────────── 1. 抽帧（如果没抽过）──────────
FRAMES_DIR="data/training/phase_a/frames"
if [ ! -d "$FRAMES_DIR" ] || [ "$(ls -1 "$FRAMES_DIR" 2>/dev/null | wc -l)" -lt 50 ]; then
    echo "[+] 没找到足够帧，跑 extract_frames.py..."
    "$PY" tools/extract_frames.py --per-video 50
fi
FRAME_COUNT=$(ls "$FRAMES_DIR" | grep -c '\.jpg$' || echo 0)
echo "[+] 已有 $FRAME_COUNT 张帧待打包"
if [ "$FRAME_COUNT" -lt 30 ]; then
    echo "[error] 帧数太少（$FRAME_COUNT）— 检查 data/raw_videos/ 是否有视频"
    exit 1
fi

# ────────── 2. 准备 kit 目录 ──────────
TS=$(date +%Y%m%d)
KIT_DIR="emily_kit_$TS"
rm -rf "$KIT_DIR"
mkdir -p "$KIT_DIR"/{setup,desktop,models,videos,frames}

# 2a. 帧 zip
echo "[+] 打包 $FRAME_COUNT 张帧..."
(cd "$FRAMES_DIR/.." && zip -qr "$REPO_ROOT/$KIT_DIR/frames/phase_a_frames_150.zip" frames/)

# 2b. setup 脚本（一次性现场装机）
cp tools/setup-system.command "$KIT_DIR/setup/setup-system.command"
chmod +x "$KIT_DIR/setup/setup-system.command"

# 2c. 桌面 3 个图标 + cheatsheet
cp tools/update.command          "$KIT_DIR/desktop/1-update.command"
cp tools/start-cvat.command      "$KIT_DIR/desktop/2-start-cvat.command"
cp tools/start-dashboard.command "$KIT_DIR/desktop/3-start-dashboard.command"
cp docs/emily-cheatsheet.html    "$KIT_DIR/desktop/cheatsheet.html"
chmod +x "$KIT_DIR/desktop/"*.command

# 2d. 模型文件
cp yolov8s-pose.pt           "$KIT_DIR/models/"
cp pose_landmarker_lite.task "$KIT_DIR/models/"

# 2e. 训练视频
echo "[+] 打包 raw_videos..."
(cd data && zip -qr "$REPO_ROOT/$KIT_DIR/videos/raw_videos.zip" raw_videos/)

# 2f. 密码模板
cat > "$KIT_DIR/密码模板.txt" <<'EOF'
Emily 的 CVAT 账号
==================

URL:      http://localhost:8080
用户名:   emily
密码:     ____________________
邮箱:     ____________________

（Tim 老师在 Emily 电脑现场装机时填这张表，
  填好后让 Emily 第一次登录后让浏览器记住密码，
  此文件之后可删 / 留作备份）

GitHub PAT（用于 git pull 不用密码）
=====================================

PAT:      ghp_____________________

（在 setup-system.command 里输入一次后会存进 macOS Keychain，
  之后所有 git pull 都自动用这个，Emily 不用知道是什么）
EOF

# 2g. README — 给 Tim 老师的现场装机清单
cat > "$KIT_DIR/README.md" <<'EOF'
# 给 Tim 老师 — Emily 完整环境装机清单

Emily 装完之后，桌面有 3 个图标她每天用，你不在场也能正常工作。

## 你需要带的
- 这个 `emily_kit_*` 文件夹（已经在 Emily 桌面）
- 一个 GitHub PAT（read 权限即可，建议 90 天有效期）
- ~1 小时时间（含网速等待）

---

## 第 1 步：Homebrew 必装（如果 Emily 电脑没有）

打开终端（Cmd+空格搜 Terminal）：
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
跟提示走，10 分钟左右。

## 第 2 步：双击装机脚本（自动 ~25 分钟）

Finder 进 `emily_kit_*/setup/` → 双击 `setup-system.command`。

会自动做：
- 装 python@3.11 / git / OrbStack（轻量 Docker）
- 配 GitHub Keychain（中途让你输 PAT 一次，不回显）
- clone syncswim-dashboard
- 创建 venv + pip install
- 拷模型 + 解压 raw_videos
- clone CVAT + 拉镜像
- 桌面布置 3 个图标

中途如果 OrbStack 提示需要授权，去 Launchpad 双击启动一次，回来按任意键。

## 第 3 步：手动配 config.toml（5 分钟）

```bash
open -a TextEdit ~/syncswim-dashboard/config.toml
```

改两个字段：
- `camera_url = "http://<Emily 手机的 IP>:4747/video"`（DroidCam）
- `imu_nodes = ["NODE_A1", "NODE_A2"]` 改成她那两块 M5 实际广播的名字

## 第 4 步：CVAT 配置（10 分钟）

1. 双击桌面 `2-start-cvat.command`，等 ~30 秒
2. 浏览器自动开 http://localhost:8080
3. 终端跑（密码记到 `密码模板.txt`）：
   ```bash
   docker exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser'
   ```
4. 用 emily / 你设的密码登录
5. **+ Create new project** → name=`syncswim-detector-phase-a` → label=`person` (Rectangle)
6. **+ Create new task** → name=`phase-a-150-frames` → 拖入 `frames/phase_a_frames_150.zip` 解压后的所有 jpg
7. 等 task 状态变 `Annotation`

## 第 5 步：测 Dashboard（5 分钟）

确保 Emily 手机 DroidCam 开着 + M5 节点开机：
1. 双击桌面 `3-start-dashboard.command`
2. 浏览器自动开 http://localhost:8000
3. 看实时画面 + BLE 是否连上

## 第 6 步：陪标 5 帧示范（10 分钟）

跟 `cheatsheet.html` 一起做：
- 进 task → Job #1
- 左侧选矩形 ▢ → N → Shape + By 2 Points → 拖框（**包水下身影**）
- F 跳下一帧
- 第 5 帧 → Menu → Export task dataset → YOLO 1.1 → 不勾 Save images
- 微信发给自己 → 验证格式

## 你回家之后，Emily 每天的操作

| 想干啥 | 双击 |
|---|---|
| 拉最新规则 / 修补 | `1-update.command` |
| 标注 | `2-start-cvat.command` |
| 训练 / 现场录制 | `3-start-dashboard.command` |
| 看标注规则 | `cheatsheet.html`（浏览器自动开） |

她标完 → 微信发 zip 给你。

## 现场常见问题

| 现象 | 处理 |
|---|---|
| OrbStack 启动慢 / 卡 | Launchpad 找它双击一次（首次需要授权弹窗） |
| `docker compose pull` 慢 | 国内常见，等 5-10 分钟；超时就重跑 |
| `createsuperuser` 报 Postgres 没起 | 等 30 秒重试 |
| Dashboard 黑屏 | 检查 DroidCam 手机 IP / 防火墙 / 同 WiFi |
| BLE 不连 | M5 重启一下；config.toml 节点名核对 |
| `git pull` 问密码 | Keychain 没存好；重跑 setup-system.command 第 3 步 |

## 这套系统的边界

- **训练 / 评估在 Tim 老师机器跑**（M2 GPU，Emily 笔记本不够）
- Emily 这边只做：标注 + dogfood 测试（dashboard 实时看模型效果）
- 训完的 `best.pt` 通过 git pull 自动同步给 Emily（在 .gitignore 里？需要 Tim 老师另外发）

## 完整文档

`docs/phase-a-annotation.md` + `docs/emily-annotation-onboarding.md`
（仓库 git pull 后在 `~/syncswim-dashboard/docs/` 下）
EOF

# ────────── 3. 整体打 zip ──────────
ZIP_OUT="$KIT_DIR.zip"
rm -f "$ZIP_OUT"
zip -qr "$ZIP_OUT" "$KIT_DIR"
SIZE=$(du -h "$ZIP_OUT" | cut -f1)

cat <<EOF

[done] 输出 $ZIP_OUT  ($SIZE)

包含：
  setup/
    setup-system.command        (Tim 老师双击一次性装全套)
  desktop/
    1-update.command            (拉最新)
    2-start-cvat.command        (Emily 标注)
    3-start-dashboard.command   (Emily 训练 / 录制)
    cheatsheet.html             (一页 A4 速查表)
  models/
    yolov8s-pose.pt             (22MB)
    pose_landmarker_lite.task   (5MB)
  videos/
    raw_videos.zip              (~11MB, 3 段)
  frames/
    phase_a_frames_150.zip      ($FRAME_COUNT 帧, ~20MB)
  README.md                     (你的现场装机清单)
  密码模板.txt                   (现场填)

下一步：
  1. AirDrop / 微信发 $ZIP_OUT 到 Emily 电脑
  2. 在她电脑上解压到桌面
  3. 双击 setup/setup-system.command 装机
  4. 按 README.md 第 3-6 步手动配置
EOF
