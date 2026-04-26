#!/bin/bash
# update.command — Emily 双击拉最新代码 + 桌面文件
#
# 什么时候跑：
#   - Tim 老师在群里说"更新一下"
#   - 标注规则有改动
#   - 加了新功能
#
# 不会破坏任何数据 / 模型 / 标注 — 只更新代码 + 桌面图标 + cheatsheet。

set -e
trap 'echo ""; echo "按任意键关闭窗口..."; read -n 1 -s' EXIT

clear
cat <<'BANNER'
============================================
   更新 syncswim-dashboard
============================================
BANNER
echo ""

REPO="$HOME/syncswim-dashboard"
DESK="$HOME/Desktop"

# ────────── 1: git pull ──────────
echo "[1/3] 拉最新代码..."
if [ ! -d "$REPO/.git" ]; then
    cat <<'ERR'

❌ 仓库不存在

请微信 Tim 老师，可能需要重新装。
ERR
    exit 1
fi
cd "$REPO"
git pull origin main 2>&1 | tail -5

# ────────── 2: 刷新桌面图标 ──────────
echo ""
echo "[2/3] 刷新桌面图标..."
cp tools/update.command          "$DESK/1-update.command"
cp tools/start-cvat.command      "$DESK/2-start-cvat.command"
cp tools/start-dashboard.command "$DESK/3-start-dashboard.command"
cp docs/emily-cheatsheet.html    "$DESK/cheatsheet.html"
chmod +x "$DESK/"*.command
echo "    ✓ 已刷新 3 图标 + cheatsheet"

# ────────── 3: pip install (如果 requirements 改了) ──────────
echo ""
echo "[3/3] 检查 Python 依赖..."
if [ -f requirements.txt ] && [ -d .venv ]; then
    .venv/bin/pip install -q -r requirements.txt 2>&1 | tail -3 || true
    echo "    ✓ 依赖已同步"
fi

cat <<'DONE'

============================================
   ✅ 更新完成
============================================

  代码 / 规则 / 桌面图标 都是最新的。
  继续标注或训练即可。

DONE
