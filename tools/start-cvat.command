#!/bin/bash
# start-cvat.command — Emily 双击就能启动 CVAT 的脚本
#
# 使用方法（Emily 视角）：
#   1. 把这个文件放桌面
#   2. 双击 → 黑窗口闪一下 → 浏览器自动开 CVAT
#   3. 用账号密码登录开始标注
#
# 如果出错，**直接微信总统大人**，不要自己折腾。
#
# 设计目标（总统大人参考）：
#   - 零交互：不让 Emily 输任何命令
#   - 自愈：Docker 没跑会自动开
#   - 友好：错误信息说人话 + 留时间让她看清楚
#   - 安全：只做"开 / 等 / 弹浏览器"，绝不删任何东西

set -e

# 让窗口保持开着，Emily 能看到错误信息
# 关 Terminal 窗口要她按 Cmd+Q
trap 'echo ""; echo "============================================"; echo "  按任意键关闭窗口..."; echo "============================================"; read -n 1 -s' EXIT

# ────────── 横幅 ──────────
clear
cat <<'BANNER'
============================================
   花泳标注工作台 — CVAT 启动中
============================================
BANNER
echo ""
echo "请等待 ~30 秒 — 第一次启动可能要 1 分钟"
echo ""

# ────────── Docker 检查 ──────────
echo "[1/4] 检查 Docker..."
if ! command -v docker &>/dev/null; then
    cat <<'ERR'

❌ 没找到 Docker

请微信总统大人，他需要先帮你装 Docker。
ERR
    exit 1
fi

# Docker 装了但没跑？尝试用 osascript 启动 Docker Desktop
if ! docker info &>/dev/null; then
    echo "    Docker 没在跑，正在启动..."
    osascript -e 'tell application "Docker" to activate' 2>/dev/null \
      || open -a "OrbStack" 2>/dev/null \
      || open -a "Docker" 2>/dev/null \
      || true

    # 等 Docker 起来（最多 60s）
    for i in {1..30}; do
        sleep 2
        if docker info &>/dev/null; then
            echo "    ✓ Docker 就绪"
            break
        fi
        if [ $i -eq 30 ]; then
            cat <<'ERR'

❌ Docker 启动超时

请检查屏幕右上是否有 Docker 🐳 或 OrbStack 图标，
然后微信总统大人。
ERR
            exit 1
        fi
    done
else
    echo "    ✓ Docker 已在跑"
fi

# ────────── CVAT 目录检查 ──────────
echo "[2/4] 检查 CVAT 安装..."
CVAT_DIR="$HOME/cvat"
if [ ! -d "$CVAT_DIR" ] || [ ! -f "$CVAT_DIR/docker-compose.yml" ]; then
    cat <<'ERR'

❌ CVAT 没装好

请微信总统大人，他需要现场帮你装一次。
ERR
    exit 1
fi
echo "    ✓ 找到 $CVAT_DIR"

# ────────── 启动容器 ──────────
echo "[3/4] 启动 CVAT 服务..."
cd "$CVAT_DIR"
export CVAT_HOST=localhost
if ! docker compose up -d 2>&1 | tail -3; then
    cat <<'ERR'

❌ CVAT 容器启动失败

请截图终端窗口的红色错误，微信发给总统大人。
ERR
    exit 1
fi

# ────────── 等 HTTP 200 ──────────
echo "[4/4] 等 CVAT 后端准备好（最多 90 秒）..."
for i in {1..45}; do
    sleep 2
    code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080 2>/dev/null || echo "000")
    if [ "$code" = "200" ]; then
        echo "    ✓ CVAT 已就绪（HTTP 200）"
        break
    fi
    printf "    等待中... %d 秒已过\r" $((i*2))
    if [ $i -eq 45 ]; then
        cat <<'ERR'


⚠ CVAT 后端启动慢，但已经在跑

浏览器开了之后如果显示 "502 Bad Gateway"，
等 1 分钟后按 Cmd+R 刷新即可。
ERR
        break
    fi
done

# ────────── 弹浏览器 ──────────
echo ""
echo "正在打开浏览器..."
sleep 1
open http://localhost:8080

cat <<'DONE'

============================================
   ✅ CVAT 已启动
============================================

  浏览器应该已经自动打开。
  用你的账号密码登录就可以开始标注。

  标注规则速查：双击桌面的 cheatsheet.html
  标完导出 zip 后微信发给总统大人。

DONE
