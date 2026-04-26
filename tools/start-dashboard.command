#!/bin/bash
# start-dashboard.command — Emily 训练现场双击启动 dashboard
#
# 使用方法（Emily 视角）：
#   1. M5 节点开机 + DroidCam 在手机开好
#   2. 双击桌面这个图标
#   3. 浏览器自动打开 dashboard，看实时画面 + 录制
#   4. 训练完关浏览器 + 关本终端窗口（dashboard 自动停）
#
# 出问题立刻微信 Tim 老师，不要自己折腾。

set -e

# 让窗口保持开着 (uvicorn 退出后)，Emily 能看到错误信息
trap 'echo ""; echo "============================================"; echo "  Dashboard 已停止 — 按任意键关闭窗口..."; echo "============================================"; read -n 1 -s' EXIT

clear
cat <<'BANNER'
============================================
   花泳训练 Dashboard 启动中
============================================
BANNER
echo ""

REPO="$HOME/syncswim-dashboard"

# ────────── 仓库检查 ──────────
echo "[1/3] 检查仓库 + 依赖..."
if [ ! -d "$REPO/.venv" ]; then
    cat <<'ERR'

❌ 没找到 syncswim-dashboard 或 venv

请微信 Tim 老师，他需要先帮你装系统（setup-system.command）。
ERR
    exit 1
fi
if [ ! -f "$REPO/yolov8s-pose.pt" ]; then
    cat <<'ERR'

❌ 缺模型文件 yolov8s-pose.pt

请微信 Tim 老师补一下。
ERR
    exit 1
fi
echo "    ✓ 仓库 + venv + 模型 都在"

# ────────── 启动 uvicorn ──────────
echo "[2/3] 启动后端..."
cd "$REPO"
.venv/bin/uvicorn fastapi_app.main:app --host 0.0.0.0 --port 8000 \
    > /tmp/syncswim-dashboard.log 2>&1 &
PID=$!

# 等后端 200
echo "[3/3] 等后端就绪（最多 30 秒）..."
for i in {1..15}; do
    sleep 2
    if ! kill -0 "$PID" 2>/dev/null; then
        cat <<ERR

❌ 后端启动失败，最后日志：

$(tail -20 /tmp/syncswim-dashboard.log)

请截屏发 Tim 老师。
ERR
        exit 1
    fi
    code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000 2>/dev/null || echo "000")
    if [ "$code" = "200" ]; then
        echo "    ✓ 后端就绪（HTTP 200）"
        break
    fi
done

# ────────── 弹浏览器 ──────────
echo ""
echo "正在打开浏览器..."
sleep 1
open http://localhost:8000

cat <<'DONE'

============================================
   ✅ Dashboard 已启动
============================================

  浏览器应该已经自动打开。
  关闭这个终端窗口 = 关闭 dashboard。
  训练完 Cmd+Q 即可。

  日志: /tmp/syncswim-dashboard.log

DONE

# 阻塞直到 uvicorn 死（关终端 / Ctrl+C）
wait $PID
