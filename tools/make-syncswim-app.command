#!/bin/bash
# make-syncswim-app.command — 生成 SyncSwim.app(前台 GUI 模式,双击启动后端)
#
# 为什么改成前台 AppleScript app(不再是 LSUIElement 后台 agent):
#   macOS Sequoia 的「本地网络」授权弹窗,只对【前台 GUI app】弹出;
#   LSUIElement 后台 agent 既不弹窗、也不会出现在「本地网络」列表里,
#   于是后端连不上同 WiFi 的手机摄像头(no route to host)。
#   AppleScript app 是正常 GUI app(applet 会正常 CheckIn 窗口服务、不会"无响应"),
#   且用全新 bundle id,让 macOS 当作没见过的新 app、首次运行就依次弹
#   蓝牙 + 本地网络两个授权。本地网络权限不归 TCC 管,只能靠这条路触发。
#
# 谁跑:Tim 一次性在 Emily Mac 双击本文件。跑完桌面出现 SyncSwim.app。

set -e
REPO="$HOME/syncswim-dashboard"
APP="$HOME/Desktop/SyncSwim.app"
SRC="$(mktemp -t syncswim).applescript"

echo "=== 环境自检 ==="
echo "macOS: $(sw_vers -productVersion)  ($(uname -m))"
if [ ! -x "$REPO/.venv/bin/uvicorn" ]; then
    echo "❌ 没找到 $REPO/.venv/bin/uvicorn — 请先装好 venv 再跑本脚本。"
    exit 1
fi
echo "✓ venv 在"

echo "=== 写 AppleScript 源 ==="
# 同步持有 caffeinate+uvicorn:让后端的"责任进程"始终是本 GUI app,
# 蓝牙/本地网络授权才会归到 SyncSwim(用 & 后台会让子进程脱离、责任丢失)。
cat > "$SRC" <<'APPLESCRIPT'
set repoPath to (POSIX path of (path to home folder)) & "syncswim-dashboard"
set uvicornBin to repoPath & "/.venv/bin/uvicorn"
do shell script "cd " & quoted form of repoPath & " && exec /usr/bin/caffeinate -dis " & quoted form of uvicornBin & " fastapi_app.main:app --host 0.0.0.0 --port 8000 >> /tmp/syncswim.log 2>&1"
APPLESCRIPT

echo "=== osacompile 生成 $APP ==="
rm -rf "$APP"
/usr/bin/osacompile -o "$APP" "$SRC"
rm -f "$SRC"

echo "=== 注入身份 + 权限声明(PlistBuddy) ==="
PLIST="$APP/Contents/Info.plist"
PB=/usr/libexec/PlistBuddy
# 全新 bundle id — 让 macOS 当作没见过的新 app,首次运行就弹本地网络窗
"$PB" -c "Set :CFBundleIdentifier com.frontier.syncswim.studio" "$PLIST"
"$PB" -c "Add :CFBundleName string SyncSwim" "$PLIST" 2>/dev/null || "$PB" -c "Set :CFBundleName SyncSwim" "$PLIST"
"$PB" -c "Add :CFBundleDisplayName string SyncSwim" "$PLIST" 2>/dev/null || true
"$PB" -c "Add :NSBluetoothAlwaysUsageDescription string SyncSwim 需要蓝牙来连接 M5 运动传感器、读取 IMU 数据。" "$PLIST" 2>/dev/null || true
"$PB" -c "Add :NSLocalNetworkUsageDescription string SyncSwim 需要访问本地网络,以连接同一 WiFi 下的手机摄像头(DroidCam 视频流)。" "$PLIST" 2>/dev/null || true

echo "=== ad-hoc 签名 ==="
codesign --force --deep --sign - "$APP" 2>/dev/null && echo "✓ 已 ad-hoc 签名" || echo "(codesign 跳过)"

echo ""
echo "============================================"
echo "  ✅ 桌面已生成 SyncSwim.app (前台 GUI 版)"
echo "============================================"
echo "  双击桌面 SyncSwim.app,首次会【依次弹两个授权窗】:"
echo "  · 「SyncSwim 想使用蓝牙」      → 点【允许】"
echo "  · 「SyncSwim 想访问本地网络」  → 点【允许】(连手机摄像头要它!)"
echo "  Dock 出现 SyncSwim 图标 = 后端运行中(退出图标即停后端)。"
echo "  · 若 Dock 图标像转圈/未响应,别管它 — 后端照常在跑,"
echo "    以浏览器 http://localhost:8000 有没有画面为准。"
echo "  日志在 /tmp/syncswim.log"
echo "============================================"
