#!/bin/bash
# setup-system.command — Tim 老师在 Emily 电脑现场跑的完整装机
#
# v3 革命性改动（PR #15）：
#   - **彻底去除 git / GitHub PAT / Keychain** — Emily 不需要 GitHub 账号
#   - 代码从 kit 里的 code.zip 解压（自包含），不再 git clone
#   - 之后 Tim 微信发新 emily_kit_YYYYMMDD.zip → 双击桌面 1-update.command 自动覆盖
#
# 保留 v2 的核心特性：
#   - **idempotent**：每步检查"已完成？"，重跑安全
#   - **容错**：单步失败不终止整脚本，最后汇总 FAILED[]
#   - **重排序**：无网络步骤先做（解压代码 / 模型 / 视频 / 桌面），网络步骤后做（pip / docker pull）
#
# 用法（Tim 老师现场操作）：
#   1. 把 emily_kit_*.zip 解压到 Emily 桌面
#   2. 进 emily_kit_YYYYMMDD/setup/，双击 setup-system.command
#   3. 等 ~25 分钟（首次拉 CVAT 镜像 ~5GB）
#   4. 之后 Emily 全程只用桌面 3 个图标，不碰任何命令行
#
# 注意：刻意 NOT 用 set -e — 单步失败要让其他步骤继续

trap 'echo ""; echo "============================================"; echo "  按任意键关闭窗口..."; echo "============================================"; read -n 1 -s' EXIT

FAILED=()

# ────────── 横幅 ──────────
clear
cat <<'BANNER'
============================================
   花泳 dashboard 系统装机 — Emily 电脑
============================================
BANNER
echo ""
echo "预计 ~25 分钟（首次拉 CVAT 镜像 ~5GB 是大头）"
echo "中途 pip / docker 失败可以重跑本脚本，已做的步骤会跳过"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
KIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$HOME/syncswim-dashboard"
CVAT_DIR="$HOME/cvat"
DESK="$HOME/Desktop"

echo "kit 目录: $KIT_DIR"
echo "目标仓库: $REPO_DIR"
echo "CVAT 目录: $CVAT_DIR"
echo ""

# ────────── 1/9: Homebrew ──────────
echo "[1/9] 检查 Homebrew..."
if ! command -v brew &>/dev/null; then
    cat <<'ERR'

❌ 没找到 Homebrew

请先在 Emily 电脑装 Homebrew：
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

装完后重新跑本脚本（已完成的步骤会跳过）。
ERR
    exit 1
fi
echo "    ✓ Homebrew: $(brew --prefix)"

# ────────── 2/9: brew 依赖 ──────────
echo ""
echo "[2/9] 检查 / 安装系统依赖..."
# 注意：不再依赖 git（更新走 zip），但 OrbStack 可能用 git 装 cvat 镜像
for pkg in python@3.11; do
    if brew list "$pkg" &>/dev/null; then
        echo "    ✓ $pkg 已装"
    else
        echo "    安装 $pkg..."
        if ! brew install "$pkg"; then
            FAILED+=("brew install $pkg")
            echo "    ⚠ $pkg 安装失败，跳过（可手动 brew install $pkg 后重跑本脚本）"
        fi
    fi
done

if ! command -v docker &>/dev/null; then
    if ! brew list --cask orbstack &>/dev/null; then
        echo "    安装 OrbStack..."
        if brew install --cask orbstack; then
            echo ""
            echo "    ⚠ 请在 Launchpad 找到 OrbStack 双击启动一次（首次需要授权）"
            echo "    然后回来按任意键继续..."
            read -n 1 -s
        else
            FAILED+=("brew install --cask orbstack")
        fi
    fi
fi
echo "    ✓ 依赖检查完毕"

# ────────── 3/9: 解压代码（无网络）──────────
echo ""
echo "[3/9] 解压代码到 $REPO_DIR..."
if [ ! -f "$KIT_DIR/code.zip" ]; then
    FAILED+=("kit/code.zip 不存在")
    echo "    ❌ kit 缺 code.zip — 重新下载完整 kit"
else
    mkdir -p "$REPO_DIR"
    if unzip -oq "$KIT_DIR/code.zip" -d "$REPO_DIR/"; then
        # 标记仓库版本（kit 打包日期）
        date "+%Y-%m-%d %H:%M:%S" > "$REPO_DIR/.kit-version"
        echo "    ✓ 代码解压成功（$(ls "$REPO_DIR" | wc -l | xargs) 项）"
    else
        FAILED+=("unzip code.zip")
    fi
fi

# ────────── 4/9: 拷模型（idempotent，无网络）──────────
echo ""
echo "[4/9] 拷模型..."
if [ -d "$KIT_DIR/models" ] && [ -d "$REPO_DIR" ]; then
    cp -n "$KIT_DIR/models/"*.pt   "$REPO_DIR/" 2>/dev/null || true
    cp -n "$KIT_DIR/models/"*.task "$REPO_DIR/" 2>/dev/null || true
    pt_count=$(ls "$REPO_DIR"/*.pt 2>/dev/null | wc -l | xargs)
    task_count=$(ls "$REPO_DIR"/*.task 2>/dev/null | wc -l | xargs)
    echo "    ✓ 仓库根 .pt × $pt_count, .task × $task_count"
else
    echo "    ⚠ 跳过（kit 缺 models/ 或 repo 还没解压）"
fi

# ────────── 5/9: 解压视频（idempotent，无网络）──────────
echo ""
echo "[5/9] 解压 raw_videos..."
if [ -f "$KIT_DIR/videos/raw_videos.zip" ] && [ -d "$REPO_DIR" ]; then
    mkdir -p "$REPO_DIR/data"
    unzip -oq "$KIT_DIR/videos/raw_videos.zip" -d "$REPO_DIR/data/"
    vid_count=$(ls "$REPO_DIR/data/raw_videos" 2>/dev/null | wc -l | xargs)
    echo "    ✓ raw_videos: $vid_count 段"
else
    echo "    ⚠ 跳过（kit 缺 videos/ 或 repo 还没解压）"
fi

# ────────── 6/9: 桌面图标（idempotent，无网络）──────────
echo ""
echo "[6/9] 布置桌面图标..."
if [ -d "$KIT_DIR/desktop" ]; then
    cp "$KIT_DIR/desktop/"*.command "$DESK/" 2>/dev/null || true
    cp "$KIT_DIR/desktop/cheatsheet.html" "$DESK/" 2>/dev/null || true
    chmod +x "$DESK/"*.command 2>/dev/null || true
    echo "    ✓ 桌面 3 图标 + cheatsheet"
else
    echo "    ⚠ 跳过（kit 缺 desktop/）"
fi

# ────────── 7/9: Python venv（idempotent）──────────
echo ""
echo "[7/9] Python venv..."
if [ ! -d "$REPO_DIR" ]; then
    echo "    ⚠ 跳过（仓库还没解压）"
else
    PY311=""
    if command -v python3.11 &>/dev/null; then
        PY311="$(command -v python3.11)"
    elif [ -x "$(brew --prefix)/opt/python@3.11/bin/python3.11" ]; then
        PY311="$(brew --prefix)/opt/python@3.11/bin/python3.11"
    fi

    if [ -z "$PY311" ]; then
        FAILED+=("python3.11 not found")
        echo "    ❌ 找不到 python3.11，先 brew install python@3.11"
    elif [ -d "$REPO_DIR/.venv" ]; then
        echo "    ✓ venv 已存在"
    else
        cd "$REPO_DIR"
        if "$PY311" -m venv .venv; then
            echo "    ✓ venv 创建成功（$PY311）"
        else
            FAILED+=("venv create")
        fi
    fi
fi

# ────────── 8/9: pip install（容错 — 失败不退出）──────────
echo ""
echo "[8/9] pip install 依赖..."
if [ -d "$REPO_DIR/.venv" ]; then
    cd "$REPO_DIR"
    .venv/bin/pip install --upgrade pip --quiet 2>&1 | tail -3 || true

    # Try requirements.txt first; if it conflicts, fall back to inline
    # minimum set. This makes setup robust to "未来版" pins or ABI
    # mismatches (e.g. numpy 2.x vs mediapipe 0.10.x).
    install_minimum() {
        .venv/bin/pip install \
            "fastapi" "uvicorn[standard]" "aiofiles" "websockets" \
            "pydantic>=2.0" "bleak" \
            "numpy>=1.23,<2" "opencv-python>=4.8.0" \
            "opencv-contrib-python>=4.8.0" "pillow>=10.0" \
            "mediapipe>=0.10.5,<0.11" "ultralytics>=8.3.0" \
            "matplotlib>=3.7" "scipy>=1.10" \
            "pytest>=7.0" "httpx>=0.25"
    }

    if [ -f requirements.txt ]; then
        echo "    使用 requirements.txt..."
        if .venv/bin/pip install -r requirements.txt; then
            echo "    ✓ 依赖装好"
        else
            echo "    ⚠ requirements.txt 解析失败，回退到 minimum set..."
            if install_minimum; then
                echo "    ✓ minimum set 装好（项目所有 import 都满足）"
            else
                FAILED+=("pip install (both requirements.txt + fallback)")
                echo "    ❌ 两路都失败 — 检查网络 / 重跑本脚本"
            fi
        fi
    else
        echo "    requirements.txt 不存在，装 minimum set..."
        if install_minimum; then
            echo "    ✓ minimum set 装好"
        else
            FAILED+=("pip install minimum set")
        fi
    fi
else
    echo "    ⚠ 跳过（venv 还没创建）"
fi

# ────────── 9/9: CVAT（容错）──────────
echo ""
echo "[9/9] 准备 CVAT..."
if command -v docker &>/dev/null; then
    if [ ! -d "$CVAT_DIR/.git" ]; then
        # CVAT 仍然用 git clone（这是从 cvat-ai/cvat 拉，不是我们的 PAT），公开仓库无密码
        if command -v git &>/dev/null; then
            if git clone --depth 1 https://github.com/cvat-ai/cvat "$CVAT_DIR"; then
                echo "    ✓ CVAT clone 成功"
            else
                FAILED+=("git clone cvat")
            fi
        else
            echo "    ⚠ 没有 git，跳过 CVAT clone（手动 brew install git 后重跑本脚本）"
            FAILED+=("git not installed for cvat")
        fi
    else
        echo "    ✓ CVAT 仓库已存在"
    fi

    if [ -d "$CVAT_DIR/.git" ]; then
        cd "$CVAT_DIR"
        export CVAT_HOST=localhost
        echo "    拉 CVAT 镜像（~5GB，5-10 分钟，慢可重跑）..."
        if docker compose pull 2>&1 | tail -5; then
            echo "    ✓ CVAT 镜像就绪"
        else
            FAILED+=("docker compose pull")
            echo "    ⚠ docker pull 部分失败 — 重跑本脚本会续传"
        fi
    fi
else
    echo "    ⚠ docker 不可用，跳过 CVAT（先确保 OrbStack 启动）"
    FAILED+=("docker not available")
fi

# ────────── 总结 ──────────
echo ""
echo "============================================"
if [ ${#FAILED[@]} -eq 0 ]; then
    cat <<'DONE'
   ✅ 装机全部完成
============================================

Emily 桌面应该有：
   1-update.command           ← 拿到 Tim 老师新发的 zip 后双击更新
   2-start-cvat.command       ← 标注用
   3-start-dashboard.command  ← 训练 / 现场录制
   cheatsheet.html            ← 标注速查表

剩余 Tim 老师手动做（~10 分钟）：
   1. 编辑 ~/syncswim-dashboard/config.toml：
      - camera_url = "http://<Emily 手机 IP>:4747/video"
      - imu_nodes = ["NODE_A1", "NODE_A2"] 改成她两块 M5 的名字
   2. CVAT 浏览器配置（如还没做）：参考 README.md §4
   3. 测试：双击 3-start-dashboard.command 看 dashboard 起来

以后 Tim 老师每次更新代码：
   1. 跑 `bash tools/build-emily-kit.sh` 出新 emily_kit_YYYYMMDD.zip
   2. 微信 / AirDrop 给 Emily
   3. Emily 把 zip 放桌面，双击 1-update.command（30 秒搞定）
   4. 不需要 git / GitHub / 命令行
DONE
else
    cat <<DONE
   ⚠ 装机部分完成（${#FAILED[@]} 步失败）
============================================

失败的步骤：
$(printf "  - %s\n" "${FAILED[@]}")

✅ 已完成的步骤无需重做（脚本是 idempotent 的）。

建议：
  1. 检查上面失败的步骤的错误信息
  2. 修好原因（通常是网络）
  3. **重跑本脚本** — 已完成的会跳过，只重做失败的
DONE
fi
echo ""
