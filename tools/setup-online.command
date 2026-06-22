#!/bin/bash
# setup-online.command — 把 dashboard 变成「开机自启黑盒 + 在线隧道」
#
# 谁来跑：Tim 老师，在 Emily 的 Mac 上跑一次（双击）。
# 跑完之后：
#   · Emily 的 Mac 插电开机就自动在后台跑 dashboard（不用开终端、不碰命令行）
#   · 通过 Tailscale Funnel 暴露成一个固定 https 网址
#   · 蓝牙(M5)/摄像头/YOLO 全在这台 Mac 上（绕开 iPad 不支持 Web Bluetooth）
#   · 最后打印 Emily 用的「一键配置链接」——她在 iPad 点一次即可，之后用裸网址
#
# 设计目标：幂等（可重复跑）、容错、说人话。出问题截图微信 Tim 老师。

set -uo pipefail

# 让窗口保持开着，能看清输出
trap 'echo ""; echo "============================================"; echo "  按任意键关闭窗口…"; echo "============================================"; read -n 1 -s' EXIT

clear
cat <<'BANNER'
============================================
   SyncSwim 上线安装（开机自启 + 在线隧道）
============================================
BANNER
echo ""

REPO="$HOME/syncswim-dashboard"
PORT=8000
LABEL="com.syncswim.dashboard"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG="/tmp/syncswim-dashboard.log"
TOKEN_FILE="$REPO/.syncswim_token"
UID_NUM="$(id -u)"

# 找 brew 路径（Apple Silicon 在 /opt/homebrew，Intel 在 /usr/local）
if [ -x /opt/homebrew/bin/brew ]; then BREW_BIN=/opt/homebrew/bin; else BREW_BIN=/usr/local/bin; fi
export PATH="$BREW_BIN:$PATH"

# ────────── [1/6] 仓库 / venv / 模型 ──────────
echo "[1/6] 检查仓库 + 依赖…"
if [ ! -d "$REPO/.venv" ]; then
    echo ""
    echo "❌ 没找到 $REPO/.venv"
    echo "   请先跑 setup-system.command 装好系统,再跑这个。"
    exit 1
fi
if [ ! -f "$REPO/yolov8s-pose.pt" ]; then
    echo "❌ 缺模型 yolov8s-pose.pt — 微信 Tim 老师补一下。"
    exit 1
fi
echo "    ✓ 仓库 + venv + 模型 都在"

# ────────── [2/6] Tailscale ──────────
echo "[2/6] 检查 Tailscale…"
if ! command -v tailscale &>/dev/null && [ ! -x "$BREW_BIN/tailscale" ]; then
    echo "    没装 Tailscale,正在用 brew 安装(需要几分钟)…"
    if ! command -v brew &>/dev/null; then
        echo "❌ 没装 Homebrew,无法自动装 Tailscale。"
        echo "   请先装 Homebrew(brew.sh)或手动装 Tailscale 后重跑。"
        exit 1
    fi
    brew install tailscale || { echo "❌ Tailscale 安装失败,截图微信 Tim。"; exit 1; }
    # brew 版需要起后台服务
    sudo "$BREW_BIN/tailscaled" install-system-daemon 2>/dev/null || true
fi
TS="$(command -v tailscale || echo "$BREW_BIN/tailscale")"
echo "    ✓ Tailscale: $TS"

# 确认已登录 tailnet
if ! "$TS" status &>/dev/null; then
    echo ""
    echo "    需要登录 Tailscale(会打开浏览器,用 Frontier 的 Tailscale 账号登录)…"
    "$TS" up || { echo "❌ Tailscale 登录未完成,登录后重跑本脚本。"; exit 1; }
fi
echo "    ✓ 已登录 tailnet"

# ────────── [3/6] 生成 / 复用 token ──────────
echo "[3/6] 准备访问 token…"
if [ -f "$TOKEN_FILE" ]; then
    TOKEN="$(cat "$TOKEN_FILE")"
    echo "    ✓ 复用已有 token"
else
    TOKEN="$(openssl rand -hex 16)"
    printf '%s' "$TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    echo "    ✓ 生成新 token(存 $TOKEN_FILE)"
fi

# 可选：Vercel 前端域名(用于 CORS 白名单 + 生成配置链接)。留空则 CORS 放开(靠 token 防护)。
echo ""
read -r -p "    Vercel 前端域名(如 https://syncswim.vercel.app,没有就直接回车): " VERCEL_URL
VERCEL_URL="${VERCEL_URL%/}"
if [ -n "$VERCEL_URL" ]; then ALLOW="$VERCEL_URL"; else ALLOW="*"; fi

# ────────── [4/6] 写 LaunchAgent(开机自启 + 防休眠) ──────────
echo "[4/6] 安装开机自启黑盒…"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-dis</string>
    <string>${REPO}/.venv/bin/uvicorn</string>
    <string>fastapi_app.main:app</string>
    <string>--host</string><string>0.0.0.0</string>
    <string>--port</string><string>${PORT}</string>
    <string>--workers</string><string>1</string>
  </array>
  <key>WorkingDirectory</key><string>${REPO}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SYNCSWIM_TOKEN</key><string>${TOKEN}</string>
    <key>SYNCSWIM_ALLOW_ORIGINS</key><string>${ALLOW}</string>
    <key>PATH</key><string>${BREW_BIN}:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${LOG}</string>
  <key>StandardErrorPath</key><string>${LOG}</string>
</dict>
</plist>
EOF

# 重新加载(幂等)：先 bootout 旧的，再 bootstrap 新的
launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
if launchctl bootstrap "gui/${UID_NUM}" "$PLIST" 2>/dev/null; then
    launchctl enable "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
else
    # 老系统回退
    launchctl load -w "$PLIST" 2>/dev/null || true
fi
echo "    ✓ 已装 LaunchAgent($PLIST),开机自动跑、崩溃自动重启、caffeinate 防休眠"

# 等后端起来
echo "    等后端就绪(最多 40 秒)…"
READY=0
for i in $(seq 1 20); do
    sleep 2
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${PORT}/api/health" 2>/dev/null || echo 000)"
    if [ "$code" = "200" ]; then READY=1; break; fi
done
if [ "$READY" = "1" ]; then
    echo "    ✓ 后端已在跑(HTTP 200)"
else
    echo "    ⚠ 后端还没就绪,看日志: tail -50 $LOG"
fi

# ────────── [5/6] Tailscale Funnel(固定 https 隧道) ──────────
echo "[5/6] 开启在线隧道(Tailscale Funnel)…"
if "$TS" funnel --bg "${PORT}" 2>/tmp/syncswim-funnel.err; then
    echo "    ✓ Funnel 已开(后台持久,重启自动恢复)"
else
    echo "    ⚠ Funnel 开启失败,通常是 tailnet 还没启用 HTTPS/Funnel 权限。"
    echo "      Tim 去 Tailscale 后台(login.tailscale.com)→ DNS 启用 HTTPS Certificates;"
    echo "      → Access Controls 给本机加 nodeAttr \"funnel\";然后重跑本脚本。"
    echo "      错误详情: $(cat /tmp/syncswim-funnel.err 2>/dev/null)"
fi

# 拿本机 Funnel 域名
DNSNAME="$("$TS" status --json 2>/dev/null | "$REPO/.venv/bin/python" -c 'import sys,json; d=json.load(sys.stdin); print(d.get("Self",{}).get("DNSName","").rstrip("."))' 2>/dev/null || true)"
if [ -n "$DNSNAME" ]; then BACKEND="https://${DNSNAME}"; else BACKEND="https://<你的-mac>.<tailnet>.ts.net"; fi

# ────────── [6/6] 输出 Emily 的配置 ──────────
echo "[6/6] 完成 ✅"
echo ""
cat <<RESULT
============================================
   上线信息(请妥善保存)
============================================

  后端隧道地址 : ${BACKEND}
  访问 token   : ${TOKEN}

  —— 给 Emily 的「一键配置链接」(iPad 点一次即可) ——
RESULT
if [ -n "$VERCEL_URL" ]; then
    echo ""
    echo "  ${VERCEL_URL}/?backend=${BACKEND}&token=${TOKEN}"
    echo ""
    echo "  Emily 在 iPad 用浏览器打开上面这条链接 → 自动记住后端 →"
    echo "  以后直接开 ${VERCEL_URL} 就能用。"
else
    echo ""
    echo "  (还没填 Vercel 域名)部署好 Vercel 前端后,把链接拼成:"
    echo "  https://<你的vercel域名>/?backend=${BACKEND}&token=${TOKEN}"
fi
cat <<'TIPS'

  ⚠ 重要提醒：
   · 现场让 Mac 一直插电。合上盖子默认会休眠 → 后端掉线。
     要合盖也跑：外接电源 + 终端跑一次 sudo pmset -c disablesleep 1
   · 首次后台运行,系统可能弹「蓝牙/相机」权限 → 必须点允许,否则 M5/摄像头连不上。
   · 手机 DroidCam 的局域网 IP 换了,要在 dashboard 设置页改摄像头 URL。
   · 看后端日志：tail -50 /tmp/syncswim-dashboard.log

============================================
TIPS
