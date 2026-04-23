# 数据备份

> `data/` 是单点 — 一旦磁盘挂了所有训练录像、IMU 数据、运动员绑定全没了。备份脚本 5 分钟设置完，cron 跑起来就忘掉它。

## 快速开始（最少摩擦）

### 方案 A：外置硬盘（最简单）

```bash
# 1. 插好外置盘，假设挂载在 /Volumes/External
# 2. 写一行配置（一次）
echo "/Volumes/External/syncswim/" > data/.backup_target

# 3. 测一下
python tools/backup.py --dry-run

# 4. 上 cron — 每 15 分钟跑一次
crontab -e
# 加这一行：
*/15 * * * * /usr/bin/python3 /path/to/test_rec/tools/backup.py
```

### 方案 B：rclone 云同步（iCloud / S3 / Google Drive）

```bash
# 1. 装 rclone（macOS：brew install rclone）+ 配置
rclone config           # 跟着提示选 iCloud/S3/gdrive
rclone listremotes      # 确认，比如显示 "icloud:"

# 2. 写配置
echo "icloud:syncswim/" > data/.backup_target

# 3. 测
python tools/backup.py --dry-run
python tools/backup.py    # 真跑一次

# 4. 上 cron（同方案 A）
```

### 方案 C：rsync 到 NAS / 远程服务器

```bash
# 配置 SSH 免密登录（避免 cron 提示输密码）
ssh-copy-id user@nas.local

echo "user@nas.local:/srv/syncswim/" > data/.backup_target
```

## 工作原理

`tools/backup.py` 的核心策略：

| 行为 | 原因 |
|---|---|
| 自动判断 rsync vs rclone | 看 target 形态：`/` 开头或含 `user@host:` 用 rsync，其他用 rclone |
| `rsync --delete-after --partial` | 删除滞后到传输成功后；半截文件留着下次续传 |
| `rclone sync --transfers=4` | 4 路并行；移除目标多出的文件镜像源 |
| **永远 exit 0** | cron 不报错；失败靠 `data/.backup.log` 查 — 飞 wifi 时不刷邮箱 |
| 排除 `.backup.log` 和 `.backup_target` | 备份不传备份本身的 metadata |

## 监控

```bash
tail -f data/.backup.log
```

期望看到的样子：

```
[2026-04-23T14:30:01] [ok] rsync → /Volumes/External/syncswim/
[2026-04-23T14:45:01] [ok] rsync → /Volumes/External/syncswim/
[2026-04-23T15:00:01] [fail] rsync rc=23: ...some files vanished before...
```

`rc=23` 是 rsync 的"部分文件传输失败"，常见原因：录制中文件被改写。下一次 cron 会自动追上，不用慌。

## 常见坑

| 现象 | 原因 | 修复 |
|---|---|---|
| cron 没跑 | macOS 全盘磁盘访问 | 系统设置 → 隐私 → 完全磁盘访问 → 加 `/usr/sbin/cron` |
| rclone 提示 token 过期 | 云端 OAuth 过期 | `rclone config reconnect <remote>:` |
| rsync 报 SSH 密码 | 没免密 | `ssh-copy-id user@host` |
| 备份文件夹比 data/ 小一截 | rclone 删除了源没有的文件 | 正常 — sync 是镜像而非追加 |

## 不在备份范围

`.gitignore` + 备份脚本一致地排除：

- `__pycache__/`、`*.pyc` — 派生物
- `.backup.log`、`.backup_target` — 备份自身的 metadata
- `runs/`、`data/training/images/`、`data/training/labels/` — 微调中间产物（重生成成本低）

**真正要备的**：`data/set_*/`（训练数据）+ `data/athletes.json`（运动员绑定）。这两类丢了不可恢复。
