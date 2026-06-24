#!/bin/bash
# make-syncswim-app.command — 生成 SyncSwim.app(双击启动后端,含蓝牙权限)
#
# 谁跑:Tim 一次性,在 Emily Mac 上双击本文件(或终端跑)。
# 跑完:桌面出现 SyncSwim.app。从此 Emily 只需双击它 → 后端启动,零终端零代码。
#
# 为什么要 .app:命令行 python 没有蓝牙用途声明,macOS 一碰蓝牙就直接 crash(SIGABRT)、
# 连授权弹窗都不给。.app 的 Info.plist 带 NSBluetoothAlwaysUsageDescription,
# macOS 才会正常弹「想使用蓝牙」让用户允许 → bleak 才能连 M5。
#
# ad-hoc 签名让 macOS 稳定记住这次授权(无签名 app 的授权容易每次失效)。

set -e
REPO="$HOME/syncswim-dashboard"
APP="$HOME/Desktop/SyncSwim.app"

echo "=== 环境自检 ==="
echo "macOS: $(sw_vers -productVersion)  ($(uname -m))"
if [ ! -x "$REPO/.venv/bin/uvicorn" ]; then
    echo "❌ 没找到 $REPO/.venv/bin/uvicorn — 请先装好 venv 再跑本脚本。"
    exit 1
fi
echo "✓ venv 在"

echo "=== 生成 $APP ==="
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

# Info.plist —— 蓝牙用途声明是解 SIGABRT 的关键
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>SyncSwim</string>
  <key>CFBundleDisplayName</key><string>SyncSwim 后端</string>
  <key>CFBundleIdentifier</key><string>com.frontier.syncswim</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>NSBluetoothAlwaysUsageDescription</key><string>SyncSwim 需要蓝牙来连接 M5 运动传感器、读取 IMU 数据。</string>
  <key>LSUIElement</key><true/>
  <key>LSBackgroundOnly</key><false/>
</dict>
</plist>
PLIST

# launcher —— .app 的主程序:防睡(caffeinate 绑本进程) + 启动 uvicorn
# 用 exec 让 uvicorn 成为 .app 的主进程,这样蓝牙请求的"责任进程"是本 .app、
# macOS 据此读上面的 Info.plist 声明。
cat > "$APP/Contents/MacOS/launcher" <<LAUNCH
#!/bin/bash
cd "$REPO"
/usr/bin/caffeinate -dis -w \$\$ &
exec "$REPO/.venv/bin/uvicorn" fastapi_app.main:app --host 0.0.0.0 --port 8000 >> /tmp/syncswim.log 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/launcher"

# ad-hoc 签名(稳定 identity,让 TCC 记住授权)
codesign --force --deep --sign - "$APP" 2>/dev/null && echo "✓ 已 ad-hoc 签名" || echo "(codesign 跳过,不影响首次测试)"

echo ""
echo "============================================"
echo "  ✅ 桌面已生成 SyncSwim.app"
echo "============================================"
echo "  现在双击桌面的 SyncSwim.app:"
echo "  · 首次会弹「SyncSwim 想使用蓝牙」→ 点【允许】"
echo "  · 之后后端就在后台跑了(日志在 /tmp/syncswim.log)"
echo "  · 浏览器开 http://localhost:8000 验证"
echo ""
echo "  停止后端:活动监视器搜 uvicorn 退出,或重启 Mac。"
echo "============================================"
