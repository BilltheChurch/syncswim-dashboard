# SyncSwim 上线部署手册（Vercel 前端 + Mac 黑盒后端）

让 Emily 只带 **M5 + iPad + 手机** 去现场,连 WiFi 就能用——不带开发电脑、不碰命令行。
重活（蓝牙连 M5、摄像头、YOLO 推理）留在 Emily 的 Mac 上跑（绕开 iPad/iOS 不支持
Web Bluetooth 的死结）;前端 UI 托在 Vercel,通过 Tailscale 隧道连回 Mac。

```
  iPad(控制台) / 手机(机位)          训练后复盘也用 iPad / 任意设备
        │ https                              │
        ▼                                    ▼
  ┌──────────────┐   Tailscale Funnel  ┌──────────────────────────┐
  │ Vercel       │ ───(固定 https)────▶ │ Emily 的 Mac = 隐形黑盒     │
  │ 静态前端 UI   │   /api + /ws        │ · LaunchAgent 开机自启      │
  │ (本仓库       │                     │ · caffeinate 防休眠         │
  │  fastapi_app/ │                     │ · bleak 连 M5(蓝牙)         │
  │  static/)     │                     │ · DroidCam 抓手机视频流      │
  └──────────────┘                     │ · YOLO/MediaPipe 推理 + 录制 │
                                        │ · choreography/scoring 算法  │
                                        └──────────────────────────┘
```

前端连后端靠运行时变量 `window.BACKEND_BASE`（见 `index.html` `<head>`）:
- **本地直接连 Mac**（同源）时为空 → 走相对路径,行为和改造前一致。
- **Vercel 上**由「配置链接」把隧道域名 + token 存进 `localStorage`,前端据此连 Mac。

---

## 一次性部署（Tim 老师做）

### A. 前端上 Vercel（✅ 已部署:https://syncswim.vercel.app）
前端是纯静态 3 文件,从 `fastapi_app/static/` 目录部署,配套的 `fastapi_app/static/vercel.json`
做 `/static/*` rewrite（适配 index.html 的绝对路径引用）。**重新部署**只需:
```bash
cd fastapi_app/static
vercel deploy --prod      # 已 link 到 tims-projects-8885c065/syncswim
```
- 项目:`tims-projects-8885c065/syncswim`;固定域名 `https://syncswim.vercel.app`。
- 首次已用 `vercel link --yes --project syncswim` 关联;无框架、无 build、输出目录=当前目录。
- 只上传那 3 个前端文件,不碰 23MB 模型 / data / .venv。

### B. Tailscale tailnet 准备（一次性,在 login.tailscale.com）
1. **DNS → 启用 HTTPS Certificates**。
2. **Access Controls** → 给 Emily 的 Mac 节点加属性 `funnel`（`nodeAttrs` 里 `attr: ["funnel"]`）。
   没这两步 `tailscale funnel` 会报权限错。

### C. Emily 的 Mac 变黑盒（双击 `tools/setup-online.command`）
脚本会:检查仓库 → 装/登录 Tailscale → 生成 token → 装开机自启 LaunchAgent(caffeinate 防休眠)
→ 开 Funnel → 打印**隧道域名 + token + Emily 的一键配置链接**。
- 跑的时候会问 Vercel 域名,填 A 步拿到的。
- 跑完后端就常驻了:开机自动起、崩溃自动重启、不用开终端。

### D. Emily 的 iPad（一次）
1. 浏览器打开脚本输出的**配置链接**:
   `https://<vercel域名>/?backend=https://<mac>.<tailnet>.ts.net&token=<token>`
2. 前端自动把后端地址+token 记进 localStorage,并清掉 URL 参数。
3. 之后直接开 `https://<vercel域名>` 即可,无需再填。
（也可在 dashboard 设置页手动改后端地址/token。）

---

## 现场清单（Emily）
- [ ] Mac 插电、**别合盖**（合盖默认休眠→后端掉线;要合盖跑见下方）。
- [ ] M5 节点开机;手机开 DroidCam,和 Mac 同一个 WiFi。
- [ ] iPad 连同一 WiFi（或任意能上网的网络,Funnel 是公网 https）。
- [ ] 首次后台运行若弹「蓝牙/相机」权限 → **必须点允许**。

## 合盖也要跑
外接电源接着,终端跑一次（需要管理员密码,一次性）:
```bash
sudo pmset -c disablesleep 1     # 插电时禁止休眠(含合盖)
```
不想用时:`sudo pmset -c disablesleep 0`。

## 故障排查
| 症状 | 排查 |
|---|---|
| iPad 白屏 / 连不上 | Mac 后端在跑吗:`tail -50 /tmp/syncswim-dashboard.log`;隧道域名/token 对吗 |
| 实时视频不动 | 手机 DroidCam 的局域网 IP 变了 → dashboard 设置页改摄像头 URL |
| 回放视频无法 seek | Mac 缺 ffmpeg(`brew install ffmpeg`);转码失败日志在上面 |
| `tailscale funnel` 失败 | tailnet 没启用 HTTPS / 没加 `funnel` 属性(见 B 步) |
| 401 unauthorized | token 不对 → 重新点配置链接,或设置页改 token |

## 安全说明
- 后端通过 Funnel 暴露公网,已加 **token 鉴权**（`SYNCSWIM_TOKEN`,query 或 `X-SyncSwim-Token` 头）。
  `/api/health` 豁免（探活用）。本地未设该 env 时全放行（开发兼容）。
- **更安全的替代**:用 `tailscale serve`（非 Funnel）只在 tailnet 内可达,iPad 装 Tailscale 加入
  同一 tailnet——后端不暴露公网,可省 token。代价:iPad 要装 Tailscale 登录一次。

## 关键约定
- 端口 8000;服务名 `com.syncswim.dashboard`;日志 `/tmp/syncswim-dashboard.log`。
- 仓库根 `$HOME/syncswim-dashboard`;venv `$HOME/syncswim-dashboard/.venv`。
- 后端 env:`SYNCSWIM_TOKEN`、`SYNCSWIM_ALLOW_ORIGINS`(CORS 白名单,逗号分隔或 `*`)、
  `SYNCSWIM_DATA_DIR`(默认 项目根/data,绝对路径,自启黑盒不受 cwd 影响)。
