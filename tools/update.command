#!/bin/bash
# update.command — Emily 双击：自动找桌面最新 emily_kit_*.zip，解压覆盖代码
#
# 流程（Emily 视角）：
#   1. Tim 老师微信 / AirDrop 发来新 emily_kit_YYYYMMDD.zip
#   2. Emily 把它放在桌面（Finder 拖一下就行）
#   3. 双击桌面的 1-update.command
#   4. 30 秒后弹"✅ 更新完成"
#
# 不会动你的：
#   - CVAT 标注数据（在 OrbStack 卷里）
#   - 你已经标好的 labels
#   - 你训练 / 录制的 set
#   - 已下的 docker 镜像
#
# 会替换的：
#   - ~/syncswim-dashboard/ 下的代码（fastapi_app/, tools/, docs/, requirements.txt 等）
#   - 桌面 3 个 .command + cheatsheet.html
#   - 仓库根的模型 .pt / .task（如果新版有更新）

trap 'echo ""; echo "按任意键关闭窗口..."; read -n 1 -s' EXIT

clear
cat <<'BANNER'
============================================
   syncswim-dashboard 更新（v3 — 不用 git）
============================================
BANNER
echo ""

REPO="$HOME/syncswim-dashboard"
DESK="$HOME/Desktop"

# ────────── 1: 找桌面最新 kit zip ──────────
echo "[1/4] 找桌面最新的 emily_kit_*.zip..."
KIT_ZIP=$(ls -t "$DESK/emily_kit_"*.zip 2>/dev/null | head -1)

if [ -z "$KIT_ZIP" ]; then
    cat <<'ERR'

❌ 桌面没找到 emily_kit_*.zip

请先让 Tim 老师发新版 zip 给你：
  - 微信 / AirDrop / 邮件 都行
  - 收到后**直接放在桌面**（不用解压）
  - 然后重新双击本脚本

ERR
    exit 1
fi

KIT_NAME=$(basename "$KIT_ZIP")
KIT_SIZE=$(du -h "$KIT_ZIP" | cut -f1)
echo "    ✓ 找到: $KIT_NAME ($KIT_SIZE)"

# ────────── 2: 解压到临时目录 ──────────
echo ""
echo "[2/4] 解压临时目录..."
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"; echo ""; echo "按任意键关闭窗口..."; read -n 1 -s' EXIT

if ! unzip -q "$KIT_ZIP" -d "$TMP"; then
    echo "    ❌ 解压失败 — zip 可能损坏"
    echo "    让 Tim 老师重发一次"
    exit 1
fi

# kit zip 里第一层目录名（emily_kit_YYYYMMDD/）
KIT_DIR=$(find "$TMP" -maxdepth 1 -type d -name "emily_kit_*" | head -1)
if [ -z "$KIT_DIR" ]; then
    echo "    ❌ zip 结构不对（找不到 emily_kit_*/ 目录）"
    exit 1
fi
echo "    ✓ 解压成功"

# ────────── 3: 覆盖 ~/syncswim-dashboard/ ──────────
echo ""
echo "[3/4] 更新代码..."
if [ ! -d "$REPO" ]; then
    echo "    ❌ $REPO 不存在 — 先双击 setup/setup-system.command 完整装机"
    exit 1
fi

# 先保住这台机器的本地设置：code.zip 会整体覆盖 config.toml（这正是新模型路径
# 生效的方式），所以摄像头地址这类"只属于这台电脑"的设置要搬进 config.local.toml，
# 它不在 kit 里、永远不会被覆盖。只在第一次更新时迁移一次。
if [ -f "$REPO/config.toml" ] && [ ! -f "$REPO/config.local.toml" ]; then
    {
        echo "# 这台电脑的本地设置 — 更新时不会被覆盖（由 1-update.command 自动生成）"
        echo "[hardware]"
        grep -E '^[[:space:]]*(camera_url|camera_rotation)[[:space:]]*=' \
            "$REPO/config.toml" || true
        echo ""
        echo "[analysis]"
        if [ "$(uname -m)" = "x86_64" ]; then
            echo 'device = "cpu"   # Intel Mac 没有 Apple Metal(mps)'
        else
            echo 'device = "mps"   # Apple Silicon'
        fi
    } > "$REPO/config.local.toml"
    echo "    ✓ 本地设置已存入 config.local.toml（以后更新不会覆盖它）"
fi

if [ -f "$KIT_DIR/code.zip" ]; then
    if unzip -oq "$KIT_DIR/code.zip" -d "$REPO/"; then
        date "+%Y-%m-%d %H:%M:%S" > "$REPO/.kit-version"
        echo "    ✓ 代码已更新（kit_version: $(cat "$REPO/.kit-version")）"
    else
        echo "    ❌ 代码解压失败"
        exit 1
    fi
else
    echo "    ⚠ kit 没带 code.zip（旧版 kit 格式？让 Tim 老师重新打）"
fi

# 模型
if [ -d "$KIT_DIR/models" ]; then
    # 基础模型（COCO/MediaPipe 通用权重）放仓库根，不覆盖已存在的 —— 它们不会变，
    # 而且万一这台机器上有训练产物同名，不能动。
    cp -n "$KIT_DIR/models/"*.pt   "$REPO/" 2>/dev/null || true
    cp -n "$KIT_DIR/models/"*.task "$REPO/" 2>/dev/null || true
fi

# 我们自己训的花泳专用权重 → $REPO/models/，**必须覆盖**：每个 kit 带的就是当前
# 上线版本，文件名自带版本号(swimmer_det_v3.pt)，不会误伤任何训练产物。
if [ -d "$KIT_DIR/vision_models" ]; then
    mkdir -p "$REPO/models"
    cp -f "$KIT_DIR/vision_models/"*.pt "$REPO/models/" 2>/dev/null || true
    echo "    ✓ 花泳视觉模型已更新（$(ls -1 "$REPO/models"/*.pt 2>/dev/null | wc -l | tr -d ' ') 个）"
fi

# ────────── 4: 刷新桌面图标 ──────────
echo ""
echo "[4/4] 刷新桌面图标..."
if [ -d "$KIT_DIR/desktop" ]; then
    cp "$KIT_DIR/desktop/"*.command "$DESK/" 2>/dev/null || true
    cp "$KIT_DIR/desktop/cheatsheet.html" "$DESK/" 2>/dev/null || true
    chmod +x "$DESK/"*.command 2>/dev/null || true
    echo "    ✓ 桌面 3 图标 + cheatsheet 已刷新"
fi

# pip sync 依赖（如果 requirements 改了）
if [ -f "$REPO/requirements.txt" ] && [ -d "$REPO/.venv" ]; then
    cd "$REPO"
    echo ""
    echo "    检查 Python 依赖..."
    .venv/bin/pip install -q -r requirements.txt 2>&1 | tail -3 || true
    echo "    ✓ 依赖已同步"
fi

cat <<DONE

============================================
   ✅ 更新完成
============================================

  代码版本: $(cat "$REPO/.kit-version" 2>/dev/null || echo "unknown")
  下次更新: Tim 老师发新 zip → 放桌面 → 双击本脚本

  现在可以双击 3-start-dashboard.command 验证。

DONE
