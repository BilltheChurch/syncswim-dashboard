#!/bin/bash
# build-emily-kit.sh — 一行命令打包给 Emily 的工作包
#
# 跑一次会输出 ./emily_kit_YYYYMMDD.zip，包含：
#   ├── README.md                  ← 给总统大人的现场装机清单
#   ├── phase_a_frames_150.zip     ← 待标的 ~150 张帧
#   ├── start-cvat.command         ← 双击启动 CVAT 的脚本
#   ├── cheatsheet.html            ← Emily 的标注速查表（一页 A4 可打印）
#   └── 密码模板.txt                ← 留给总统填 Emily 的 CVAT 密码
#
# 用法：
#   bash tools/build-emily-kit.sh
#   # 然后 AirDrop / 微信文件 把 emily_kit_*.zip 传到 Emily 电脑
#   # 总统按 README.md 现场装机

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
    # 父级 worktree 时回退到主仓库的 venv
    PY="/Users/billthechurch/Downloads/test_rec/.venv/bin/python"
fi
if [ ! -x "$PY" ]; then
    echo "[error] 找不到 venv: 试过 $REPO_ROOT/.venv 和主仓库 .venv"
    exit 1
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
mkdir -p "$KIT_DIR"

# 2a. 帧 zip
echo "[+] 打包 $FRAME_COUNT 张帧..."
(cd "$FRAMES_DIR/.." && zip -qr "$REPO_ROOT/$KIT_DIR/phase_a_frames_150.zip" frames/)

# 2b. 启动脚本（chmod +x 在 git 里已经设好）
cp tools/start-cvat.command "$KIT_DIR/start-cvat.command"
chmod +x "$KIT_DIR/start-cvat.command"

# 2c. 速查表
cp docs/emily-cheatsheet.html "$KIT_DIR/cheatsheet.html"

# 2d. 密码模板
cat > "$KIT_DIR/密码模板.txt" <<'EOF'
Emily 的 CVAT 账号
==================

URL:      http://localhost:8080
用户名:   emily
密码:     ____________________
邮箱:     ____________________

（总统大人在 Emily 电脑现场装机时填这张表，
  填好后让 Emily 第一次登录后让浏览器记住密码，
  此文件之后可删 / 留作备份）
EOF

# 2e. 给总统的现场装机 README
cat > "$KIT_DIR/README.md" <<'EOF'
# 给总统大人 — Emily 电脑装机清单

## 你需要带的
- 这个 `emily_kit_*` 文件夹（已经在 Emily 电脑上）
- ~45 分钟时间

## 现场流程

### 1. 装 Docker（10 min）
浏览器开 https://www.docker.com/products/docker-desktop/ → 下 Mac 版 → 装。
首次启动需 Emily Mac 密码授权。右上角小鲸鱼 🐳 变绿就 OK。

> 笔记本 RAM ≤ 8GB？换装 OrbStack（更轻）：https://orbstack.dev/

### 2. 终端跑一次性命令（10 min）

```bash
# 拉 CVAT
cd ~
git clone --depth 1 https://github.com/cvat-ai/cvat
cd cvat
export CVAT_HOST=localhost
docker compose up -d

# 等所有容器起来后建 Emily 账号
# Username: emily, Email: 她的邮箱, Password: 她记得住的（记到密码模板.txt）
docker exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser'
```

### 3. CVAT 浏览器配置（10 min）

1. 浏览器开 http://localhost:8080，用刚建的账号登录
2. **+ Create new project** → name=`syncswim-detector-phase-a` → label=`person` (Rectangle) → Submit
3. **+ Create new task** → name=`phase-a-150-frames` → 选 `phase_a_frames_150.zip` 解压后的所有 jpg → Submit
4. 等 task 状态变 `Annotation`

### 4. 桌面准备（5 min）

```bash
# 把启动脚本和速查表放 Emily 桌面
cp start-cvat.command ~/Desktop/
cp cheatsheet.html ~/Desktop/
chmod +x ~/Desktop/start-cvat.command
```

浏览器书签栏加 `http://localhost:8080`，命名「**标注工作台**」。

### 5. 示范 5 帧（10 min）

亲手陪她标 5 帧：
- 双击 `start-cvat.command`
- 登录
- 进 task → Job #1
- 左侧点中矩形 ▢ → N → Shape + By 2 Points → 拖框
- 包水下身影
- F 下一帧
- 第 5 帧 → Menu → Export task dataset → YOLO 1.1 → 不勾 Save images → 下载
- 微信发给自己 → 验证格式

### 6. 后续

- 让 Emily 标完 30-50 帧后中途 export 一份发你检查 — **不要等她标完 150 帧才看**
- 整批标完后她导出 → 微信发你
- 出任何问题 → Emily 截屏发你 → **不要让她自己折腾技术故障**

## 常见问题（你可能现场遇到）

| 现象 | 处理 |
|---|---|
| `docker compose up -d` 报端口冲突 | `lsof -i :8080`，关占用进程 |
| Docker Desktop 第一次启动卡 | 重启 Mac 一次 |
| `createsuperuser` 报错 | 等 30 秒（Postgres 还在初始化）再试 |
| 浏览器开了 502 | 等 1-2 分钟再刷新 |

## 你回家之后

完整文档见仓库 `docs/phase-a-annotation.md` + `docs/emily-annotation-onboarding.md`。
EOF

# ────────── 3. 整体打 zip ──────────
ZIP_OUT="$KIT_DIR.zip"
rm -f "$ZIP_OUT"
zip -qr "$ZIP_OUT" "$KIT_DIR"
SIZE=$(du -h "$ZIP_OUT" | cut -f1)

cat <<EOF

[done] 输出 $ZIP_OUT  ($SIZE)

包含：
  - phase_a_frames_150.zip  ($FRAME_COUNT 帧)
  - start-cvat.command      (Emily 双击启动)
  - cheatsheet.html         (一页 A4 速查表)
  - 密码模板.txt             (总统现场填)
  - README.md               (你的装机清单)

下一步：
  1. AirDrop / 微信发 $ZIP_OUT 到 Emily 电脑
  2. 在她电脑上解压
  3. 按 README.md 现场装机
EOF
