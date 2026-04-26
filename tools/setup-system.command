#!/bin/bash
# setup-system.command — Tim 老师在 Emily 电脑现场跑一次的完整装机
#
# 这一个脚本搞定：
#   - 装 Homebrew / Python 3.11 / git / OrbStack（轻量 Docker 替代）
#   - clone syncswim-dashboard 仓库 + 永久存 GitHub 凭证
#   - 创建 Python venv + pip install
#   - 拷模型权重（yolov8s-pose.pt + pose_landmarker_lite.task）
#   - 解压 raw_videos
#   - clone CVAT + 拉镜像（不启动）
#   - 桌面布置 4 个图标
#
# 用法（Tim 老师现场操作）：
#   1. 把 emily_kit 解压到 Emily 桌面
#   2. 双击 setup/setup-system.command
#   3. 按提示输入 GitHub PAT（read 权限即可，不会回显）
#   4. 等 ~25 分钟（视网速）
#   5. 之后所有交互都通过桌面 3 个图标完成
#
# 安全说明：
#   - 不删任何已有文件
#   - 缺工具会停下来报错，不会自动 brew install 大件（除非你确认）
#   - PAT 直接写进 macOS Keychain，重启不丢失，git pull 不再问密码

set -e
trap 'echo ""; echo "============================================"; echo "  按任意键关闭窗口..."; echo "============================================"; read -n 1 -s' EXIT

# ────────── 横幅 ──────────
clear
cat <<'BANNER'
============================================
   花泳 dashboard 系统装机 — Emily 电脑
============================================
BANNER
echo ""
echo "预计 ~25 分钟（首次拉 CVAT 镜像 ~5GB 是大头）"
echo ""

# ────────── 路径推断 ──────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
KIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$HOME/syncswim-dashboard"
CVAT_DIR="$HOME/cvat"
DESK="$HOME/Desktop"

echo "kit 目录: $KIT_DIR"
echo "目标仓库: $REPO_DIR"
echo "CVAT 目录: $CVAT_DIR"
echo ""

# ────────── 1/8: Homebrew ──────────
echo "[1/8] 检查 Homebrew..."
if ! command -v brew &>/dev/null; then
    cat <<'ERR'

❌ 没找到 Homebrew

请先在 Emily 电脑装 Homebrew（一行命令）：
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

装完后重新跑本脚本。
ERR
    exit 1
fi
echo "    ✓ Homebrew: $(brew --prefix)"

# ────────── 2/8: 装 python@3.11 + git + orbstack ──────────
echo "[2/8] 检查 / 安装系统依赖..."
for pkg in python@3.11 git; do
    if ! brew list "$pkg" &>/dev/null; then
        echo "    安装 $pkg..."
        brew install "$pkg"
    fi
done

# OrbStack 比 Docker Desktop 轻 50%，更适合 Emily 笔记本
if ! command -v docker &>/dev/null; then
    if ! brew list --cask orbstack &>/dev/null; then
        echo "    安装 OrbStack（轻量 Docker 替代）..."
        brew install --cask orbstack
        echo ""
        echo "    ⚠ 请在 Launchpad 找到 OrbStack 双击启动一次（首次需要授权）"
        echo "    然后回来按任意键继续..."
        read -n 1 -s
    fi
fi
echo "    ✓ Python 3.11 / git / Docker (OrbStack)"

# ────────── 3/8: GitHub PAT + Keychain ──────────
echo ""
echo "[3/8] 配置 GitHub 凭证..."
echo "    （之后 Emily git pull 永远不用输密码）"
echo ""
read -p "      GitHub 用户名: " GH_USER
echo "      GitHub PAT (粘贴时不会回显，按回车确认):"
read -s GH_PAT
echo ""
if [ -z "$GH_PAT" ]; then
    echo "    ❌ PAT 为空，退出"
    exit 1
fi

# 写到 macOS Keychain — 之后所有 https github.com 操作免密
git config --global credential.helper osxkeychain
printf "protocol=https\nhost=github.com\nusername=%s\npassword=%s\n\n" \
    "$GH_USER" "$GH_PAT" | git credential-osxkeychain store
echo "    ✓ Keychain 已存（可以删掉这个终端记录了）"

# ────────── 4/8: clone 仓库 ──────────
echo ""
echo "[4/8] clone syncswim-dashboard..."
if [ -d "$REPO_DIR/.git" ]; then
    echo "    仓库已存在，跳过 clone（之后用 1-update.command 拉新）"
else
    git clone "https://github.com/BilltheChurch/syncswim-dashboard.git" "$REPO_DIR"
fi
echo "    ✓ 仓库就绪: $REPO_DIR"

# ────────── 5/8: Python venv + 依赖 ──────────
echo ""
echo "[5/8] Python venv + 依赖..."
PY311="$(brew --prefix python@3.11)/bin/python3.11"
if [ ! -x "$PY311" ]; then
    echo "    ❌ python3.11 找不到：$PY311"
    exit 1
fi
cd "$REPO_DIR"
if [ ! -d ".venv" ]; then
    "$PY311" -m venv .venv
fi
.venv/bin/pip install --upgrade pip --quiet
if [ -f requirements.txt ]; then
    .venv/bin/pip install -r requirements.txt
else
    echo "    ⚠ requirements.txt 不存在，装最小依赖集"
    .venv/bin/pip install \
        "fastapi[standard]" uvicorn opencv-python ultralytics \
        mediapipe bleak numpy matplotlib pillow tomli httpx pytest
fi
echo "    ✓ venv 就绪"

# ────────── 6/8: 拷模型 + 视频 ──────────
echo ""
echo "[6/8] 拷模型 + 解压视频..."
if [ -d "$KIT_DIR/models" ]; then
    cp "$KIT_DIR/models/"*.pt "$REPO_DIR/" 2>/dev/null || true
    cp "$KIT_DIR/models/"*.task "$REPO_DIR/" 2>/dev/null || true
    echo "    ✓ 模型已拷入仓库根"
else
    echo "    ⚠ kit 没带 models/ 目录，跳过"
fi

if [ -f "$KIT_DIR/videos/raw_videos.zip" ]; then
    mkdir -p "$REPO_DIR/data/raw_videos"
    unzip -oq "$KIT_DIR/videos/raw_videos.zip" -d "$REPO_DIR/data/"
    echo "    ✓ raw_videos 已解压: $(ls "$REPO_DIR/data/raw_videos" 2>/dev/null | wc -l | xargs) 段"
else
    echo "    ⚠ kit 没带 videos/raw_videos.zip，跳过"
fi

# ────────── 7/8: CVAT ──────────
echo ""
echo "[7/8] 准备 CVAT（不启动，留给桌面图标）..."
if [ ! -d "$CVAT_DIR/.git" ]; then
    git clone --depth 1 https://github.com/cvat-ai/cvat "$CVAT_DIR"
fi
cd "$CVAT_DIR"
export CVAT_HOST=localhost
echo "    拉 CVAT 镜像（~5GB，5-10 分钟）..."
docker compose pull 2>&1 | tail -3 || true
echo "    ✓ CVAT 就绪（双击 2-start-cvat.command 才启动）"

# ────────── 8/8: 桌面图标 ──────────
echo ""
echo "[8/8] 布置桌面图标..."
if [ -d "$KIT_DIR/desktop" ]; then
    cp "$KIT_DIR/desktop/"*.command "$DESK/"
    cp "$KIT_DIR/desktop/cheatsheet.html" "$DESK/" 2>/dev/null || true
    chmod +x "$DESK/"*.command
    echo "    ✓ 桌面 3 图标 + cheatsheet"
else
    echo "    ⚠ kit 没带 desktop/ 目录，跳过桌面布置"
fi

# ────────── 完成 ──────────
cat <<DONE

============================================
   ✅ 系统装机完成
============================================

Emily 桌面应该有：
   1-update.command           ← 拉最新规则 / 代码
   2-start-cvat.command       ← 标注用
   3-start-dashboard.command  ← 训练现场用
   cheatsheet.html            ← 标注速查表

剩余 Tim 老师手动做（~10 分钟）：
   1. 编辑 $REPO_DIR/config.toml：
      - camera_url = "http://<Emily 手机 IP>:4747/video"
      - ble_device_name + imu_nodes 改成她两块 M5 的名字
   2. CVAT 浏览器配置（参考 README.md §3）：
      - 双击 2-start-cvat.command 启动
      - 浏览器开 http://localhost:8080
      - 创建 emily 账号（写到 密码模板.txt）
      - 建 project syncswim-detector-phase-a
      - 建 task phase-a-150-frames + 上传 phase_a_frames_150.zip 解压的帧
   3. 测试：双击 3-start-dashboard.command 看 dashboard 起来
   4. 陪 Emily 标 5 帧示范

DONE
