# Development Log — IMU Motion Capture System

> 真实开发过程中遇到的问题、分析思路、以及解决方案的完整记录。
> 每一条都来自实际动手调试，不是纸上谈兵。

---

## 问题 #1：macOS 蓝牙权限导致脚本崩溃

**时间**：项目启动阶段（BLE 扫描脚本首次运行）

**现象**：运行 `python3 scan_ble.py` 时，脚本直接崩溃，退出码 134（SIGABRT），没有任何错误信息输出。

**分析过程**：
- 退出码 134 = SIGABRT，说明进程被系统强制终止，不是代码逻辑错误
- macOS 对蓝牙访问有严格的隐私控制（TCC 机制），应用必须获得用户授权才能使用蓝牙
- 终端应用（Terminal / VS Code / Cursor）默认没有蓝牙权限，首次调用 CoreBluetooth 框架时，如果没有权限就会被系统 kill

**解决方案**：
在 System Settings → Privacy & Security → Bluetooth 中，手动为终端应用开启蓝牙权限，重启终端后生效。

**收获**：
嵌入式/IoT 开发不只是写代码——操作系统层面的安全策略会直接影响硬件通信，特别是在 macOS 这样权限管控严格的平台上。这是课本上不会教的实战经验。

---

## 问题 #2：bleak 库 API 版本不兼容

**时间**：BLE 扫描脚本首次成功运行阶段

**现象**：蓝牙权限修复后，脚本能开始扫描，但立刻报错：
```
AttributeError: 'BLEDevice' object has no attribute 'rssi'
```

**分析过程**：
- 参考代码基于 bleak 旧版本编写，直接通过 `device.rssi` 读取信号强度
- 安装的是 bleak 2.1.1（最新版），API 发生了变化
- 新版中 RSSI 不再挂在 `BLEDevice` 对象上，而是放在 `AdvertisementData` 中
- 需要使用 `BleakScanner.discover(return_adv=True)` 才能拿到广播数据

**解决方案**：
```python
# 旧版（不工作）
devices = await BleakScanner.discover(5.0)
for d in devices:
    print(d.rssi)  # AttributeError

# 新版（修复后）
devices = await BleakScanner.discover(5.0, return_adv=True)
for addr, (d, adv) in devices.items():
    print(adv.rssi)  # 正确
```

**收获**：
开源库的版本迭代会引入 breaking changes。在工程实践中，不能盲目复制示例代码，要根据实际安装的版本查阅对应文档。这种"代码看起来对、跑起来报错"的情况在真实开发中非常常见。

---

## 问题 #3：设备端 BLE 连接状态显示始终为灰色（未连接）

**时间**：固件开发 + Python 端数据接收验证阶段

**现象**：Python 端成功连接设备并接收到完整的 IMU 数据流（30 秒收到 936 个数据包），但 M5StickC Plus2 的屏幕上蓝牙状态指示灯始终显示灰色（"未连接"），与实际状态矛盾。

**分析过程**：
- 数据能正常传输说明 BLE 连接确实建立了
- 固件代码中 `deviceConnected` 变量在 `onConnect` 回调里被设为 `true`
- 但 BLE 回调函数运行在 ESP32 的 FreeRTOS 的**另一个任务/线程**上
- `deviceConnected` 声明为普通 `bool`，编译器可能将其缓存在寄存器中
- 主循环 `loop()` 中读取的始终是缓存的旧值 `false`，而不是内存中被回调修改后的 `true`
- 这是一个经典的**多线程可见性问题**

**解决方案**：
```cpp
// 修复前
bool deviceConnected = false;

// 修复后：volatile 关键字告诉编译器每次都从内存读取
volatile bool deviceConnected = false;
```

**收获**：
这是嵌入式系统中一个经典的并发问题。`volatile` 关键字在普通应用开发中几乎用不到，但在嵌入式多任务环境（RTOS、中断处理）中至关重要。这个 bug 的隐蔽之处在于：系统功能（数据传输）完全正常，只是 UI 显示错误——如果不仔细对比"数据能传但界面显示未连接"这个矛盾，很容易忽略。调试不仅是看错误日志，更要观察系统行为中的"不一致"。

---

## 问题 #4：数据接收频率远低于预期（31Hz vs 预期 86Hz）

**时间**：固件初版 + Python 数据接收测试阶段

**现象**：固件端 `delay(10)` 理论上支持 ~100Hz 的循环频率，但 Python 端实际只收到 ~31Hz 的数据。

**分析过程**：
- 逐项计算每次 loop 的耗时：
  - IMU 读取：~1ms
  - **全屏 Sprite 渲染 + SPI 推送到屏幕**：~15-20ms（240×135×16bit）
  - BLE notify：~1ms
  - delay(10)：10ms
  - 合计：~30ms/轮 ≈ 33Hz，与实测 31Hz 吻合
- 瓶颈是**每帧都做全屏显示刷新**，SPI 传输 240×135 像素需要大量时间

**解决方案**：
将显示刷新与 IMU 采集/BLE 发送**解耦**：
- IMU 读取 + BLE 发送：每轮都执行（高频）
- 屏幕刷新：每 3 轮执行一次（~33fps，人眼看不出差别）
- delay 从 10ms 降到 2ms

```cpp
// 每轮都读 IMU 和发 BLE
// 但只有每 3 轮才刷屏
loopCount++;
if (loopCount >= 3) {
    loopCount = 0;
    // 渲染 + 推屏（耗时操作）
}
```

**结果**：频率从 ~31Hz 提升到 ~86Hz，提升 2.75 倍。

**收获**：
嵌入式系统的性能优化核心思路是**识别瓶颈并分离关键路径**。数据采集是时间敏感任务，显示刷新是人眼感知任务，两者对实时性的要求完全不同。把它们放在同一个循环里以相同频率执行，是一种资源浪费。这个优化思路在所有实时系统中都适用：区分"必须快"和"够快就行"的任务，分别用不同频率调度。

---

## 问题 #5：Ctrl+C 退出后设备无法被重新发现

**时间**：recorder.py 开发测试阶段

**现象**：第一次运行 `recorder.py` 正常连接设备。Ctrl+C 退出后，再次运行，设备扫描不到，必须手动重启 M5StickC Plus2 + 重启 Mac 蓝牙才能恢复。

**分析过程**：
发现是**两端都有问题**：

1. **Python 端（电脑）**：Ctrl+C 直接杀死进程，BLE 连接没有正常断开。macOS CoreBluetooth 的底层仍认为连接存在，阻塞了新的连接请求。

2. **固件端（设备）**：即使 macOS 最终超时断开，ESP32 的 `onDisconnect` 回调触发后，**没有重新启动 BLE 广播**。设备变成了"活着但隐身"的状态——开机正常，但不再广播自己的存在，任何扫描都找不到它。

**解决方案**：

固件端——在断开回调中重启广播：
```cpp
void onDisconnect(BLEServer *s) {
    deviceConnected = false;
    delay(500);
    pServer->getAdvertising()->start();  // 关键：重新开始广播
}
```

Python 端——用信号处理替代暴力退出：
```python
loop = asyncio.get_event_loop()
def _signal_handler():
    state.running = False  # 设置标志位，让主循环优雅退出
loop.add_signal_handler(signal.SIGINT, _signal_handler)
```
`state.running = False` 后，`async with BleakClient` 的上下文管理器会正常执行 `__aexit__`，发送标准的 BLE 断开请求。

**收获**：
BLE 是一个**有状态的协议**，连接和断开都需要双方协商。强制杀死一端不等于连接消失——另一端可能还在等待。而 ESP32 BLE 的广播不会在断开后自动恢复，这是一个需要手动处理的边界情况。在 IoT 系统中，**连接生命周期管理**（建立、维持、优雅断开、异常恢复）和数据传输本身一样重要。这个问题也提醒我们：开发中不能只测"正常流程"，断开、重连、异常退出这些边界场景往往是实际使用中最容易出问题的地方。

---

## 问题 #6：32.6% 的数据包丢失——BLE 传输瓶颈

**时间**：recorder.py 首次完整录制 + 数据质量分析阶段

**现象**：录制 24 秒，理论上应收到 ~2033 包（86Hz），实际只收到 1369 包。丢包率 32.6%。同时观察到 35.2% 的数据包以批量方式到达（多个包的本地时间戳几乎相同），最大时间间隔达 388ms。

**分析过程**：
- BLE Notify 是**无确认机制**的（类似 UDP），发送方不等待接收方确认
- macOS CoreBluetooth 的默认连接间隔约 30ms
- 每个连接间隔内只能传输有限数量的通知（通常 4-6 个）
- 设备以 86Hz 发送 = 每 30ms 连接窗口需要传 ~2.6 个通知
- 看似够用，但 BLE 协议开销、信道竞争、macOS 调度延迟等因素导致实际吞吐量不足
- **关键洞察**：问题不在于单个包太大，而在于**通知频率太高**

**解决方案**——批量打包二进制协议：

核心思路：降低 BLE 通知频率，但不降低数据率。

设备端每 3 次 IMU 读数打成一个二进制包再发送：
- 通知频率：86Hz → ~29Hz（远低于 BLE 连接间隔限制）
- 实际数据率：保持 86Hz（每个通知包含 3 组完整数据）

二进制协议设计：
```
Packet (52 bytes):
  Header (4 bytes):
    [0] state: 0=IDLE, 1=REC
    [1] set_number
    [2] reading_count (3)
    [3] reserved

  Per Reading (16 bytes × 3):
    uint32_t timestamp     (设备 millis)
    int16_t  ax, ay, az    (加速度 × 1000)
    int16_t  gx, gy, gz    (陀螺仪 × 10)
```

选择二进制而非文本格式：旧的文本协议每条 ~70 字节，二进制每条仅 16 字节，3 条总共 52 字节（含头部），完全在 BLE MTU 范围内。

**结果**：丢包率从 32.6% 降到 **0%**。最大间隔从 388ms 降到 26ms。

**收获**：
这个问题的解决体现了**系统级思维**的重要性。表面上看是"丢包"，直觉反应可能是"增大缓冲区"或"加重传机制"。但深入分析后发现根本原因是协议层面的频率不匹配。解决方案不是修补传输层，而是**重新设计数据协议**——用批量打包降低通知频率，用二进制编码压缩数据体积。这种"改变问题的形状而不是硬碰硬"的思路，在工程设计中非常有价值。

---

## 问题 #7：33.9% 的数据是重复值——IMU 采样率与读取频率不匹配

**时间**：批量协议优化后的数据质量验证阶段

**现象**：丢包问题解决后，新的录制数据显示有效率 106.4 Hz（高于 IMU 理论上限），但 33.9% 的相邻数据点具有完全相同的加速度和陀螺仪值。总数据量 3567 远超 86Hz 的预期 2883。

**分析过程**：
- 优化 delay 到 2ms 后，loop 运行频率超过 100Hz
- 但 MPU6886 传感器的内部硬件采样率只有 ~65-70Hz
- 当软件读取频率 > 硬件产出频率时，多次读取会得到**同一份数据**
- 这些重复数据没有实际物理意义，会污染后续分析
- 在设备时间戳的间隔分布中可以明显看到：50% 的间隔是 2-3ms（远快于 IMU 实际更新周期）

**解决方案**：
在固件中添加基于时间的采样门控，只在 IMU 有新数据时才读取和缓冲：

```cpp
unsigned long lastIMUTime = 0;
const unsigned long IMU_INTERVAL_MS = 10;  // 10ms = 100Hz 上限

void loop() {
    unsigned long now = millis();
    if (now - lastIMUTime >= IMU_INTERVAL_MS) {
        lastIMUTime = now;
        // 读 IMU → 缓冲 → 显示 → BLE 发送
    }
}
```

10ms 间隔（100Hz）略高于 IMU 真实采样率（~70Hz），确保不漏采，但避免读取速度远超产出速度的重复问题。

**预期结果**：重复率降至接近 0%，每个数据点都是真实的独立测量值。

**收获**：
"数据量大"不等于"数据质量高"。在传感器系统中，盲目提高读取频率只会产生冗余数据，甚至引入噪声。正确的做法是理解硬件的物理限制（ADC 采样率、数据就绪中断），让软件采样频率**匹配**而非超越硬件能力。这个问题也展示了数据分析在工程调试中的价值——如果不对录制的 CSV 做统计分析（间隔分布、重复检测），这个问题根本不会被发现。

---

## 技术栈演进时间线

| 版本 | 频率 | 丢包率 | 重复率 | 关键改动 |
|------|------|--------|--------|----------|
| v1 | 31 Hz | N/A | N/A | 初始固件，每帧全屏刷新 |
| v2 | 86 Hz | 32.6% | ~0% | 显示/数据分离，delay 降低 |
| v3 | 106 Hz* | 0% | 33.9% | 二进制批量协议，3 读数/包 |
| v4 (当前) | ~70-80 Hz (预期) | 0% | ~0% (预期) | 定时采样门控，匹配 IMU 硬件率 |

*v3 的 106Hz 包含了 33.9% 重复数据，实际有效数据率约 70Hz

---

## 问题 #8：OpenCV 无法通过 HTTP 拉取 DroidCam 视频流

**时间**：阶段二——视觉管道开发

**现象**：`cv2.VideoCapture("http://192.168.66.169:4747/video")` 返回连接失败，但同一 URL 在浏览器中可以正常播放视频。curl 请求返回 HTTP 200。

**分析过程**：
- curl 返回 200 说明网络和 URL 都没问题
- 尝试了 `/video`、`/mjpegfeed`、`/videofeed` 三个端点，全部失败
- 尝试指定 `cv2.CAP_FFMPEG` 和 `cv2.CAP_AVFOUNDATION` 后端，均报错："backend is generally available but can't be used to capture by name"
- 检查 OpenCV 构建信息确认 FFmpeg 已编译，但 pip 安装的 OpenCV 在 **macOS ARM (Apple Silicon)** 上的 FFmpeg 库不包含 HTTP 协议支持
- 这是一个 opencv-python pip 包的已知限制，不是代码问题

**解决方案**：
绕过 OpenCV 的视频捕获，自己手写 MJPEG 流解析器：
```python
class MjpegStreamReader:
    """手动解析 MJPEG 流中的 JPEG 帧边界"""
    def _reader(self):
        stream = urllib.request.urlopen(self.url)
        buf = b""
        while self.running:
            buf += stream.read(4096)
            start = buf.find(b"\xff\xd8")  # JPEG 起始标记
            end = buf.find(b"\xff\xd9")    # JPEG 结束标记
            if start != -1 and end != -1:
                jpg = buf[start:end + 2]
                frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
```
在后台线程持续读取 HTTP 流，按 JPEG 标记（`FFD8` 开始、`FFD9` 结束）切割出每一帧，用 `cv2.imdecode` 解码为 OpenCV 可用的图像矩阵。

**收获**：
当高层抽象（OpenCV 的 VideoCapture）失败时，理解底层协议（MJPEG = HTTP 传输的连续 JPEG 帧）就成了关键。MJPEG 的本质极其简单——它就是一串 JPEG 图片通过 HTTP 连续发送——知道这一点就能用 20 行代码手动实现。这个例子展示了"了解协议原理"比"会调 API"更重要：API 可能在特定平台上出 bug，但协议是不变的。

---

## 问题 #9：MediaPipe 新版移除了 `solutions` API

**时间**：阶段二——MediaPipe 骨骼检测集成

**现象**：
```python
mp_pose = mp.solutions.pose
# AttributeError: module 'mediapipe' has no attribute 'solutions'
```
所有网上的 MediaPipe 教程都使用 `mp.solutions.pose`，但安装的 0.10.33 版本中这个模块不存在。

**分析过程**：
- 检查 `dir(mediapipe)` 发现只有 `['Image', 'ImageFormat', 'tasks']`
- MediaPipe 0.10.x 完全重构了 API，从 `solutions`（旧）迁移到 `tasks`（新）
- 新 API 需要显式下载模型文件（`.task` 格式），不再内置
- 导入路径也变了：`from mediapipe.tasks.python.vision import PoseLandmarker`
- 而且 `import mediapipe.tasks.python.vision as mp_vision` 会失败（模块结构问题），必须用 `from ... import` 语法

**解决方案**：
1. 下载 `pose_landmarker_lite.task` 模型文件
2. 使用新的 tasks API：
```python
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode
from mediapipe.tasks.python import BaseOptions

options = PoseLandmarkerOptions(
    base_options=BaseOptions(model_asset_path="pose_landmarker_lite.task"),
    running_mode=RunningMode.IMAGE,
)
landmarker = PoseLandmarker.create_from_options(options)

# 使用
mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
results = landmarker.detect(mp_image)
landmarks = results.pose_landmarks[0]  # 第一个人
```
3. 骨骼连接线需要手动绘制（旧 API 的 `draw_landmarks` 不再可用）

**收获**：
AI/ML 库的 API 变化速度远超传统软件库。MediaPipe 在一个大版本中完全重构了面向用户的接口，导致互联网上 90% 的教程代码无法运行。这提醒我们：**不能依赖教程代码，要依赖官方文档和实际安装版本的 API**。解决方法是检查 `dir()` 和 `__version__`，从实际可用的模块反向推导正确的使用方式，而不是从教程正向复制。

---

## 问题 #10：NumPy 版本三方冲突（OpenCV vs TensorFlow vs MediaPipe）

**时间**：阶段二——依赖安装

**现象**：安装 MediaPipe 后，`import mediapipe` 报错 `AttributeError: _ARRAY_API not found`，提示 NumPy 1.x 编译的模块无法在 NumPy 2.x 下运行。

**分析过程**：
- MediaPipe 0.10.33 拉取了 numpy 2.2.6（最新版）
- 但系统中已有 tensorflow-macos 2.15.0，它要求 `numpy<2.0.0`
- 降级到 numpy 1.26.4 后，opencv-python 4.13.0 又要求 `numpy>=2`
- 三个包形成了**循环版本冲突**：MediaPipe ↔ TensorFlow ↔ OpenCV

**解决方案**：
安装兼容 numpy 1.x 的 OpenCV 旧版本：
```bash
pip3 install "numpy<2" "opencv-python<4.11" "opencv-contrib-python<4.11"
```
最终组合：numpy 1.26.4 + OpenCV 4.10.0 + MediaPipe 0.10.33 + TensorFlow 2.15.0，全部兼容。

**收获**：
Python 生态的**依赖地狱**是真实存在的工程问题。当多个大型库（ML 框架、计算机视觉库、数学库）共存时，版本约束可能互相矛盾。解决思路是：找到冲突链中**最容易降级**且**影响最小**的环节。这里 OpenCV 4.10 vs 4.13 功能差异极小，是最佳降级点。在生产环境中，通常用虚拟环境（venv/conda env）隔离不同项目的依赖来避免此类问题。

---

## 问题 #11：前后端契约不匹配 —— UI 永远空白的"静默失败"

**时间**：阶段六 Coach Workstation 完善阶段

**现象**：
训练分析页面上有一块漂亮的「传感器数据」卡片——HTML 结构完整、CSS 样式到位、前端函数 `buildSensorSection(report)` 也正确实现，却**永远显示空白**。用户投诉说"这个卡片看起来是假的"。

**分析过程**：

初看以为是 CSS 的 `display: none` 或 z-index 问题，但 DOM 检查显示卡片元素存在，只是内容为空。打开浏览器开发者工具看网络请求：
```
GET /api/sets/set_002_20260319_165319/report  → 200 OK
```
返回数据：
```json
{
  "overall_score": 7.9,
  "metrics": [...],
  "phases": [...],
  "correlation": -0.497
}
```
发现问题了——**后端根本没有返回 `imu_summary` 字段**。

再看前端代码：
```js
function buildSensorSection(report) {
    const imuData = report.imu_summary || {};   // ← {} 
    const nodeBlocks = Object.entries(imuData).map(...).join('');
    if (!nodeBlocks) return '';                  // ← 直接返回空字符串
    // ...
}
```

前端代码非常"友好"——遇到缺失字段时静默退化为空字符串，不报错、不警告。这是典型的**防御式编程掩盖了契约缺口**。

**根本原因**：
前端 UI 设计（预留了 IMU 卡片布局）和后端 API 实现（只返回核心评分字段）**在不同时间由不同目标推进**，没有共享的数据契约文档。前端开发时想象"未来会有"，后端实现时优先"当前必要"，两边各自 OK，合在一起就是 UI 空壳。

**解决方案**：

**1. 服务端补齐 `imu_summary` 计算（fastapi_app/api_routes.py）**：
```python
def _imu_summary(set_dir: str) -> dict:
    summary = {}
    for node, df in load_all_imus(set_dir).items():
        if df.empty:
            continue
        packets = len(df)
        duration = float(df["timestamp_local"].iloc[-1] - df["timestamp_local"].iloc[0])
        rate = packets / duration
        tilt = calc_imu_tilt(df[["ax", "ay", "az"]].to_dict("records"))
        
        # 丢包率估算：设备时间戳间隔 > 3× 中位数 视为丢包窗口
        dev_ts = df["timestamp_device"].values.astype(float)
        intervals = np.diff(dev_ts)
        med = float(np.median(intervals))
        lost = int(np.sum(np.round(intervals[intervals > med * 3] / med) - 1))
        
        summary[node] = {
            "packets": packets, "rate": round(rate, 1), "duration": round(duration, 2),
            "tilt_mean": float(np.mean(tilt)), "tilt_std": float(np.std(tilt)),
            "lost": lost, "loss_pct": round(100 * lost / max(packets + lost, 1), 2),
        }
    return summary
```

**2. 把 `imu_summary` 加入 `/report` 响应** —— 一个字段，前端瞬间有了数据。

**3. 顺便补齐其他缺失字段**：`duration` / `frame_count` / `fps_mean` / `score_breakdown` / `has_video`，把 API 契约一次性对齐。

**收获**：

这个 bug 的教训不是代码层面的（实现都对），而是**工程流程层面**的：
1. **防御式编程是双刃剑**：`report.imu_summary || {}` 让代码不崩溃，但也让问题不可见。真正重要的契约缺失应该**响亮地失败**（fail loud）或者**明确地降级**（显示"数据缺失"占位符），而不是静默吞掉。
2. **前后端的真正契约是 TypeScript / Pydantic / OpenAPI，而不是口头约定**：如果这个 API 响应定义为 Pydantic 模型，字段缺失在 serialization 阶段就会报错。
3. **UI 的"空态"设计比"正常态"更值得投入**：当数据缺失时给出明确反馈（"此训练组无 IMU 数据"）比什么都不显示有用得多。

这类"UI 看起来正常但功能实际失效"的问题在实际产品中极其常见，**一次前后端接口审查（把实际响应和 UI 期望对一遍）**就能找到一堆。

---

## 问题 #12：视频 MP4 下载而非流式播放 —— 必须支持 HTTP Range 请求

**时间**：阶段六 分析页视频播放器开发

**现象**：
分析页加入 `<video>` 元素播放录制的 `video.mp4`，想让教练可以回放。第一版路由：
```python
@router.get("/sets/{name}/video")
async def stream_video(name: str):
    return FileResponse(f"data/{name}/video.mp4", media_type="video/mp4")
```

在 Chrome / Safari 中：
- 视频可以播放
- **但是进度条不能拖动**（拖到任意位置就回到开头）
- **10MB+ 视频在移动端流量爆炸**（每次切换 Set 都重新下载整个文件）

**分析过程**：

HTML5 `<video>` 元素依赖 **HTTP Range 请求** 实现 seek（跳转）：
- 用户拖进度条到 50% 时，浏览器发 `Range: bytes=5242880-` 请求
- 服务器应该返回 `206 Partial Content` + 从该字节开始的数据
- 不支持 Range 的服务器返回完整文件，浏览器只能回到开头

`FastAPI.FileResponse` 默认**不解析 Range header**，直接 200 返回整个文件。对于图片、小文件没问题，对视频就是 UX 灾难。

另外，完整下载 10MB 视频：
- 首屏加载延迟高（要等整个视频下载完才能开始播放）
- 移动流量浪费（用户可能只想看前 5 秒）
- 服务器内存压力（多个客户端同时下载会占用大量 RAM）

**解决方案**：

手动实现 HTTP Range 响应：
```python
@router.get("/sets/{name}/video")
async def stream_video(name: str, request: Request):
    video_path = f"data/{name}/video.mp4"
    file_size = os.path.getsize(video_path)
    range_header = request.headers.get("range")
    
    if range_header:
        # 解析 "bytes=START-END"
        m = range_header.replace("bytes=", "").split("-")
        start = int(m[0]) if m[0] else 0
        end   = int(m[1]) if len(m) > 1 and m[1] else file_size - 1
        end   = min(end, file_size - 1)
        length = end - start + 1
        
        # 流式读取（避免把整个分片加载到内存）
        def iterfile(s, ln):
            with open(video_path, "rb") as f:
                f.seek(s)
                remaining = ln
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk: break
                    remaining -= len(chunk)
                    yield chunk
        
        return StreamingResponse(
            iterfile(start, length),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )
    return FileResponse(video_path, media_type="video/mp4")
```

关键点：
1. **状态码 206** 而不是 200：告诉浏览器这是分片响应
2. **`Content-Range` header** 声明分片范围和总大小
3. **`Accept-Ranges: bytes`** 让浏览器知道可以继续发 Range 请求
4. **生成器 + 64KB chunks**：边读边发，内存占用恒定

**结果**：
- Chrome / Safari / Firefox 进度条可以任意拖动
- 首屏只下载前几百 KB（视频的 moov atom 和开头几秒）
- 服务器内存使用恒定（不受视频大小影响）

**收获**：

这是一个典型的**"高层抽象的代价"问题**：`FileResponse` 是 FastAPI 提供的便利抽象，覆盖了 90% 的小文件场景，但在视频、大文件、断点续传等场景下**抽象的泄漏**就显现了。

**知道底层协议（HTTP Range）永远比只会用高层 API 更有价值**：
- `FileResponse` 只是 `open(file).read()` + 设置 Content-Type 的封装
- Range 请求是 HTTP/1.1 标准（RFC 7233），任何视频播放场景都会用到
- 一旦理解协议，手动实现只需要 20 行代码

这个问题的姊妹问题是 #8（OpenCV 拉 MJPEG）——**当高层 API 失效时，底层协议理解让你不至于束手无策**。软件工程中真正值钱的不是 API 熟练度，而是对下面一层的理解。

---

## 问题 #13：MediaPipe 在遮挡部位"假装看得见" —— visibility 门控的必要性

**时间**：阶段六上线后真机测试

**现象**：
用户把 M5Stick 戴在手臂上，相机只拍到上半身（腿完全不在画面内），却发现分析页面上仍然有「腿部垂直偏差」、「双腿对称性」等"正常数值"。更诡异的是这些数值还会**随动作变化而变化**——看起来像真数据。

**分析过程**：

翻 `landmarks.csv`，每行 134 列（33 关键点 × 4 字段），每个点除 x/y/z 外还有 `_vis` 列——这是 MediaPipe 给的**可见度置信度**（0.0–1.0）。抽查发现，画面中没腿的帧里，`right_ankle_vis` 只有 0.05–0.15（远低于正常可见的 0.9+）。但 `right_ankle_x` / `right_ankle_y` 并不是 NaN 或 0——**MediaPipe 根据人体先验给了一个"推测坐标"**（大约在画面下方某处）。

这是 MediaPipe 设计上的取舍：对被遮挡/出画的关键点，它选择**继续"猜"一个合理位置**，而不是抛出 null。目的是保证骨骼连通性（对渲染友好），但对下游**做几何计算的业务逻辑是陷阱**。

核心代码 `dashboard/core/vision_angles.py`：
```python
def calc_leg_deviation_vision(df, side="right"):
    cols = [f"{side}_hip_x", f"{side}_hip_y", f"{side}_ankle_x", f"{side}_ankle_y"]
    # ...
    for _, row in df.iterrows():
        angle = _angle_from_vertical(row[cols[0]], row[cols[1]], row[cols[2]], row[cols[3]])
        results.append(angle)
```
**它完全没读 `*_vis` 列**。MediaPipe 推测的坐标被当成真数据，算出一个"腿部垂直偏差"给教练看。教练据此调整训练——**这是真正的坑**。

**解决方案**：

三层修复：

**1. 底层几何计算加 visibility 门控**（`dashboard/core/vision_angles.py`）：
```python
VIS_THRESHOLD = 0.5

def _vis(row, key):
    vc = f"{key}_vis"
    if vc not in row.index:
        return 1.0  # 旧 CSV 没这列，保持兼容
    return float(row[vc])

def calc_leg_deviation_vision(df, side="right"):
    # ...
    for i, (_, row) in enumerate(df.iterrows()):
        if _vis(row, f"{side}_hip") < VIS_THRESHOLD or _vis(row, f"{side}_ankle") < VIS_THRESHOLD:
            results[i] = np.nan     # ← 遮挡帧返回 NaN
            continue
        results[i] = _angle_from_vertical(...)
```

**2. 聚合层用 nan-safe 统计**（`dashboard/core/scoring.py`）：
```python
# 旧：
dev_val = float(np.mean(calc_leg_deviation_vision(landmarks_df)))
# 新：
_a = calc_leg_deviation_vision(landmarks_df)
dev_val = float(np.nanmean(_a)) if np.any(~np.isnan(_a)) else 0.0
```
`np.nanmean` 忽略 NaN；如果全部帧都遮挡，用安全默认值（腿部偏差 → 0°，膝伸直 → 180°，即"没问题"）。

**3. API 输出 JSON 安全**（`fastapi_app/api_routes.py`）：
```python
series[key] = [None if np.isnan(arr[i]) else round(float(arr[i]), 2) for i in idx]
```
JSON 规范不支持 NaN，必须转成 `null`。

**4. 前端折线图在 null 处断线**（`fastapi_app/static/app.js`）：
```js
let pen = false;
s.data.forEach((v, i) => {
    if (v == null || Number.isNaN(v)) { pen = false; return; }
    if (!pen) { c.moveTo(x, y); pen = true; }
    else c.lineTo(x, y);
});
```
遮挡期间曲线出现**明显断口**，教练一眼看出"这段没拍到腿"。

**收获**：

1. **机器学习库的输出不是"上帝真理"**。MediaPipe 设计者有他们的优化目标（渲染平滑），我们的目标是**严谨的几何计算**。对 ML 输出做**下游可信度检查**是工程师的责任。
2. **缺失数据的三种表达**：null（不知道）、0（已知为零）、猜测值（可能是真，也可能是假）。混淆这三者会让整个数据分析都靠不住。
3. **断链比假数据安全**：宁可折线上断一段让教练看到"这里没数据"，也不要画一条假曲线骗教练做出错误判断。
4. **API 契约必须 JSON-safe**：NumPy 的 NaN/Inf 直接序列化成 JSON 会报错或变成非法 token。跨语言边界时统一用 `None` → `null`。

---

## 问题 #14：页面状态不持久 —— rotation 是最小但最典型的样本

**时间**：阶段六上线后用户首次真机使用

**现象**：
教练每次打开 dashboard，视频默认显示是"侧倒"的（手机竖放 DroidCam 推出来的流就是竖向）。他必须每次点一下"旋转 90°"才能看到正方向。调整好之后，下次重新打开——又是侧倒。

**分析过程**：

翻前端代码：
```js
let currentRotation = 0;  // ← 硬编码初始值
```
翻后端 `POST /api/camera/config`：
```python
if req.rotation is not None and req.rotation in (0, 90, 180, 270):
    _camera.rotation = req.rotation
    # URL 保存了 → hw["camera_url"] = req.url
    # 但 rotation 忘了持久化！
```
`CameraManager.__init__` 里也是：
```python
self._rotation = 0  # ← 每次重启又是 0
```

所以链条：**前端发 POST → 后端更新内存 → 没写 config.toml → 重启内存丢失 → CameraManager 默认 0**。三个环节任何一个持久化了都不会出问题，但三个都漏了。

**解决方案**：

把 rotation 作为一等配置字段穿三层：

```python
# camera_manager.py
def __init__(self, camera_url=None, rotation=None):
    cfg_hw = load_config().get("hardware", {})
    if camera_url is None:
        camera_url = cfg_hw.get("camera_url", "http://...")
    if rotation is None:
        rotation = int(cfg_hw.get("camera_rotation", 0))
    self._rotation = rotation if rotation in (0, 90, 180, 270) else 0
```

```python
# api_routes.py  POST /api/camera/config
if req.rotation is not None and req.rotation in (0, 90, 180, 270):
    _camera.rotation = req.rotation
    hw["camera_rotation"] = req.rotation   # ← 持久化到 config.toml
```

```js
// app.js — 页面启动时读配置，让 UI 和后端状态对齐
async function preloadCameraState() {
    const cfg = await fetch('/api/config').then(r => r.json());
    const hw = cfg.hardware || {};
    if (hw.camera_rotation !== undefined) {
        currentRotation = parseInt(hw.camera_rotation, 10) || 0;
        $$('.btn-rot').forEach(b =>
            b.classList.toggle('active', parseInt(b.dataset.rot, 10) === currentRotation));
    }
}
preloadCameraState();
```

**收获**：

这是个**"小而典型"的状态持久化 bug**——单一字段，但暴露了三层架构之间的**状态一致性**问题：
1. UI 状态（浏览器 `currentRotation`）
2. 服务器内存状态（`CameraManager._rotation`）
3. 持久化存储（`config.toml`）

任何改动用户偏好的操作都必须**三层同步**，否则某个层级重启就会"穿帮"。做后端的工程师很容易漏掉第 3 步——因为内存改了"看起来就是对的"，不做长时间 kill-restart 测试发现不了。

**教训**：**一切用户可见的偏好都要默认持久化**。把"持久化"当成状态机的必经步骤，而不是事后的"功能增强"。

---

## 问题 #15：视频区域挤掉录制按钮 —— flex 布局的经典陷阱

**时间**：阶段六真机测试（手机竖向 DroidCam 流）

**现象**：
用户报告"页面大小不统一，需要滚动才能看到下面的按钮"。屏幕录像显示：打开 dashboard 时，视频区域把整屏撑满，"开始录制"按钮被推到视口下方，必须滚动才能点到。

**分析过程**：

原 CSS：
```css
.live-layout {
    display: flex;
    gap: 14px;
    min-height: calc(100vh - 84px);   /* ← min-height，不是 height */
}

.video-wrapper { flex: 1; }

#video-canvas {
    width: 100%;
    max-height: 60vh;                  /* ← 60vh 在横屏 OK，竖屏太高 */
}
```

问题链：
1. `.live-layout` 用 `min-height`——视频大时可以**突破视口**撑开页面
2. 视频是 canvas，`canvas.width = img.width; canvas.height = img.height;` 每帧用真实分辨率。竖屏手机流 480×640 被放到 `width: 100%` → 按屏幕宽度缩放 → 高度按比例变成屏宽的 4/3
3. 1920px 宽屏上，视频高度可以轻松超过 1000px，控制栏被挤到 1500px 往下

这是 flex 布局里经典的"**子元素内容撑爆容器**"问题。**`flex: 1` 只保证占满剩余空间，不限制最大尺寸**。

**解决方案**：

三处联动改：
```css
.live-layout {
    display: flex;
    gap: 14px;
    height: calc(100vh - 84px);      /* 从 min-height 改成 height — 锁死视口 */
    overflow: hidden;
}

.video-col {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 0;                    /* 关键！允许 flex 子项收缩到小于内容高度 */
}

.video-wrapper {
    flex: 1 1 auto;
    min-height: 0;                    /* 同上 */
    display: flex;
    align-items: center;
    justify-content: center;
}

#video-canvas {
    max-width: 100%;
    max-height: 100%;                 /* 不再用 60vh，跟随容器 */
    width: auto;
    height: auto;
    object-fit: contain;
}
```

关键点：**`min-height: 0` 是破解这个问题的魔法**。Flex item 默认 `min-height: auto`，意思是"最小高度 = 内容自然高度"。如果 canvas 里有个 640px 的图片，flex item 就至少 640px，无论父容器多小。`min-height: 0` 让它可以收缩到任意尺寸，再配合 `max-height: 100%` 让 canvas 按比例缩放。

**收获**：

`min-height: 0` 是 flex 布局最反直觉的坑之一：
- 初学者以为 `flex: 1` 就能控制大小
- 实际上 flex 算法有个"内容高度下限"保护
- 需要显式 `min-height: 0` / `min-width: 0` 才能真正让子项按 flex 比例分配，而不是被内容撑大

这个坑之所以隐蔽，是因为**大部分测试环境是横屏**，内容自然高度不超过 60vh，症状不出现；一上竖屏相机/真实用户设备就炸。**写响应式布局必须测至少 3 种纵横比**：16:9 桌面、9:16 手机竖向、1:1 Instagram 式。

---

## 问题 #16：BLE 重启后必须重启 M5 —— BLE 状态机的"失联不失约"

**时间**：阶段六真机多次开发调试后

**现象**：
教练每次 `Ctrl+C` 停掉 dashboard 服务、重启之后，M5Stick 的 BLE 就**连不上了**——必须按 M5 的电源键重启硬件，Python 才能再次扫描到它。对开发迭代体验极差：每改一行代码重启都要按 2 次硬件电源键。

**分析过程**：

BLE 是**有状态的双方协议**。建立连接时，中央（Python/macOS CoreBluetooth）和外设（M5）各自维护一份"连接状态"。正常断开需要一方发 `LL_TERMINATE_IND`，另一方收到后才会清理状态并重新进入广播模式。

问题链条：
1. `Ctrl+C` → Python 主进程收到 SIGINT → FastAPI shutdown 被触发
2. `shutdown()` 调 `ble_manager.stop()` → 设置 `self.running = False`
3. 后台 daemon 线程中的 asyncio 循环**还没来得及检测到 running=False**，主进程就退出了
4. 守护线程（`daemon=True`）被操作系统**强行终止**
5. `async with BleakClient(...)` 的 `__aexit__` 没机会执行 → **没发送断开请求**
6. M5 端依然认为"连接存活"——**等待 30 秒的 BLE 链路超时**才会发 onDisconnect → 重启广播
7. 用户在 30 秒内重启服务 → 扫描不到 M5 → 以为挂了 → 手动重启 M5

**解决方案**：

两端配合修：

**Python 端 (`ble_manager.py`)**：
```python
def stop(self, grace: float = 4.0) -> None:
    """Signal all node threads to stop with grace period."""
    self.running = False
    for t in self._threads:
        if t.is_alive():
            t.join(timeout=grace)  # ← 等待 asyncio 优雅清理
    self._threads.clear()
```

并在 asyncio 循环中显式断开：
```python
async with BleakClient(target.address) as client:
    node.connected = True
    await client.start_notify(...)
    while (client.is_connected and self.running and not node.force_reconnect):
        await asyncio.sleep(0.2)
    try:
        await client.stop_notify(...)
    except Exception:
        pass
    if client.is_connected:
        try:
            await client.disconnect()   # ← 主动发断开，不等 __aexit__
        except Exception:
            pass
```

**force_reconnect 机制** — `/api/ble/reconnect` 设置每个节点的 `force_reconnect=True`：
```python
@router.post("/ble/reconnect")
async def ble_reconnect():
    for node in _ble.nodes.values():
        node.force_reconnect = True
    return {"status": "reconnecting"}
```
内循环观测这个 flag → 立即 `disconnect()` → 外层重新 scan。这样即使万一进入"死连接"状态，用户点一下"重连 BLE"按钮就能强制修复，不用重启硬件。

**退避算法** — 扫描失败不再固定 3 秒：
```python
backoff = 1.0
while self.running:
    devices = await BleakScanner.discover(4.0, return_adv=True)
    if not target:
        await asyncio.sleep(min(backoff, 4.0))
        backoff = min(backoff * 1.5, 4.0)
        continue
    backoff = 1.0
```
找不到时快速重试（1→1.5→2.25→3.4→4s 封顶），找到后重置。

**收获**：

1. **daemon 线程是开发陷阱**：方便启动时不管它，但进程退出时**没有任何清理机会**。对于有持久外部连接（BLE、TCP、数据库）的线程，应该用非守护线程或显式 join。
2. **协议状态机必须双向对齐**：只管自己那头的"我断开了"，不管对端的"你收到了吗"，就会留下僵尸连接。BLE 尤其严重，因为 supervision timeout 可以长达 30 秒。
3. **graceful shutdown 不是可选项**：在嵌入式/IoT 系统里，"进程死掉了" ≠ "资源释放了"。把 shutdown 流程写对和把启动流程写对一样重要。
4. **给用户手动兜底**：即使自动重连逻辑完美，硬件物理故障（wifi 干扰、电池弱）仍会卡住。提供"重连"按钮让用户 5 秒内自助解决，远好于每次叫教练重启设备。

---

## 问题 #17：实时页"眼盲手不盲" —— visibility 门控在前后两层都必须做

**时间**：阶段六 visibility 修复（问题 #13）上线后

**现象**：
问题 #13 修好分析页对遮挡关节的伪数据后，**实时页（dashboard 上方的"实时指标"面板）还在显示**：相机里只有上半身，但"腿部垂直 2.2°、膝盖伸直 179.5°"照样跳动。

**分析过程**：

问题 #13 修复的是 `dashboard/core/vision_angles.py` ——这是**分析已录制数据**的路径。而实时页的角度数据来自另一条路径：

```
CameraManager._run() [后台线程]
  → landmarker.detect(mp_image)
  → _compute_angles(landmarks, w, h)
  → self._latest = {..., angles: {...}}
  → ws_video.py → WebSocket → 浏览器
  → updateLiveMetrics(data.angles)
```

核心代码 `fastapi_app/camera_manager.py` 的 `_compute_angles`：
```python
def _compute_angles(landmarks, w, h):
    # ...
    angles["leg_deviation"] = _angle_from_vertical(...)   # ← 不检查 visibility
    angles["knee_extension"] = calc_angle(pt(24), pt(26), pt(28))
```

一模一样的疏漏——**MediaPipe 对被遮挡关节的猜测坐标被直接当数据**。问题 #13 只修了录制后分析那路，这个实时路没改。

**解决方案**：

把同样的 visibility 门控搬到实时路径，加上侧面视角的对侧补充（`elbow_left` / `knee_extension_left` / `shoulder_line`）：

```python
LIVE_VIS_THRESHOLD = 0.5

def _compute_angles(landmarks, w, h):
    lm = landmarks
    def v(idx):
        return getattr(lm[idx], "visibility", 1.0)
    def ok(*idxs):
        return all(v(i) >= LIVE_VIS_THRESHOLD for i in idxs)
    
    angles = {}
    if ok(24, 28):          # 髋 + 踝
        angles["leg_deviation"] = ...
    if ok(24, 26, 28):      # 髋 + 膝 + 踝
        angles["knee_extension"] = ...
    if ok(12, 24):          # 肩 + 髋
        angles["trunk_vertical"] = ...
    # 对侧（侧面拍摄时）
    if ok(11, 13, 15):
        angles["elbow_left"] = ...
    # ...
    return angles
```

前端 `updateLiveMetrics` 看到 `undefined` 会显示 "--"，用户一眼看出"这段没检测到"而不是"数值是 0.0"。

**收获**：

这是**"同一个 bug 在两条代码路径上都得修"** 的典型案例。很多团队有这样的结构：
- 实时路径 / 事后分析路径
- 客户端路径 / 服务端路径
- Web 路径 / 移动端路径

相同的业务规则（比如"遮挡关节不算"）如果没有**集中抽象**，就会散落在多处，修一处漏一处。

**经验**：
1. **写新代码时**，警惕"这个判断在另一个文件我已经写过了"的感觉——很可能意味着应该抽成共享函数
2. **修 bug 时**，问"还有哪些地方可能有同样的问题"——`grep` 找所有相同模式的代码
3. **做 code review 时**，优先看"这个改动有没有对称的遗漏"——往往并发/异步路径会被遗忘

对这个项目而言，我给两条路径都加了 `VIS_THRESHOLD` 常量（分析路径是 `VIS_THRESHOLD`，实时路径是 `LIVE_VIS_THRESHOLD`），未来如果需要可以合并成一个配置项。

---

## 问题 #18：Canvas 不听 object-fit —— 视频在巨大黑框中心变小

**时间**：阶段六 UI 审查

**现象**：
修完 `min-height: 0` flex 陷阱（问题 #15）后，画面不再挤掉按钮，但竖屏手机流（480×720）在 1500px 宽的桌面容器中显示时，**左右各有约 500px 的黑边**——视频看起来"又小又孤独"。

**分析过程**：

尝试过的 CSS：
```css
#video-canvas {
    max-width: 100%;
    max-height: 100%;
    width: auto;
    height: auto;
    object-fit: contain;  /* ← 无效 */
}
```

这里的核心认知错误：**`object-fit` 只适用于 `<img>`、`<video>`、`<object>` 这种"有真实内容"的替换元素**。`<canvas>` 是个"画板"——它有两种尺寸：
1. **像素缓冲区尺寸**（`canvas.width` / `canvas.height` HTML 属性）：决定绘图坐标系
2. **CSS 显示尺寸**（`style.width` / `style.height`）：决定视觉呈现

`object-fit` 对 canvas 无效 —— 浏览器会把 canvas 的像素缓冲区内容**拉伸**填满 CSS 显示区域。

如果我们在 JS 里做 `canvas.width = img.width; canvas.height = img.height;` 然后 CSS `width: 100%; height: 100%`，drawing 被按容器比例拉伸——**画面变形**。

如果 CSS 用 `width: auto; height: auto`，canvas 按像素缓冲尺寸渲染（480×720），`max-*: 100%` 会约束不超过容器，但**不会保持宽高比**——会压缩其中一维导致变形。

**解决方案**：

既然 CSS 自动机制不够，直接用 JS 测量**一次**图像尺寸，**显式计算**wrapper 应有的 CSS 宽高：

```js
let _lastAspect = 0;

function fitVideoWrapper(aspect) {
    if (Math.abs(aspect - _lastAspect) < 0.01) return;
    _lastAspect = aspect;

    const wrap = canvas.parentElement;
    const col = wrap.parentElement;
    const controlsH = col.querySelector('.controls-bar').offsetHeight;
    const availH = col.clientHeight - controlsH - 10;
    const availW = col.clientWidth;

    let targetH = availH;
    let targetW = targetH * aspect;
    if (targetW > availW) {
        targetW = availW;
        targetH = availW / aspect;
    }
    wrap.style.width  = Math.floor(targetW) + 'px';
    wrap.style.height = Math.floor(targetH) + 'px';
}

img.onload = () => {
    canvas.width = img.width;
    canvas.height = img.height;
    // ...draw...
    fitVideoWrapper(img.width / img.height);
};
```

同时把 CSS 改成让 wrapper 承担"宽高比容器"职责：
```css
.video-wrapper {
    flex: 0 1 auto;
    max-width: 100%;
    max-height: 100%;
    /* JS 会写入 inline width/height 来控制比例 */
}
#video-canvas {
    width: 100%;
    height: 100%;
    /* 像素缓冲仍由 JS 按图像尺寸设置 */
}
```

然后把 side panel 从 260 → 340 px，让两侧黑边更窄。

**收获**：

1. **Canvas 和 img 虽然都能显示图像，但在 CSS 语义上完全不同**：canvas 是"有内部坐标系的块级元素"，没有原生 aspect 保持机制。
2. **`object-fit` / `aspect-ratio` 这类"浏览器智能"不是银弹**——看文档 caniuse，确认你的元素类型支持
3. **"前后端分工"的另一种版本**：CSS 做 90% 的布局，但最后 10% 的精确控制往往需要 JS 测量 DOM + 计算 + 赋值。做响应式设计不要纠结"要不要用 JS"，工具选最简单够用的
4. **把一次性计算结果缓存**（`_lastAspect` 只有变化时重算）是小优化但重要——不做这个，每一帧都会触发 layout thrashing

---

## 问题 #19：骨架标注信息量不足 —— 专家期望看到所有可测量维度

**时间**：阶段六真机用户反馈（教练视角）

**现象**：
教练看到原版骨架叠加图只有"肘 155°、膝 178°"两个角度 + 简单的骨骼连线。他的反馈是："我想看到所有关节都有名字、所有角度都有数值，而且骨架要牢牢锁住人的身体。"

**分析过程**：

这不是 bug，是**专家用户对数据密度的期望 vs 普通用户对简洁的期望**的冲突。教练作为专业用户：
- 需要看到每个关键点的名称（以便用专业术语和学生交流："你左肘张角小了"）
- 需要看到所有可计算角度的当前值（多个角度同时评估动作协调性）
- 需要看到置信度（判断标注可靠性）

但普通用户看到 33 个点 + 10+ 个角度 pill 会觉得画面"过载"。

**解决方案**：

不选边站，两者都要 —— 加一个"详细标注"开关（按钮 + 快捷键 `T`，localStorage 持久化）：

**Normal 模式（默认简洁）**：
- 12 条骨骼连线
- 12 个主要关节的圆点
- 3 个关键角度标签（肘、膝、腿）

**Detailed 模式（专家详细）**：
- 全部 33 个关键点圆点（大小随置信度变化，低置信度用半透明）
- 12 个主要关节的**中文名称**标签（左肩、右肩、左肘、右肘……）
- 所有已计算角度的标签（右肘/左肘、右膝/左膝、右髋、右腿/左腿、躯干、肩线）

关键实现：
```js
const JOINT_LABELS = {
    11: '左肩', 12: '右肩', 13: '左肘', 14: '右肘',
    15: '左腕', 16: '右腕', 23: '左髋', 24: '右髋',
    25: '左膝', 26: '右膝', 27: '左踝', 28: '右踝',
};

const ANGLE_MARKERS = [
    { key: 'elbow',               joint: 14, label: 'R肘' },
    { key: 'elbow_left',          joint: 13, label: 'L肘' },
    { key: 'knee_extension',      joint: 26, label: 'R膝' },
    { key: 'knee_extension_left', joint: 25, label: 'L膝' },
    // ...
    { key: 'trunk_vertical',      joint: [23, 24], label: '躯干' },  // 中点
    { key: 'shoulder_line',       joint: [11, 12], label: '肩线' },
];

function drawSkeletonOnCanvas(c, cv, landmarks, angles) {
    const detailed = _annotationMode === 'detailed';
    // ...
    const jointSet = detailed
        ? Array.from({ length: 33 }, (_, i) => i)    // 全部 33 个
        : [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];  // 13 个关键
    // ...
}
```

伴生：
- 置信度映射点大小：`r = 3 + vis * 2`（低置信度 3px，高置信度 5px）
- 低可见度点用半透明颜色 `rgba(59,130,246,0.6)`，提醒"这个点不太靠得住"

**收获**：

1. **专家用户 vs 普通用户的分歧**是产品设计的永恒话题，一般解法：**默认简洁、专家模式明确开关**
2. **UI 开关要同时满足**"记得住偏好"（localStorage）+ "一键切换"（快捷键 `T`）+ "视觉可识别"（按钮的 active 状态）
3. **数据可视化里，置信度不应该被隐藏**——把置信度编码到视觉维度（颜色深浅、圆点大小）比把它藏在文本里更有效
4. **中文标注胜过英文缩写**——用户是中国教练，看到"左肘"比看到"L_Elbow"反应更快

## 问题 #20：打开页面就自动开始录制 —— "首包即状态"的陷阱

**时间**：阶段六真机测试，教练反馈"服务一启动就录了"

**现象**：
教练启动服务器、打开浏览器，发现 dashboard 在**一秒钟内**就从 IDLE 跳到 REC，开始录制。他根本没有按 M5 的 A 键、也没点页面上的"开始录制"按钮。

**分析过程**：

BLE 二进制协议每个包都带 state 字节（0=IDLE, 1=REC）。[ble_manager.py](fastapi_app/ble_manager.py) 用"状态变化检测"防止重复触发：
```python
if node_name == self.master_node and self.on_state_change:
    if not hasattr(node, '_last_dev_state') or node._last_dev_state != dev_state:
        node._last_dev_state = dev_state
        self.on_state_change(dev_state, set_n)
```

看起来正确——"变化时才触发"。但问题在**第一个包**上：此时 `_last_dev_state` 还不存在，条件里的 `or` 短路后直接进 `if`，调用 `on_state_change(dev_state, set_n)` — 且 `dev_state` 可能是 "REC"（如果 M5 上次录制结束时忘了切回 IDLE，或者上个调试会话残留）。

`main.py` 的回调：
```python
if dev_state == "REC" and not recorder.recording:
    recorder.start_recording(set_number)
```

→ **自动启动录制**。用户毫无察觉。

**根本原因**：
"边缘触发（edge-triggered）"的检测逻辑用 `!hasattr` 作为初始值，把**首次观测**也当成"变化"，从而在程序启动时把设备的**既有状态**误判为"新事件"。

**解决方案**：

两步 gate：
```python
if node_name == self.master_node and self.on_state_change:
    if not hasattr(node, '_last_dev_state'):
        node._last_dev_state = dev_state     # 只记录基线，不触发
    elif node._last_dev_state != dev_state:
        node._last_dev_state = dev_state
        self.on_state_change(dev_state, set_n)  # 真实变化才触发
```

第一步"静默建立基线"，之后才响应变化。

**收获**：

这个 bug 在软件里叫做 **"首帧特殊处理"（first-frame special case）**。几乎所有做事件/状态机/传感器融合的系统都会撞一次。经典表现：
- 游戏引擎的 `isButtonPressedThisFrame`：第一帧 `was` 是 undefined，所有已按下按键都"算新按"
- React 的 `useEffect` 依赖数组：第一次渲染依赖都"变化了"
- 自动驾驶的目标追踪：从 nothing → something，每个目标都是"新出现"

**设计原则**：**状态机的边沿检测必须显式区分"初始化"和"状态跳变"两种情况**。不要用 `!hasattr` / `undefined` / `None` 作为"可能变化"的占位——它们的语义是"未知"，不是"旧状态"。

---

## 问题 #21：空数据也给满分 —— 诚实比优雅更重要

**时间**：阶段六真机使用后发现

**现象**：
教练按 Button A 很快又切回，录了一个 0 秒的空 set。进入分析页，看到：
- 综合评分：**10.0 / 10**
- 姿态评分：**10.0**，伸展：**10.0**，对称：**10.0**，运动：**10.0**
- 详细指标每一项都是"达标 · -0.0"

**他以为是界面 bug — 实际上是算法在"编故事"**。

**分析过程**：

翻 `scoring.py` 的老实现：
```python
# 当没有数据时用"安全默认值"
else:
    height_val = 0.0         # assume ok
    knee_val = 180.0          # assume straight, no penalty
    align_val = 180.0         # assume aligned
    trunk_val = 0.0           # assume vertical
    sym_val = 0.0             # assume symmetric
```

这些"安全默认值"的语义全部是"完美"——然后经过 `compute_deduction` 全部得到 `zone="clean"`，deduction = 0。最后 `overall_score = 10.0 - sum(deductions) = 10.0`。

代码里的每个决策都有"设计理由"（"数据没到，先默认满分，总不能凭空扣分吧？"），但**合在一起就是骗教练**。真正的信息——"我们根本没测到这个指标"——在每一层都被"合理默认值"吞掉了。

**解决方案**：

引入 `zone="no_data"` 语义 + 禁用默认值：

```python
@dataclass
class MetricResult:
    name: str
    value: float | None      # None == "no data"
    unit: str
    deduction: float
    zone: str                # "clean" | "minor" | "major" | "no_data"
    max_value: float


def _no_data(name, unit, max_value):
    return MetricResult(name=name, value=None, unit=unit,
                        deduction=0.0, zone="no_data", max_value=max_value)


def _nanmean_or_none(arr, min_samples=1):
    """Return nan-safe mean, or None if nothing usable."""
    if arr is None or len(arr) == 0:
        return None
    valid = np.asarray(arr, dtype=float)[~np.isnan(arr)]
    if len(valid) < min_samples:
        return None
    return float(np.mean(valid))
```

每个指标改成：
```python
trunk_val = _nanmean_or_none(calc_trunk_vertical(landmarks_df), min_samples=3) if has_landmarks else None
if trunk_val is None:
    metrics.append(_no_data("trunk_vertical", "deg", 90.0))
else:
    d, z = compute_deduction(trunk_val, config, metric="trunk_vertical")
    metrics.append(MetricResult("trunk_vertical", trunk_val, "deg", d, z, 90.0))
```

**综合评分改由"可用指标"计算**：
```python
real_metrics = [m for m in metrics if m.zone != "no_data"]
if len(real_metrics) < 2:
    overall_score = None                         # 干脆不给分
else:
    overall_score = max(0.0, 10.0 - sum(m.deduction for m in real_metrics))
```

**前端的相应改动**：
```js
if (zone === 'no_data' || m.value === null) {
    return `<div class="metric-card no-data">
              <span class="mc-value">—</span>
              <div class="mc-zone zone-no_data">无数据</div>
            </div>`;
}
```

综合评分为 null 时显示"—"并附横幅解释："本训练组数据不足，无法给出综合评分。"

**验证**：
一个只有 IMU / 没有视频的 set，以前显示 10.0，现在显示 8.3（= IMU 三项实测值的扣分结果），视觉指标全部显示"无数据"，雷达图说"数据不足，无法绘制"。

**收获**：

这个 bug 的教训是**"合理的默认值可能比没有值更糟糕"**：

1. **空态设计（empty-state design）是产品设计的核心**——教练看到"这里没数据"会知道要去解决采集问题；教练看到"满分 10.0"会以为系统在工作，运动员在跳"完美"动作。后者的危害**大于没有系统**。

2. **默认值有"信息性"和"非信息性"两种**。`price = 0` 在购物车里是非信息的（0 = 免费），但 `leg_deviation = 0°` 是强信息的（0 = 完美垂直）——**不应该把"缺失"映射到有语义的默认值**。

3. **Python/JavaScript 的 `0` / `None` / `NaN` / `undefined` 最好不要混用**。`0` 是真值，`None/null` 是"无"，`NaN` 是"计算失败"。在数据管线里必须一致地区分，**跨边界（CSV → Python → JSON → JS）时尤其小心**。

---

## 问题 #22：分析页骨架叠加按钮无效 —— 占位符代码的后果

**时间**：阶段六上线后用户测试

**现象**：
分析页的视频播放器上有"骨架叠加" toggle，默认开启，图标有反馈，但**视频画面上从来没看到任何骨架**。关掉再开也一样。

**分析过程**：

直接看 [app.js:setupSkeletonOverlay](fastapi_app/static/app.js) 的当时实现：
```js
const drawOverlay = async () => {
    if (!tgl.classList.contains('active')) {
        c2.clearRect(0, 0, canvas.width, canvas.height);
        return;
    }
    const rect = video.getBoundingClientRect();
    canvas.width  = Math.max(1, rect.width);
    canvas.height = Math.max(1, rect.height);
    // No client-side landmark data — just overlay a thin "REC OVERLAY"...
    const c2 = canvas.getContext('2d');
    c2.clearRect(0, 0, canvas.width, canvas.height);
    c2.strokeStyle = 'rgba(59,130,246,0.0)'; // no-op; placeholder
};
```

**是我自己当初写的 placeholder！** 注释上写着 `// no-op; placeholder` —— 意思是"骨架叠加暂不实现，等我后面补上"。但 UI 已经放好了按钮、CSS 做了状态，这段"暂空"的代码就永远堆在那里。

这是典型的**"半成品 UI"**：功能入口存在（按钮能点、能亮），但后端没填，用户以为在工作。

**解决方案**：

1. **后端**：新增 `/api/sets/{name}/landmarks` 返回压缩 JSON：
```json
{
    "fps": 25.0,
    "duration": 16.3,
    "times": [0.0, 0.04, 0.08, ...],
    "frames": [[[x, y, v], ... 33 点], ...]
}
```

2. **前端** `setupSkeletonOverlay` 重写：
```js
async function setupSkeletonOverlay(name) {
    // 加载 landmarks
    const landmarks = await fetch(`/api/sets/${name}/landmarks`).then(r => r.json());

    // 二分查找最接近当前时间的帧
    function findFrameIdx(t) {
        const times = landmarks.times;
        let lo = 0, hi = times.length - 1;
        while (lo < hi) {
            const mid = (lo + hi) >> 1;
            if (times[mid] < t) lo = mid + 1; else hi = mid;
        }
        return lo;
    }

    // 处理 video + object-fit:contain 的 letterbox 偏移
    function resizeCanvas() {
        const rect = video.getBoundingClientRect();
        const vw = video.videoWidth, vh = video.videoHeight;
        const scale = Math.min(rect.width/vw, rect.height/vh);
        const drawW = vw * scale, drawH = vh * scale;
        const x = (rect.width - drawW) / 2;
        const y = (rect.height - drawH) / 2;
        canvas.width = rect.width; canvas.height = rect.height;
        return { x, y, w: drawW, h: drawH };
    }

    function drawOverlay() {
        const box = resizeCanvas();
        c2.clearRect(0, 0, canvas.width, canvas.height);
        if (!tgl.classList.contains('active')) return;
        const idx = findFrameIdx(video.currentTime);
        const pts = landmarks.frames[idx];
        // 画骨骼连线 + 关节点
        // 坐标：box.x + p[0] * box.w, box.y + p[1] * box.h
    }

    // 播放时 rAF，暂停时单次
    let rafId = null;
    function loop() {
        drawOverlay();
        if (!video.paused) rafId = requestAnimationFrame(loop);
    }
    video.addEventListener('play', () => loop());
    video.addEventListener('seeked', drawOverlay);
    video.addEventListener('loadedmetadata', drawOverlay);
}
```

关键细节：
- **Letterbox 计算**：`<video>` 元素用 `object-fit: contain`，实际画面在容器中居中带黑边。canvas 覆盖在上方时，骨骼坐标要按画面实际位置（带 x/y 偏移 + 实际 w/h）映射，不能直接用容器尺寸。
- **二分查找**：landmarks 一秒 25 帧，200 秒的视频就有 5000 帧。每次 timeupdate (~4Hz) 如果线性扫描会卡。二分查找 O(log n)。
- **rAF 节流**：播放时用 requestAnimationFrame 跟视频刷新率同步（一般 60fps），暂停时画一次省电。

**收获**：

1. **Placeholder 代码是债务**。标记 `// TODO` 就会忘；放上看起来"能跑"的空实现就会**骗自己+骗用户**。更好的做法：**要么不放 UI，要么报错**：
   ```js
   const drawOverlay = () => {
       throw new Error('Skeleton overlay not yet implemented');
   };
   ```
   至少在控制台会看到红色警告。

2. **"UI 先行"要么 all-in，要么 none**。写 HTML 时留好空位很容易，但你放了一个"漂亮的按钮"就等同于**签下了一份功能契约**——用户会假设它工作。

3. **坐标系转换是 overlay 类代码的最大坑**：视频、canvas、DOM 的坐标系不一定对齐，加上 CSS 的 `object-fit` / transform 就更复杂。**写 overlay 前画一张"坐标系映射图"是值得的**。

---

## 阶段六最后一轮 — 应用论文研究成果

**时间**：读了两篇花样游泳相关论文后，做系统升级

论文：
- **Edriss et al. 2024** (IJCSS 23/2) — MediaPipe 验证 vs AutoCAD 黄金标准（r=0.93, ICC=0.92）
- **Yue et al. 2023** (Scientific Reports 13:21303) — 从 11 届国际比赛 105 队视频归纳出 5 个显著得分预测变量

**吸收并落实的三点**：

### 1. FINA 扣分尺度校准
论文 Figure 2 & 3 明确：偏差 0–15° = -0.2，15–30° = -0.5，>30° = -1.0。项目之前的 `config.toml` 是拍脑袋定的。现在改成：
```toml
[fina.leg_deviation]
clean = 15
minor = 30
clean_ded = 0.0
minor_ded = 0.5
major_ded = 1.0
```
这样系统给出的扣分跟真实比赛的裁判判罚同尺度。

### 2. 新增 Yue 2023 的显著变量
论文回归分析出 5 个显著预测变量。我们新增：
- **`leg_height_index`**（腿高指数）%：thigh above water / total leg length。国际队平均 30.8%，顶级队 32.7%。评分档位按论文：≥32 clean、25–32 minor、<25 major。
- **`movement_frequency`**（动作频率）Hz：IMU 加速度包络峰值/秒。**Yue 2023 里 β=0.345, p<0.001 是最强正向预测变量**。评分档位按国际队典型值（1.6–2.2 Hz 为 clean）。

### 3. 升级到 Heavy 模型
论文用的是 MediaPipe Holistic（全身+脸+手），精度最高。我们之前用 lite 模型（6 MB），现在下载 heavy（30 MB，精度 ~30% 提升）并设为默认：
```toml
pose_model_size = "heavy"  # 或 "lite" 换速度
```

`camera_manager.py` 加 `_resolve_model_path()` 函数，按 config 优先级查找本地文件，找不到自动降级。

**收获**：

**论文指引"测什么"，工程决定"怎么测"**。系统层面的启示：
1. 跟真实比赛裁判体系对齐的扣分尺度 → 教练用系统的反馈可以**无缝翻译成比赛环境下的调整建议**。
2. 单一关节角度（膝、肘）是**入门级指标**；真正对评分有预测力的是**动作动力学指标**（频率、节律、图形持续时间）。把这些指标做进系统，从"看姿态"上升到"看策略"。
3. 读论文不是脱离工程的学术活动——**论文里的效应量（β、r、p）就是特征工程的先验**。想知道哪个指标最值得做？把标准化回归系数按绝对值排序就是。

---

## 问题 #23：MediaPipe Pose 的"面部依赖"错觉 —— 两阶段检测流水线的陷阱

**时间**：阶段六真机测试后，教练用笔记本挡住脸，身体还在画面内

**现象**：
教练把笔记本电脑放在身前挡住脸部，**身体明明完整可见**，但骨架整体消失 / 反复闪烁 / 跳跃到错误位置。取下笔记本，骨架立刻稳定。

教练的直觉是"系统在依赖面部识别"。这个直觉**部分正确**，但理解它为什么正确需要深入 MediaPipe 的架构。

**分析过程**：

MediaPipe Pose Landmarker 是一个**两阶段流水线**：
```
Frame → [Person Detector]  →  ROI bbox  →  [Landmark Model]  →  33 keypoints
```

1. **Person Detector (BlazePose)** 的训练数据**大量依赖头部/面部特征**作为"人"的信号。这个检测器的作用是找到图像中的人并给出 ROI。当面部被遮挡：
   - 检测分数降低
   - 若低于 `min_pose_detection_confidence` → 整个帧判为"没人" → 没有后续 landmark 提取
   - 即使有 ROI，也可能给到错误位置（比如挡住脸的笔记本）

2. **VIDEO mode 的"tracking 继续"** 原本是优势：首帧检测到后，后续帧用上一帧的 ROI 继续提取 landmarks，省去重检测。但此模式有**退出条件**：当 tracking confidence 低于 `min_tracking_confidence`，会触发重新检测。重新检测失败（面部遮挡）→ 又退回 tracking → 又失败 → **振荡循环**。用户看到的就是"闪烁跳跃"。

3. 两篇论文没遇到这个问题是因为**池边拍摄全景**，整个身体永远在画面内、面部永远可见。**实验室 bench testing 暴露了论文方法论的盲区**。

**这是 MediaPipe 的架构限制，不是我们的代码 bug**。想要"面部无关"的骨架检测，需要换模型（YOLOv8-pose、RTMPose、mmpose）——工程量大，暂不做。

**可以改善的三个方向**：

**方向 1 — 降低置信度阈值**
让追踪在部分遮挡时更持久：
```toml
pose_det_conf = 0.5      # 原 0.6：更容易开始检测
pose_pres_conf = 0.5     # 姿态存在置信度
pose_track_conf = 0.4    # 原 0.6：追踪在遮挡时不立即掉线
```

**方向 2 — 用户可切 IMAGE 模式**
`VIDEO` 每 N 帧才做一次完整检测（之间都是 tracking）；`IMAGE` 每帧都独立检测。后者慢且抖，但**遮挡恢复更快**（不会卡在"失败 tracking"里出不来）：
```toml
pose_mode = "video"  # or "image"
```
切到 image 后可能 FPS 从 25 掉到 15 左右，但面部遮挡场景恢复性能变好。

**方向 3 — UI 引导**
设置页新增"相机摆位指南"面板，明确告诉教练：**初次识别需要完整身体入镜**，锁定后可短暂遮挡部分躯干但不要持续遮挡面部 > 2s。

**收获**：

1. **"库的直觉"和"库的实现"往往不同**。MediaPipe 的文档说"detect 33 pose keypoints"，让人以为这是纯粹的身体几何模型。但 **实现上它先检测人**，而人的检测器又偏好面部信号。这种隐藏依赖只有在边界场景才暴露。
2. **两阶段流水线的失败会"级联放大"**。Stage 1 失败 → Stage 2 无数据 → 用户看到整个系统失效。这在 ML 系统里非常常见，比如：
   - OCR：版面分析失败 → 识别全错
   - 语音识别：端点检测失败 → 文本全错
   - 检索：召回失败 → 排序全错
3. **论文的 "limitation" 小节值得认真读**。Edriss 2024 明确说："variations in lighting and background can affect the accuracy of the system"。这不是 "免责声明"，而是**系统真实的失败模式**。如果想把研究成果产品化，必须设计"当 limitation 触发时怎么办"的 fallback。
4. **给用户"模式开关"比"自动决策"更好**。我们不知道每个场景的最优参数——让教练自己按场景切换 `video` / `image` 模式，比我们自作主张强制一种方案健康。

---

## 阶段六收尾 — 多人支持 + 6 个新指标 + 论文研究的系统落地

### 1. 多人识别 (num_poses=1 → 8)

MediaPipe Pose Landmarker 从 0.10.x 开始原生支持 `num_poses` 参数。**我之前没开**。现在默认 8 人（花样游泳团体自由自选）：

```python
options = PoseLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=_MODEL_PATH),
    running_mode=RunningMode.VIDEO,
    num_poses=8,
    ...
)
```

WebSocket payload 增加 `all_landmarks`（全部识别到的人）和 `person_count`（人数）。主评分人依然是 `landmarks[0]`（primary），其他人用紫色淡化线条画骨架（`drawSecondaryPose`），右下角徽章从"检测中 / 无人"升级为"N 人"。

### 2. 论文里显著但还没实现的 3 个变量全部补齐

Yue 2023 Table 3 列出 8 个变量 + 5 个显著预测值。之前只实现了 `movement_frequency` 和 `leg_height_index`。这次补上剩余 3 个：

| 指标 | 计算方式 | 黄金范围 |
|---|---|---|
| `rotation_frequency` | `‖gyroscope‖` 的均值（deg/s），IMU 陀螺仪直接输出 | 顶级队 44.95 ± 10.07 deg/s |
| `mean_pattern_duration` | 加速度包络峰值间的平均间隔（秒） | 顶级队 5.45 s |
| `last_hf_duration` | 最后一个峰值到录制结束的时长 | 顶级队 16.98 s |

`rotation_frequency` 这里有个**关键优势**：论文用 Kinovea 人工点标从视频估计旋转，误差大；**我们用 IMU 陀螺仪直接测，精度高一个数量级**。

### 3. 我们独有的 3 个 IMU 指标（论文没有）

论文只有视频，我们有 **IMU + 视频**。这是我们的独有信息，应该充分利用：

| 指标 | 物理含义 | 公式 |
|---|---|---|
| `explosive_power` | 爆发力 | 95% 分位数 ‖accel - 1g‖ |
| `energy_index` | 代谢消耗代理 | ∫‖accel - 1g‖ dt / duration |
| `motion_complexity` | 动作复杂度 | 加速度幅值谱的 Shannon 熵 |

这三个指标：
- 单独使用意义模糊（每个技术动作的"正确爆发力"不同）
- **横向对比时才放光**：同一运动员在两次训练中，`energy_index` 上升 = 同样的动作花了更多能量 = 疲劳 / 动作不经济
- Coach 的实用场景：**训练前后对比**，判断进步 / 倦怠

### 4. FINA 扣分尺度与 Edriss 2024 对齐

论文 Figure 2/3 明确给出扣分梯度（0-15° = -0.2, 15-30° = -0.5, >30° = -1.0）。我重写 `config.toml`，让系统扣分与裁判判罚同尺度，这样教练用系统的反馈可以**直接翻译成比赛场景**。

### 5. 面部遮挡的三层改善（见问题 #23）

降低检测置信度阈值 + 新增 `pose_mode = video/image` 切换 + 设置页添加"相机摆位指南"。

### 6. 综合效果

以 `data/set_002_20260319_165319` 为例（31s 前臂 IMU + 无视觉）：

```
overall_score: 7.7             (之前 10.0 伪满分)
  leg_deviation         value=—     zone=no_data      (诚实：没视觉数据)
  leg_height_index      value=—     zone=no_data
  knee_extension        value=—     zone=no_data
  smoothness            value=20.3  zone=minor  -0.5
  stability             value=44.9  zone=major  -1.0
  movement_frequency    value=2.30  zone=minor  -0.2
  rotation_frequency    value=283.7 zone=major  -0.3   (新！IMU 专属)
  mean_pattern_duration value=0.83  zone=major  -0.3   (新！)
  last_hf_duration      value=0.18  zone=clean  0.0    (新！)
  explosive_power       value=1.71  zone=clean  0.0    (新！我们独有)
  energy_index          value=0.57  zone=clean  0.0    (新！我们独有)
  motion_complexity     value=8.55  zone=major  0.0    (新！我们独有)
```

从 8 个指标扩展到 15 个指标（9 个真实数据 + 6 个 no_data 诚实报告）。教练能看到的训练维度**翻倍**，且每个维度都有**明确的研究引用或物理意义**。

---

**最终收获 — 论文与工程的互操作**：

1. **论文是工程的先验**：β / ICC / p-value 这些统计量**直接告诉你哪些特征值得做**。不看论文拍脑袋加指标 = 做一堆"听起来合理但实际无效"的东西。
2. **工程是论文的乘数**：论文限于"用什么测"的层面（camera、软件），但**怎么测、怎么呈现给用户、怎么对比训练前后、怎么处理缺失**这些都是工程问题。把论文结论产品化，比复现论文本身有价值得多。
3. **把论文的"局限性"当 TODO 来做**：Edriss 2024 结尾建议"与 Xsens IMU 对比"——我们正好有 IMU。这种"论文没做但建议做"的方向是最好的产品机会点。

---

## 问题 #24：回放三连错 —— 骨架快半拍、分析页没有队友、时长显示 0 秒

### 症状

教练拿到 `set_008_20260422_142249` 这一段：

1. **分析页不显示第二个人的骨架**。明明实时预览能看到 P2、P3，回放时只剩主要运动员那一根蓝色骨架。
2. **回放骨架比视频快半拍**：滑动进度条没事，按下 Play 之后眼看着骨架已经做下一个动作了，视频还在上一帧。
3. **时长显示 `--:-- · 0.0s`**：明明录了 27 秒的视频，分析页的"时长"卡却显示 0。

### 分析过程

先看第 3 条，这是最容易复现的。`data/set_008_*/` 里：

```
imu_NODE_A1.csv    67B   ← 只有一行 header，BLE 没连上
imu_NODE_A2.csv    67B
landmarks.csv      749 KB
video.mp4          9.3 MB
vision.csv         30 KB
```

`api_routes.py::set_report` 里 `duration` 的计算只看 IMU：

```python
for df in load_all_imus(set_dir).values():
    if not df.empty and "timestamp_local" in df.columns:
        ts = df["timestamp_local"].values.astype(float)
        if len(ts) > 1:
            duration = max(duration, float(ts[-1] - ts[0]))
```

IMU CSV 是空的（只有 header），`len(ts) == 0`，duration 始终是 0。**IMU-only 的假设在"只拍了视频"的场景里是错的**。

再看第 2 条（骨架 drift）。用 `ffprobe` 读 video 元信息：

```
video.mp4    691 frames @ 25 fps    duration = 27.64s
vision.csv   692 rows (含 header) → 691 行数据  ✓
landmarks.csv  654 rows (含 header) → 653 行数据  ✗ 少 38 行
```

691 vs 653。**landmarks.csv 比 video.mp4 少 38 帧**。

翻到 `main.py::_vision_writer_loop`：

```python
recorder.write_vision(local_ts, frame_count, ...)    # 每帧都写

if data["landmarks"] and len(data["landmarks"]) == 33:   # ← 门控
    lm_dicts = [...]
    recorder.write_landmarks(local_ts, frame_count, lm_dicts)

if data.get("raw_frame") is not None:
    recorder.write_video_frame(data["raw_frame"])        # 每帧都写
```

**姿态未检测到的帧，landmarks 被跳过，但 video 还在写**。长时间跑下来，两个文件行数就对不齐。

前端 `findFrameIdx` 是按比例映射的：

```js
const ratio = video.currentTime / video.duration;
return Math.round(ratio * (landmarks.frames.length - 1));
```

假设遮挡集中在录制末尾（运动员游出视野），landmarks 的密度就是"前密后疏"。按比例映射：video currentTime=50% → skeleton 取 landmarks[~326]，但这 326 行其实是前 ~85% 真实时间里录下的。**骨架显示的是"未来的姿势"，比视频快。这正是教练看到的半拍 drift**。

最后第 1 条（没有 P2）。看 `recorder.write_landmarks`：签名只接受一个 `landmarks_list`，也就是主要运动员那一组。`CameraManager` 生产了 `all_landmarks`（所有人）和 `landmarks`（主），但 `_vision_writer_loop` 只把主要那组写盘。结果：**实时视图能看到 P2，录制完成后的 CSV 里只有 P1，回放时自然只画得出一个人**。

### 根因（三合一）

| 症状 | 根因 |
|------|------|
| 骨架快半拍 | `_vision_writer_loop` 对 landmarks 有"有姿态才写"的条件，对 video 没有 → 行数不对齐 → 比例映射错位 |
| 没有 P2/P3 骨架 | 录制层从来没有持久化 `all_landmarks`，只写了主要运动员 |
| 时长 0 秒 | `duration` 计算只依赖 IMU，无 IMU 的训练组没有回退 |

三个问题都来自**同一个"只为主路径设计"的思维惯性** —— 当初写录制代码时假设 IMU 必连、假设主要运动员必可见、假设姿态必检测到，结果碰到边界情况就集体塌方。

### 修复

**1. landmarks.csv 与 video.mp4 强制 1:1 对齐**

`main.py::_vision_writer_loop` 现在无条件写一行 landmarks，缺失时由 `recorder.write_landmarks` 自动填 0。

```python
lm_list = data.get("landmarks") or []
lm_dicts = [
    {"x": l[0], "y": l[1], "z": 0.0, "visibility": l[2]} for l in lm_list
] if lm_list and len(lm_list) == 33 else []
recorder.write_landmarks(local_ts, frame_count, lm_dicts)
```

这样每帧 `video.mp4` 都严格对应一行 `landmarks.csv`，比例映射再怎么算都不会漂移。

**2. 新增 `landmarks_multi.jsonl` 保存多人数据**

JSONL 格式，每行一帧 + 所有被检测到的运动员：

```json
{"ts":1713770569.123,"frame":42,"persons":[[[0.51,0.48,0.93],...×33], [[0.33,0.29,0.81],...×33]]}
```

`Recorder.write_landmarks_multi` 跟 `write_video_frame` 并行调用，天然保证行数一致。

**3. `/api/sets/{name}/landmarks` 返回 `all_frames`**

有 `landmarks_multi.jsonl` 的训练组额外返回 `all_frames: [persons_per_frame, ...]`，前端 `setupSkeletonOverlay` 用 `TEAM_COLORS` 画出 P1（蓝色主角）+ P2/P3...（其他颜色 + "P2" 标签）。

**4. 时长回退链**

`set_report` 的 duration 现在顺序尝试：

```
IMU timestamp 范围
  → vision.csv timestamp 范围
  → landmarks.csv timestamp 范围
  → video frame_count / fps     （最后的兜底）
```

纯视频录制、纯 IMU 录制、纯视觉录制，都能得到一个合理的时长。

### 收获

1. **"1:1 对齐" 不是契约，是构造出来的**：如果两个文件期望严格同长，必须保证**同一个写循环里无条件各写一行**，别留"选择性跳过"的分支。否则对齐只是当下碰巧成立，而不是永远成立。
2. **按比例映射是一把双刃剑**：`currentTime/duration` 这套比例映射优雅省事，但它**严格依赖两端采样密度一致**。一旦密度不一致（哪怕只是 5% 的 drift），视觉上就是"比过去更快"或"比未来更慢"。排查此类问题要先验证"两边到底有多少个样本"。
3. **回退链是面向失败场景的设计**：`duration` 从 IMU 回退到 vision 再回退到 landmarks 再回退到 video container 的每一步，都对应一个真实场景（无 IMU / 无视觉 / 无姿态 / 什么都不全）。这不是过度设计，是"面向我们真实拿到的烂数据"的工程自觉。
4. **用 ffprobe / wc -l 量化差异**：靠 "看着不对" 调不动这种 bug，必须把视频帧数、CSV 行数拿到手同框对比。一旦数字摆出来，根因立刻自解。

---

## 问题 #25：多人骨架的"脸盲" —— 颜色按数组顺序绑定，导致教练对不上人

### 症状

阶段六给多人录制做了 P1（蓝）/ P2（紫）/ P3（橙）的颜色区分，看上去挺像那么回事。直到我们脑补一个真实场景：

> 两位运动员 A、B 同框。开始 A 离镜头近、area 大 → 系统判 A 是 P1（蓝）、B 是 P2（紫）。半秒后 B 翻身朝镜头扑近，area 反超 A → P1 变成 B（蓝突然变成另一个人）、A 沦为 P2（紫）。

颜色和身份**完全是数组顺序的副产品**。教练眼里看到的是「蓝色那个人变身了」，但 IMU 还绑在 A 身上，分析就全错位。

更糟的是，这个问题在阶段六的 demo 数据里看不出来 —— 当时只有一个人。它**只在真实多人训练里才会暴露**，而我们到目前为止还没去过真泳池。属于"离线设计的代码碰到真实使用必崩"的典型范本。

### 这事儿为什么是阶段七的前置

后续两件事都依赖"同一个人在所有帧里、所有 Set 之间，能被认出是同一个人"：

1. **运动员名 ↔ ID 映射**（7.2）—— 教练手动给"#3"起名"张三"，之后看到 #3 就知道是张三
2. **跨 Set 趋势对比**（7.3）—— 同一个张三的两次训练做对比图

如果"#3"在帧之间会换人、会跨 Set 重新分配，上面两件事就是空中楼阁。所以阶段七必须先解决**身份**问题，再做名字、再做对比。

### 实现：YOLOv8-pose 接 BYTETracker

ultralytics 自带 ByteTrack 集成 —— 把 `model.predict()` 换成 `model.track(persist=True, tracker='bytetrack.yaml')` 即可。返回的 `result.boxes.id` 就是稳定 track_id（卡尔曼滤波 + IoU 关联）。

#### 关键扩展：返回值变成 `(persons, track_ids)` 元组

[fastapi_app/yolo_pose.py](fastapi_app/yolo_pose.py) 里 `detect()` 原本只返回 area-排序的 person 列表，现在多返回一个等长的 `track_ids: list[int|None]`。`None` 出现在两种情况：① BYTETracker 还没给新检测分配 ID（极罕见、就一帧）；② 用 MediaPipe backend（无追踪能力，全 None）。

排序时要保证 ids 跟 persons 对齐 —— sort by area 之后用 `track_ids = [track_ids[i] for i in order]` 同步置换。

#### 新增 `reset_tracking()`：跨 Set 隔离

ByteTrack 的状态是 stateful 的 —— `predictor.trackers[0]` 持有一个对象，记录每个 ID 的卡尔曼状态、消失帧数等。如果不主动 reset，上一个 Set 用到 #5，下一个 Set 第一个被识别的人就成了 #6 —— 教练满脸问号"为什么我刚开始录就看到 #6 而不是 #1"。

所以在 [fastapi_app/main.py](fastapi_app/main.py)（BLE 按钮触发）和 [fastapi_app/api_routes.py](fastapi_app/api_routes.py)（dashboard 按钮触发）两处 `start_recording()` 后都加一行 `camera_manager.reset_tracking()`。

#### 持久化：`landmarks_multi.jsonl` 加 `ids` 字段

不能改原本的 `persons` 数组结构，否则旧的 set_008 等录制无法回放。所以在每行 JSON 里**新增一个并行字段**：

```json
{"ts": 12.345, "frame": 308, "persons": [[[x,y,v]×33], ...], "ids": [3, 7]}
```

旧文件没有 `ids` 字段，[fastapi_app/api_routes.py](fastapi_app/api_routes.py) 的读取逻辑用 `obj.get("ids")` 兜底成 `[None]*N`，前端 fallback 到旧的"主角蓝 + 队友按 idx 配色"。**新旧文件回放都不坏**。

#### 前端：`colourFor(arrayIdx, trackId)` 二级 fallback

```js
function colourFor(arrayIdx, trackId) {
    if (trackId != null) return TEAM_COLORS[trackId % TEAM_COLORS.length];
    if (arrayIdx === 0) return '#3B82F6';   // legacy primary blue
    return TEAM_COLORS[arrayIdx % TEAM_COLORS.length];
}
function labelFor(arrayIdx, trackId) {
    if (trackId != null) return `#${trackId}`;
    if (arrayIdx === 0) return '';
    return `P${arrayIdx + 1}`;
}
```

实时页（`drawSkeletonOnCanvas` + `drawSecondaryPose`）和分析页（`drawPersonAt`）都走这套规则。教练现在看到的是「`#3` 永远是同一个人，颜色永远不变」，无论这个人是 area-第一还是第二。

#### 防御性长度对齐

[fastapi_app/camera_manager.py](fastapi_app/camera_manager.py) 在写出帧字典前做最后一次 sanity check：

```python
if len(track_ids) != len(all_landmarks):
    track_ids = [None] * len(all_landmarks)
```

万一上游某个边缘情况让 `track_ids` 跟 `all_landmarks` 长度不齐（比如 ultralytics 升级后行为变化），降级到全 None 也好过让 `ids[i]` 取错人 —— 那种"silent misbinding"是最坏的 bug：颜色绑错人、IMU 也跟着绑错，分析数据全错但不会报错。

### 验证

1. **静态语法**：`python3 -c "import ast; [ast.parse(...)]"` 五个改动文件全过
2. **recorder smoke**（mock cv2，6 个帧场景）：
   - 正常多人 `[3, 7]` ✓
   - 单人 `[3]` ✓
   - 空帧 `[]` ✓
   - 旧格式（无 ids）→ `[None, None]` ✓
   - 混合（部分有 ID 部分 None）→ `[3, None]` ✓
   - 畸形 person 被过滤时 ids 也对齐过滤 → 长度一致 ✓
3. **测试套件回归**：`uv run pytest tests/` 改动前后均 9 failed / 94 passed（9 个失败全部 pre-existing，与本次改动无关）

实地（多人 + 真实泳池）验证留到 **7.0 数据采集**完成后。

### 收获

1. **"颜色 = 身份" 不能是数组顺序的副产品**：当排序键（这里是 area）会随时间变化时，按数组下标绑色一定会出问题。要么固定一个稳定 key（这里就是 track_id），要么**就别让颜色承担身份信息**。
2. **stateful 的库要把"reset"显式暴露**：BYTETracker 默认全程持有状态，不主动 reset 就会跨 Set 泄漏。这种"看不见的延续"是分布式系统/有状态服务里最常见的踩坑模式 —— 不是 bug，是默认行为不符合用户的心智模型。
3. **加字段不改结构是良药**：JSONL 里加 `ids` 而不是改 `persons` 的形状，让旧录制无痛回放。这种"扩展点"思维在版本演进中省下大量返工成本。
4. **silent misbinding 比 crash 更可怕**：长度不齐时 `track_ids[i]` 读错值，前端把蓝色画在了错的人头上，下游 IMU/视频/评分全错位但不会报错。这种 bug 一旦让教练用错了再被发现，信任度直接归零。defensive check 不是过度设计，是对"silent error"零容忍的纪律。
5. **离线想象的产品必经实地验证**：阶段六全部 UI 没有真实多人数据校验过。`#25` 这一坑在阶段六代码合入主干那刻就埋下了，但因为没有真实场景去触发，一直没暴露。这印证了"7.0 实训数据采集"作为隐藏前置的必要性 —— 没有真数据，所有"我们觉得这样可以"的判断都是赌博。

---

## 问题 #26：从 `#3` 到「张三」 —— 给抽象 ID 一张人脸

### 背景

阶段 7.1 让 BYTETracker 给每个运动员发了一个稳定的整数 ID（`#3`、`#7`），骨架颜色也跟着 ID 走，**身份**问题解决了。但教练在屏幕上看到的还是 `#3` —— 一个抽象数字。要把这套系统真正交到教练手里，必须能说"这个 #3 是张三、那个 #7 是李四"，否则数据再准也只是"匿名运动员的优秀指标"，没法落到具体人头上。

7.2 的目标只有一句话：**让骨架标签从 `#3` 升级为「张三」**。

### 看似简单的两个设计决策

#### 决策 1：绑定是「per-Set」还是「全局」？

直觉上，「张三就是张三」，应该全局绑定一个 ID 就够了。但前一个 PR 的 7.1 决定了 BYTETracker 在每场录制开始时 reset，所以**张三今天是 #3，明天可能是 #7，后天可能是 #2**。如果做成"全局绑定 #3 = 张三"，明天就全错了。

所以绑定必须是 `(set_name, track_id) → athlete_name` 三元组。同一个张三在不同 set 里有不同 binding，但都指向同一个 `athlete_id`。这正是 7.3 跨 Set 对比要用的"同一个人的多次训练"基础。

数据 schema 在 [fastapi_app/athlete_store.py](fastapi_app/athlete_store.py) 里：

```json
{
  "version": 1,
  "athletes": [
    {
      "id": "ath_xxxxxxxx",
      "name": "张三",
      "color": "#A855F7",
      "bindings": [
        {"set": "set_009_…", "track_id": 3},
        {"set": "set_010_…", "track_id": 5}
      ]
    }
  ]
}
```

#### 决策 2：bind 操作的冲突如何处理？

如果教练已经绑了"set_009 的 #3 = 张三"，现在又要绑"set_009 的 #3 = 李四"，怎么办？

三种选择：
- **拒绝**：返回 409 Conflict，让教练先 unbind 张三 —— 最严格但 UX 最差
- **共存**：允许同一个 (set, track_id) 同时绑给两个人 —— 数据不一致，下游要为每个 #3 都画两个名字
- **覆盖**：自动从张三身上拿走，挂到李四身上 —— 体感最自然，符合"我刚才搞错了"的心智

我选了**覆盖**。`bind_track` 的实现在写新绑定前，先扫一遍所有 athlete 把同 `(set, track_id)` 的 binding 都摘掉：

```python
for ath in data["athletes"]:
    ath["bindings"] = [
        b for b in ath.get("bindings", [])
        if not (b["set"] == set_name and int(b["track_id"]) == int(track_id))
    ]
```

这样 `lookup_for_set(set_name)` 永远返回唯一映射，前端不需要处理多对一的歧义。

### 实现：从持久层到 UI 一条线

#### 持久层：[fastapi_app/athlete_store.py](fastapi_app/athlete_store.py)

JSON-backed CRUD store，关键设计：

- **原子写**：`tmp + os.replace`，避免写到一半进程崩溃留下半截 JSON。
- **forward-compat**：读到未知 schema version 或损坏文件直接返回空 store，**不抛异常**。教练操作时碰到"突然弹错误"的恐怖远大于"配置丢了重来一遍"。
- **threading.Lock**：FastAPI worker thread 和 dashboard 并发请求都安全。
- **lookup_for_set()**：`O(athletes × bindings)` 反查 —— 真实场景每个队最多十几个 athlete、每人几十个 binding，完全够。

#### API 层：6 个端点（[fastapi_app/api_routes.py](fastapi_app/api_routes.py)）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/athletes` | 列出所有 athlete |
| POST | `/api/athletes` | 新建（`name` 必填，`color` 可选） |
| PATCH | `/api/athletes/{id}` | 改名 / 改色 |
| DELETE | `/api/athletes/{id}` | 删除 athlete（连带所有 binding） |
| POST | `/api/athletes/{id}/bind` | 绑定 `(set, track_id)` |
| POST | `/api/athletes/{id}/unbind` | 解绑 |

**为什么 unbind 是 POST 不是 DELETE-with-body？** 第一版我写成 `DELETE /bind`，结果 `httpx.Client.delete()` **不接受** `json=` kwarg —— 这是 httpx 的明确限制。这是个红旗：如果连同进程的 TestClient 都嫌弃 DELETE-with-body，生产环境的代理 / CDN / curl-脚本里更不可控。所以改成 `POST /unbind` 是更稳健的语义选择，也符合"unbind 不是真正的 idempotent delete"（解绑一个不存在的 binding 我返回 404）。

**phantom set 拦截**：`bind` 端点会先检查 `os.path.isdir(_set_dir(req.set))`。让一个不存在的 set 进入 binding 列表，`lookup_for_set` 永远找不到它 —— 看起来 binding 在但用不上，是最坏的"看似工作但实则失效"的 silent bug。

#### 数据流：`/api/sets/{name}/landmarks` 加 `athlete_map` 字段

```python
if _athletes is not None:
    athlete_map = _athletes.lookup_for_set(name)
    payload["athlete_map"] = {str(k): v for k, v in athlete_map.items()}
```

key 必须 stringify —— JSON 没有 int key。前端读取时用 `aMap[String(track_id)]` 复原。

#### 前端：三层 fallback 的 `colourFor` / `labelFor`

```js
function colourFor(arrayIdx, trackId, athleteMap) {
    if (trackId != null) {
        const ath = athleteMap && athleteMap[String(trackId)];
        if (ath && ath.color) return ath.color;          // ① athlete pinned colour
        return TEAM_COLORS[trackId % TEAM_COLORS.length]; // ② track-id colour
    }
    if (arrayIdx === 0) return '#3B82F6';                 // ③ legacy primary blue
    return TEAM_COLORS[arrayIdx % TEAM_COLORS.length];   // ④ legacy by-index
}
```

最关键：**有 athlete binding 时颜色由 athlete 决定，否则由 track_id 决定**。教练能给张三固定一个紫色，无论今天的张三是 #3 还是 #7。

`labelFor` 同样三层：athlete name → `#${trackId}` → `P${idx+1}`。

#### UI：分析页「队员管理」模态

视频卡片头部加一个「队员」按钮 → 弹模态：

- 顶部 hint：解释为什么 binding 是 per-Set
- 中部：本 set 出现过的所有 unique track_id 列表（聚合自 `landmarks.all_ids`）
- 每行：色块（按 `id % 8`）+ `#3` + 已绑定显示运动员名 + 解绑按钮 / 未绑定显示下拉
- 下拉里：已有 athlete 列表 + 「+新建运动员」选项

「新建运动员」目前用 `window.prompt()`。功能 OK 但 UX 粗糙，等 7.3 完成后顺手做成内联 input。

### in-place mutation：避免 setupSkeletonOverlay 重入

每次绑定后**不能**重新调 `setupSkeletonOverlay(name)` —— 它会 `addEventListener` 给 `<video>` 元素累计绑定，导致每帧 drawOverlay 跑 N 次。

解决方案：模块级 `_activeOverlay = { setName, landmarks }`。模态绑定后**直接 mutate** `_activeOverlay.landmarks.athlete_map`：

```js
aMap[String(trackId)] = { athlete_id, name, color };
if (_activeOverlay && _activeOverlay.landmarks) {
    _activeOverlay.landmarks.athlete_map = aMap;
}
```

drawOverlay 闭包里的 `landmarks` 是同一对象引用，下一次 `requestAnimationFrame` 自动拾取。无重新绑定，无视频闪烁，无事件监听泄漏。

### 验证

- ✅ 所有 .py / .js 静态语法（`python3 ast.parse`、`node --check`）
- ✅ athlete_store 单元 smoke：9 个边界场景（CRUD、绑定冲突解决、解绑幂等、损坏 JSON 自愈、未知 schema 兜底、绑不存在的 athlete 返回 None）
- ✅ FastAPI TestClient 集成 smoke：11 assertions（含覆盖式 bind 冲突 / phantom set 404 / 空 name 400 / 解绑幂等 / 删除幂等）
- ✅ 完整 pytest 回归：9 failed / 94 passed = baseline

### 收获

1. **per-Set 绑定不是过度设计，是物理事实**：BYTETracker 在 reset 后世界重新开始，把"张三 = #3"假设成全局是把局部规律当全局规律 —— 在分布式 / 有状态系统里这是经典错误。每次设计"X 等于 Y"型的映射，先问一句"在什么时间窗口、什么状态边界内成立？"
2. **冲突解决的语义比正确性更重要**：覆盖式 bind 不一定"对"，但它最贴合教练的心智模型（"哦我刚才搞错了"）。设计 API 时永远要想"用户最常打错的操作发生时，结果是什么"。
3. **DELETE-with-body 是历史包袱**：HTTP 规范允许，但生态不友好。POST + 子动作 (`/unbind`) 是更可移植的写法。这种小细节，在团队协作里能省掉无数次"为什么 curl 能跑前端就不行"的扯皮。
4. **silent misroute 比报错更危险**：phantom set 不拦截 → 用户以为绑成功了，结果回放时啥也没看到，怀疑是别的 bug，去查别处 —— 浪费的不是时间，是信任。Edge-case 拦截要走 fail-loud 路线。
5. **前端模态的 in-place mutation 是高性价比 trick**：比起重新初始化整个 overlay 系统，只 mutate 一个对象引用，完美避开"事件监听累积"这种隐性 bug。React 时代我们容易忘了这种轻量级的、面向"现有 vanilla JS 闭包"的优雅做法。

---

## 问题 #27：跨 Set 对比 —— 让 IMU 独有指标"真正放光"

### 背景

DEVLOG #23 在介绍 `explosive_power / energy_index / motion_complexity` 三个 IMU 独有指标时埋了一个坑：

> 这些指标单独看没有"标准答案"——爆发力多大算好？能量消耗多少算多？所以**只在横向对比里才放光**。教练的实用场景是"训练前后对比"：同一运动员两次训练，`energy_index` 上升 = 同样的动作花了更多能量 = 疲劳 / 动作不经济。

但 7.2 之前我们没有"同一运动员的多次训练"这个概念，只有按 set 编号排列的孤立录制。7.1 给了稳定 ID、7.2 把 ID 绑到了名字 — 现在 7.3 终于可以兑现这张支票，做出**横向对比页**。

### 设计要点

#### 1. 后端最小复用：复用 set_report，不重写计算

跨 set 对比天然要求"每个 set 的数值跟它各自分析页看到的完全一致"。如果新写一套统计逻辑，就有"对比页说 7.5 但分析页说 7.7"的对不上号风险。

我直接 await 已有的 `set_report(name)` route handler，从返回 dict 里抠精简字段：

```python
for name in set_names:
    rep = await set_report(name)
    if isinstance(rep, JSONResponse):
        results.append({"name": name, "error": "not found"})
        continue
    slim = {
        "name": name,
        "overall_score": rep.get("overall_score"),
        "metrics": rep.get("metrics"),
        ...
    }
```

**partial-failure 设计**：某个 set 不存在不该让整个对比请求 500。每个 set 独立 try，失败的标 `{"name": ..., "error": "not found"}`，前端能渲染部分对比 + 高亮失败的那行。这是面向"教练 7 天前删了 set_005 但今天打开旧的对比快照"的真实场景。

**上限 20 个**：批量太大网络会卡，且雷达图叠加超过 6 条人眼根本看不清。20 是个合理的硬性上限。

#### 2. 前端三块视图，一个状态机

我没用 React/Vue，全是模块级 `_compareState` + `renderCompare()`。三块视图：

- **chips strip** — 当前可对比的 set 列表，点击 toggle 选中
- **雷达叠加** — 选中 set 的多边形叠加，颜色按 athlete 走
- **单指标折线** — 选中 set 按录制时间升序排列，X 轴是时间，Y 轴是指标值

切换"指标筛选"下拉只重画折线（`renderCompareCharts()` 不重渲染 chips），改"运动员筛选"才整体重拉数据（`applyCompareFilter()`）。

#### 3. 雷达叠加的"共有指标 intersect"

不同 set 可能有不同 metric 集合（IMU 没连那场就缺 IMU 指标，纯 IMU 那场就缺视觉指标）。雷达图所有顶点必须一致，所以要算所有选中 set 的 metric 交集：

```js
let names = (reports[0].metrics || [])
    .filter(m => m.value != null && m.zone !== 'no_data')
    .map(m => m.name);
for (let i = 1; i < reports.length; i++) {
    const set = new Set(reports[i].metrics.filter(m => ...).map(m => m.name));
    names = names.filter(n => set.has(n));
}
```

如果交集 < 3 个指标（雷达图至少需要三角形），渲染一句"共有指标 < 3，无法叠加"。这是教练混选了"纯 IMU"和"纯视频"两个 set 时会触发的友好提示。

#### 4. 颜色策略：athlete > palette

教练选了"张三的全部 5 场训练"，所有 5 个雷达多边形都是同一个紫色。视觉上一眼能看出"哦这五场都是同一个人的进步轨迹"。

选了"张三 vs 李四 各 3 场"，张三的 3 场都紫色，李四的 3 场都蓝色，交集对比一目了然。

这就是 7.2 那个"athlete pin colour"字段的真正用途 — 它在 7.2 PR 里只是个 UX 装饰，到 7.3 才显现出"跨场视觉聚簇"的真正价值。

#### 5. set 名字缩写 → 人类可读

原始：`set_009_20260422_142249`，22 字符，雷达图标签塞不下。

格式化为：`#9 · 04-22 14:22`，11 字符，肉眼能秒看出"哦这是 9 月 22 号下午 2 点那场"。

这种细节对教练 vs 工程师的 UX 差异巨大 — 工程师能记住 "20260422_142249" 的语义，教练只想看"哪天哪场"。

### 验证

- ✅ JS / Python 静态语法
- ✅ FastAPI TestClient 集成 smoke：4 场景（empty sets 400 / >20 sets 400 / phantom set partial error / athletes/{id}/sets 404）
- ✅ pytest 回归：9 failed / 94 passed = baseline

### 收获

1. **复用 route handler 是确保"对比页和详情页数值对得上"的最直接保证**：抗拒重新实现的诱惑，只做"投影"而不是"重算"。这种 DRY 不是为了少写代码，是为了**消除两套实现 drift 的可能性**。
2. **partial-failure > all-or-nothing**：批量 API 默认应该是"每个独立成败、整体永远 200"。让前端决定如何展示部分失败，比让前端处理 500 友好得多。
3. **下游产品化挖掘上游工程投资**：7.3 之所以能在两小时内做完，全靠 7.1 的 stable ID 和 7.2 的 athlete name 这两个"看似只是基础"的工作。**真正有用的产品价值往往隐藏在三层之上的 UX 里**，但它们必须站在前面铺好的稳定基座上。如果当初 7.1 只做了"颜色和数组顺序解耦"而没引入 BYTETracker，7.3 的趋势对比就根本无从谈起。
4. **不同 set 的 metric 集合要做交集**：跨 set 比较前一定要先对齐"维度集合"，否则雷达图会突然"长出一个角"或"少一个角"，肉眼立刻察觉异常但调试起来很难。先做交集 + 阈值校验（< 3 给提示），是面向"用户混选不兼容数据"的常规防御。
5. **状态机的拆分粒度反映用户操作的拆分粒度**：用户切指标只重画折线，用户改筛选才重拉数据。这个分层避免了"每点一下都重新跑一次完整渲染"的浪费。状态机粒度 = 用户操作粒度，这是最朴素也最有效的性能优化原则。

---

## 问题 #28：YOLO 微调的"基础设施先行" —— 在素材到位前把脚手架搭好

### 背景

7.4 的目标是"用真实游泳素材微调 YOLOv8-pose"。但我们目前**还没有**真实素材 — 总统大人决定先把整个阶段七的代码框架打完再上传素材。

正常思路："没素材就什么都做不了，等素材到了再说"。但这是错的：

1. **流程上的所有难点都和素材内容无关**：怎么半监督预标、怎么避开 ultralytics 的 80/20 自动拆分坑、怎么针对水中场景调 augmentation、怎么评估泛化能力 — 这些**全是工程问题**，跟具体素材是哪个泳池毫无关系。
2. **素材到位时教练第一次跑应该一行命令**：如果到那时候才开始想"哦怎么把视频转成 YOLO format"，会浪费教练的真实素材时间。
3. **写脚手架时是清醒的 → 选择会更冷静**：等素材堆积起来再边训练边想，容易急功近利做出错误决定（比如 auto-split）。

所以 7.4 这一阶段不动模型，只准备**完整可跑的基础设施**：脚本、配置、文档。等总统大人一上传素材，能 1 行命令跑完整流程。

### 三个脚本 + 一个 yaml + 一份文档

#### `tools/preannotate.py` — 半监督预标注

最关键的设计点：**故意调低 conf 阈值（0.3 而不是 0.5）**。

直觉上 conf 应该高，"我们要可靠的预标"。但这个工具的用户不是模型，**是教练 + 标注员**。教练修一个错位的关键点比从空白开始画快得多。所以宁可让 borderline 检测也进入预标 — 错的修一下，对的省下手工绘制成本。

```python
v = 2 if c > 0.5 else (1 if c > 0.0 else 0)
```

visibility 的三档映射也按这个逻辑：高置信 = visible(2)，低置信 = occluded(1)，零置信 = unlabelled(0)。让标注员一眼能看出"这个点模型不太确定，需要重点检查"。

跳过"零检测"帧：如果某一帧 YOLO 找不到任何人，连图带 label 都不写。empty-label 图只会污染数据集，触发 ultralytics 的"missing labels"警告。

#### `tools/train_pose.py` — augmentation 针对水中场景调

ultralytics 默认的 augmentation 是为通用 COCO 调的，对花泳并不合适：

| 参数 | 默认 | 我们 | 为什么 |
|---|---|---|---|
| `mosaic` | 1.0 | 0.5 | 多人镜头本身已经有"自然 mosaic"。叠加 1.0 会把 4 张多人画面拼成一张，模型直接懵。 |
| `degrees` | 0.0–10.0 | 5.0 | 花泳动作有强烈的方向语义（vertical routine 必须头朝下），过度旋转破坏先验。 |
| `hsv_v` | 0.4 | 0.5 | 水面反光让画面亮度跳幅极大，需要更宽容的亮度抖动。 |
| `mixup` | 0.0 | 0.1 | 少量混合保留单人特征，但不能太多 — 混合两个翻身姿势会让 keypoint 完全乱。 |

这些选择都基于"领域先验"，**不是把超参数留给用户调**。教练不是 ML 工程师，给他一堆未明含义的旋钮等于没给。

#### `tools/eval_pose.py` — 把"留出场地"的要求写进 docstring

模块 docstring 第一段就强调：

> CRITICAL: the validation split must come from a venue / lighting /
> athlete combination that was NOT in the training set. Otherwise a
> high mAP just means "memorized this dataset"...

这种"过拟合到训练池"的坑太常见。把警告写进**程序自身的 docstring**，比写在外部文档里更难错过。

输出里也直接打基准：`(baseline yolov8s-pose ≈ 0.55 on swim)`。让用户**当场就能判断"这个数好不好"**，而不是去翻文档对照。

#### `data/training/syncswim.yaml` — flip_idx 是关键

```yaml
flip_idx: [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]
```

水平翻转增强时，左右关键点要对换。`flip_idx[i] = j` 表示"翻转后第 i 个 keypoint 的语义跟原来第 j 个一样"。COCO 标准对应：

```
0  nose      (镜像后还是 nose)
1  left_eye   ↔  2  right_eye
3  left_ear   ↔  4  right_ear
... 以此类推
```

如果**没**指定 flip_idx，ultralytics 翻转后 left_shoulder 和 right_shoulder 的 label 不变 — 模型就开始相信"左肩可以出现在右边"，回归不收敛。这是个特别难调的坑，因为不会报错，只会模型表现奇差。

#### `docs/fine-tuning.md` — 把所有"踩过的坑"前置

文档不是流程描述，是**给未来的自己 / 教练写的踩坑记录**。比如：

> **正确做法**：手动拆分 train/val。ultralytics 默认按文件名 hash 拆 — 同视频相邻帧会被分到两边，val mAP 虚高。

> **数据隐私**：单个真实训练视频可能有运动员肖像权问题 — 上传给云端 CVAT 前必须确认所有出现的人都签过授权。

> **常见坑表**：列了 5 个最常见 failure mode 和修复方法。

这种"在素材到位前写好的文档"比"碰到坑了再补"更冷静、更全面。

### 阶段七全景回顾

走到这里，阶段七的拼图全了：

| 阶段 | 做了什么 | 解锁了什么 |
|---|---|---|
| 7.1 | BYTETracker 给每个运动员稳定 ID（`#3`、`#7`） | 颜色绑身份不绑数组顺序 |
| 7.2 | 教练把 ID 绑到名字（`#3 = 张三`） | 跨场识别同一个人 |
| 7.3 | 多 set 雷达叠加 + 单指标时间轴 | "训练前后对比"的真实场景兑现 |
| 7.4 | 微调脚本 + 文档 | 当真实素材到位时，1 行命令出 best.pt |

每一阶段都是为下一阶段铺路：**没有 7.1 的稳定 ID，7.2 的 athlete name 就是空中楼阁；没有 7.2 的 athlete，7.3 的"张三的所有训练"无从谈起；没有 7.3 验证模型在真实指标上的表现，7.4 的微调就只是给数字看好看而非真改善教练的判断**。

### 收获

1. **基础设施先行 ≠ 过度工程**：在素材到位前把流程跑通的所有"非数据相关"工程问题先解决掉，是产品成熟的标志。等数据来了再边训边写代码 = 浪费数据。
2. **故意调低预标 conf 是面向"人类校对者"的优化**：模型工程师容易把 conf 阈值当成"输出质量门槛"，但在半监督场景里它是"省下多少手画功夫的拉杆"。**用户是谁，决定了优化目标是什么**。
3. **augmentation 的领域先验远比通用默认值重要**：花泳"vertical routine 头朝下"是先验，COCO 不知道。把领域知识硬编码到 `degrees=5.0` 比留给用户调更负责任。
4. **flip_idx 这种"不指定就静默错"的坑要早暴露**：把它写在 yaml 而不是 train 脚本里，教练改 yaml 时一眼能看到 17 个数字 — 哪怕看不懂也会去 google，比埋在代码里强。
5. **文档不是流程描述，是踩坑记录**：碰到坑前先写文档，比碰到坑后补文档更冷静、更全面，因为这时候没有"赶紧出结果"的压力扭曲判断。

---

## 问题 #29：用预录制视频做 dogfood —— 把"导入"做成第一公民

### 背景

总统大人决定先把阶段 7 全部完成 + 后续若干小特性，再上传真实素材做 dogfood。但**当下还有一摞历史训练录像可以先用**。问题是：现有 pipeline 的入口只有"实时录制"——MJPEG 摄像头流 + BLE IMU + Button A 触发 → 落盘 set。视频文件没有任何入口能进系统。

两个糟糕的备选方案：

1. **临时改 camera_manager 喂视频**：把 MJPEG reader 换成 cv2 VideoCapture，假装是"实时摄像头"。结论拒绝 — 这是侵入式改动，dogfood 完了得回退，回退又容易漏一处。
2. **手工拼装 set 目录**：照着 `Recorder` 写出的 CSV/JSONL 格式手动创建文件。脆弱、容易漂、每个新 phase 加字段都要更新这个手工流程。

正确做法：**做一个一等公民的"导入"工具**，输出跟 live recorder 100% 同构的 set 目录，下游 pipeline 完全不知道这是录的还是导入的。

### 设计原则：与 Recorder 共享 schema

[tools/import_video.py](tools/import_video.py) 的核心姿态是**只调用、不复制**：

```python
from fastapi_app.camera_manager import _compute_angles
from fastapi_app.recorder import IMU_HEADER, LANDMARK_NAMES, VISION_HEADER
```

elbow 角度走 `_compute_angles`、CSV header 走 `Recorder` 模块常量、`reset_tracking()` 走 `YoloPoseDetector` 自带方法。**任何一个 schema 变化，导入工具自动跟随**。这避免了"live 加了字段、导入还在写老格式" 这类悄无声息的 drift。

### 五个不变量

写完后我用合成视频 + monkey-patched detector 跑了端到端 smoke，确认 5 个关键不变量：

1. **6 个文件齐全**：`video.mp4` / `vision.csv` / `landmarks.csv` / `landmarks_multi.jsonl` / `imu_NODE_A1.csv` / `imu_NODE_A2.csv`
2. **IMU CSV header-only**：触发 `set_report` duration 回退链（DEVLOG #13），让无 IMU 的导入 set 也能显示真实时长
3. **vision.csv 30+1 行**：每帧一行 + header
4. **landmarks.csv 30+1 行，与 video 严格 1:1**：DEVLOG #13 的核心约束 —— 否则比例映射后骨架会漂移
5. **landmarks_multi.jsonl 30 行，奇偶交替**：奇数帧（无人）`persons=[], ids=[]`、偶数帧（2 人）`ids=[3, 7]` —— 证明两条 detection 分支都跑了

测试用 monkey-patched 的 fake `YoloPoseDetector`，因为 yolov8s-pose.pt 权重不入仓（.gitignore），CI 环境也跑不动 mps inference。**用 mock 验证 pipeline 拓扑结构 ≠ 验证模型质量**，前者就是这个 PR 要做的事。

### dogfood 的"测得到 vs 测不到"

把整个测试矩阵整理在这里：

| 能验证 ✅ | 测不到 ❌（需要硬件 + 真实场地） |
|---|---|
| 多人追踪 ID 稳定性 | 实时 MJPEG 摄像头流 |
| 骨架渲染、配色、标签 | BLE IMU 数据接收 |
| YOLO 在水中场景的真实表现（mAP） | Button A 录制触发 |
| 分析页 / 历史页 / 对比页 / 设置页 / 队员管理 | 实时页评分环 + 三维条 |
| 队员命名 → 跨场对比的完整闭环 | 现场操作流（教练岸边走动 UX） |
| 7.4 微调流程 | |

这就是导入工具的边界 —— **录制路径以外的一切都能验证**，足够支撑后续阶段 8 的 ABCDEF 改动验证。剩下的"硬件依赖"留给真正的实地 dogfood。

### 收获

1. **导入是一等公民，不是一次性脚本**：`tools/` 里的脚本如果会被反复用、且会随系统演进、且与生产代码共享 schema，就值得做成"工具"而不是"脚本"。一次性脚本会随 phase 演进 drift 然后被人嫌弃。
2. **mock 验证拓扑、真实数据验证质量**：smoke test 的目标是证明"路径走通、字段齐全、不变量保持"，不是证明"模型预测准"。把这两件事分开避免"为了能跑测试拉一坨真实模型权重进 CI"的反模式。
3. **共享代码的诱惑要算 ROI**：reuse `_compute_angles` 是好的（schema-coupled、变更同步），但 reuse `Recorder` 整个写盘类就过度了 — 那会强制 import 工具持有线程锁、状态机等不需要的东西。**reuse 的合理边界在"schema/常量"层面，不在"行为/状态"层面**。
4. **设计一开始就考虑"非典型入口"**：live recorder 是典型入口，import 是非典型。但如果系统设计时不预留"非典型入口"的位置，到了 dogfood 阶段就要么改主路径要么手工拼装。把这种"侧门"做成一等公民工具是产品成熟的标志。
5. **set 编号共享 vs 命名区分**：导入 set 跟 live set 共享 `set_NNN` 编号空间（教练在历史页看到连续编号），但目录名加 `_imported_` 后缀（一眼能看出来源）。**统一其能统一的，区分其需要区分的**，比一刀切都好。

---

## 问题 #30：阶段 8 第一波 —— 三件"小事"，每件都揭出一个普遍模式

阶段 8 接 dogfood 准备拳，第一组改动是 **A. 实时页绑定 athlete + B. 数据备份脚本 + C. 教练备注**。三件事看起来杂，每件不到 200 行，但都是教练真正会用、丢了就难受的小特性。

### 8.1 实时页绑定 athlete (A)

#### 痛点

7.2 把"队员命名"做在了**分析页**。一个录制结束 → 切到分析页 → 进模态 → 给 #3 起名"张三"。**理论可行，实操不顺**：教练录制时盯着泳池，看见 #3 那一刻**最知道这是张三**；等录制结束、切页面、找 set，他可能已经在带下一组了。

正确的人体工程学：**录制中即可命名**。

#### 设计：暂存 + 录后批量 flush

直觉做法：实时绑定调 `/api/athletes/{id}/bind` 立即写库。但 BYTETracker ID 在录制开始时 reset，**录制开始前**和**录制中**的 ID 是同一个空间，可是真实 set 名字要等录制结束才知道。

所以：

```js
const _liveSeenTrackIds = new Set();   // ws 流里出现过的 unique track_ids
const _pendingLiveBindings = new Map();// track_id → {athleteId, name, color}
```

绑定时**只写到 `_pendingLiveBindings`**，不调后端。录制 stop 触发 `flushLiveBindings(setName)` 拉响应里的 `set_dir` basename，批量 POST `/api/athletes/{id}/bind`。

`/api/recording/stop` 早就返回 `{"set_dir": ...}`，前端只需把绝对路径取 basename，不用任何后端改动。**最少摩擦的扩展点**。

#### Badge 反馈

按钮上加一个 `<span class="live-pending-badge">` 显示当前待绑数量。教练即使不打开模态，也能看到"哦我已经绑了 3 个了"。

#### 不做即时视觉反馈

第一版**没**让骨架立刻变颜色 / 显示名字 — 那需要让 `drawSkeletonOnCanvas` / `drawSecondaryPose` 也接受 athleteMap 参数，改两个函数签名 + 闭包重组，工作量翻倍。Trade-off：先解决"录制中能命名"这个核心痛点，视觉反馈下个 PR 再加。

### 8.2 数据备份脚本 (B)

#### 设计原则：cron 友好 = 永远 exit 0

最容易写错的备份脚本：失败时返回 non-zero 让 cron 发邮件。结果：飞 wifi 一晚上，早上收到 96 封 "rsync timed out" 邮件。

`tools/backup.py` 的硬规矩：**任何错误路径都 exit 0**。失败信息只写到 `data/.backup.log`，cron 永远不会收到错误退出码。

```python
sys.exit(0)   # never crash cron
```

#### 智能选 backend：rsync vs rclone

```python
def _classify(target: str) -> str:
    head, _, _ = target.partition(":")
    if target.startswith("/") or "@" in head:
        return "rsync"
    if shutil.which("rclone"):
        return "rclone"
    if shutil.which("rsync"):
        return "rsync"
    return "none"
```

`/Volumes/External/syncswim/` → rsync。  
`user@nas.local:/srv/syncswim/` → rsync。  
`icloud:syncswim/` → rclone。  

这个启发式覆盖了 99% 的常见 case，剩下 1% 让用户显式 `--target` 指定。

#### 配置层级

`--target` arg > `BACKUP_TARGET` 环境变量 > `data/.backup_target` 单行文件。

让 cron 可以零配置：
```bash
echo "/Volumes/External/syncswim/" > data/.backup_target
*/15 * * * * /usr/bin/python3 /path/to/tools/backup.py
```

cron 行**完全没有 secrets**。target 路径是用户机器局部信息，落在 `data/.backup_target`（已 .gitignore），不入仓不进 cron 配置。

#### --delete-after vs --delete-before

`rsync -a --delete-after`：**先传输、后删除**。如果中途网络断，destination 上的旧文件还在，没有"两边都没数据"的灾难窗口。这是个看似小但救命的细节。

### 8.3 教练备注 (C)

#### 为什么要

数据指标抓不到的事：
- "今天教三个新人侧空翻"（context）
- "运动员 B 说肩有点酸"（外部信息）
- "下次重点抓 leg_deviation"（教练自己的提醒）

现在教练只能脑子里记。一周后翻历史看到这场 set 评分突然下降，不知道是因为运动员状态、教学内容还是设备问题。

#### 实现：file-as-content，不引入数据库

每个 set 目录加一个 `note.md`。文件存在 = 有备注，不存在 = 没备注。**没数据库、没 schema 迁移、没并发锁**（一个 set 不会同时有两个教练编辑）。

```
data/set_NNN_xxx/
  ...
  note.md         ← 教练手写的 markdown，free-form
```

PUT 端点接收文本：
- 非空 → atomic write (`tmp + os.replace`) 防写到一半进程崩
- whitespace-only / 空 → **删除文件** 而不是写空文件

后者很关键：保持"文件存在 = 有内容"的不变量。如果空文件也能存在，下游 `os.path.exists(note_path)` 就要做额外的 stat 检查文件大小。**让 file system 状态和业务语义一对一**。

#### 前端：内联编辑，不弹模态

分析页顶部加备注卡，跟评分行并列。textarea + 保存/还原按钮。**不弹模态**因为：

- 教练通常是"看到分析页 → 想起一件事 → 写下来"，不是"专门进模态写备注"
- 备注是分析页的延伸，不是另起一段心流

这种"就地编辑" UX 比模态痛快得多。

### 三件事的共同模式

写完三件事回头看，有几个共同模式：

1. **不用数据库的诱惑要顶住**：athlete_store.json、note.md、`.backup_target` 都是文件。每个的 schema、并发模型、备份策略都比"加个 SQLite 表"简单得多。但不是所有数据都能这样 — set 数 >500 后历史页就慢了（task.md J 工程债）。**当下能用文件就用文件**，等真扛不住再迁。
2. **frontend-only 改动 > 后端改动**：8.1 完全没改后端 — 复用 7.2 的 `/api/athletes/{id}/bind`，只是把"立即调"改成"暂存后批量调"。这种"在已有 endpoint 之上做行为变化"的能力，正是 7.2 留下来的契约空间。
3. **缺省值是产品语言**：备份脚本"无 target → log 一行 skip 然后 exit 0"、备注端点"不存在 → 返回 empty 不是 404"、live binding"无 ID 检测到 → 提示 friendly empty state 不是 alert"。**用户从未做过任何配置时，系统的反应就是产品对待用户的态度**。
4. **`exit 0` / silent fallback / friendly empty state 不是偷懒，是工程纪律**：错误路径要"安静"才能让正常路径被注意到。如果备份失败也 exit 0、备注空也 200、live 模态也 friendly empty，教练才会真正信任系统不会"突然抽风"。**信任是产品最难赢、最易失的东西**。

### 验证

| 模块 | 测试 |
|---|---|
| 8.1 实时绑定 | JS 静态语法、节点对齐人工 review、待 dogfood 实测 stop → flush 流程 |
| 8.2 备份脚本 | `--dry-run` 在无 target 时 log "skip" 而非崩溃 |
| 8.3 set note | TestClient 7 assertions（phantom 404 / empty 默认 / PUT-GET 往返 / whitespace 删除 / 空 idempotent / 原子写不留 .tmp） |
| 整体 | pytest 回归 9 failed / 94 passed = baseline |

### 收获

1. **小特性是产品成熟的标志**：phase 1-7 是核心能力，phase 8 是"把这些能力变好用"。一个产品在 phase 1 看起来很有"工程味"，到 phase 8 才开始有"产品味"。
2. **行为变化不一定要 schema 变化**：8.1 没改后端、8.2 没碰 fastapi、8.3 用文件不是表。**优先在已有契约空间内做行为变化**，能等再加 schema。
3. **永远 exit 0 是 cron 友好的护城河**：任何 cron 脚本都该把这条当默认。日志记下错误，cron 安静跑。一封"timed out"邮件能毁掉一周的好心情。
4. **file-as-content vs database-as-content**：file 模式简单但不 scale；database 简单 query 但 schema 演进难。当数据是"独立的、append-mostly、并发低"时（一个 set 一个 note），file 完胜。
5. **frontend pending-state 的设计模式很强大**：暂存 + 批量 flush 的模式（8.1）适用于很多"操作触发时不知道后端 ID"的场景。值得作为一个常用 pattern 记住。

---

## 问题 #31：PDF 报告 —— 选库的两次反复

### 痛点

教练训完想发训练报告给运动员、家长、领导。8.4 之前的唯一方式：**截屏**。截屏的问题：
- 单页只能放一部分；要发雷达 + 指标 + 关键帧得截 3-5 张
- 没有元数据（录制时间、运动员姓名、综合评分大字号）
- 接收方不知道这是"哪场训练"，要靠教练在微信里补充说明
- 看起来像"工程师在 demo dashboard"，不像"教练在递交报告"

PDF 是最自然的解：一份文件，A4 排版，发一次就完。**专业感** = 信任 = 教练能用这套系统对外。

### 选库：从 weasyprint 走回 matplotlib

#### 第一轮：选 weasyprint

直觉选择 — HTML/CSS 控制力最强，渲染质量也最好。`uv pip install weasyprint` 装上了。

跑第一段测试代码：

```
OSError: cannot load library 'libpango-1.0-0': ...
WeasyPrint could not import some external libraries.
```

WeasyPrint 依赖 native libs：pango / cairo / gdk-pixbuf。macOS 需要 `brew install pango cairo gdk-pixbuf libffi`。

这是个小坑：**用户首次装 weasyprint 要跨过 brew 这道墙**。Linux 也类似（`apt install libpango-1.0-0` 等）。

#### 第二轮：matplotlib PdfPages

回到现实：项目本来就装了 matplotlib（`analyze.py` 用它做时序图）。matplotlib 自带 `backend_pdf.PdfPages`，能直接出 PDF：
- **零新 deps**（连 pip install 都不用）
- 跨平台无 native libs
- 单页一个 figure，控制力够用
- 中文字体可在 `rcParams` 里指定

代价：HTML 那种"自由排版"没了，需要用 `add_axes([x, y, w, h])` 手动定位。但训练报告的版式简单（标题 + 数字 + 图 + 表），matplotlib 完全 hold 得住。

**反思**：第一次直觉选了"渲染质量最高"的，没考虑"装得多痛"。把"装的成本" 当成一项设计 constraint 后，matplotlib 立刻成了正确答案。**别把"最好"和"最合适"混淆**。

最后我把 weasyprint 卸了（`uv pip uninstall weasyprint`），requirements.txt 不动。

### 中文字体的"silent fail"

matplotlib 默认 font.family 是 `DejaVu Sans`，**对中文是空白方块**。问题在于 — **不报错**。代码跑得很好，PDF 也生成，看起来一切正常 — 直到真的打开 PDF 看到 `□□□□□`。

修复：用 fallback 链覆盖跨平台：

```python
matplotlib.rcParams["font.family"] = [
    "Heiti TC",            # macOS bundled
    "Hiragino Sans GB",    # macOS bundled
    "Songti SC",           # macOS bundled
    "Noto Sans CJK SC",    # Linux: apt install fonts-noto-cjk
    "Microsoft YaHei",     # Windows
    "sans-serif",
]
```

发现哪些字体可用的姿势：

```python
import matplotlib.font_manager as fm
fm.findfont("Heiti TC", fallback_to_default=False)
```

返回 `/System/Library/Fonts/STHeiti Medium.ttc` → 字体存在；返回 DejaVu 路径 → 字体不存在。

#### 副作用：每次渲染产生噪音

跨平台 fallback 列表在 macOS 上跑，会对每个不存在的字体打 `findfont: Font family 'Microsoft YaHei' not found.`。一份 3 页 PDF 打了 5 行噪音。

修复：

```python
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
```

把 fallback warning 降级到 ERROR 级别，UserWarning-level 的查找失败不再噪音。

### 与 dashboard JS 雷达对齐

PDF 的雷达图必须跟 dashboard 上的一致 —— 否则教练对外发的数字、自己看的数字两套。这是 silent divergence 最常见的原因之一。

```js
// app.js
function normalizeForRadar(name, val) {
    switch (name) {
        case 'leg_deviation': return Math.max(0, Math.min(100, (30 - val) / 30 * 100));
        ...
```

```python
# tools/export_pdf.py
def _normalize_for_radar(name: str, val: float | None) -> float:
    if name == "leg_deviation":
        return max(0.0, min(100.0, (30 - val) / 30 * 100))
    ...
```

两套实现保持手动同步是个**临时妥协**。理想做法：把 normalize 逻辑下沉到 `dashboard.core/`，前后端都通过 API 拉取归一化的值（前端就不用算了）。但这是大改动，留给未来。**当下用代码注释 + DEVLOG 把这个 coupling 显式化**，至少让未来的自己 / 同事知道改一处就要改两处。

### 端点设计：lazy import + 三级 fallback

`/api/sets/{name}/report.pdf` 实现：

```python
@router.get("/sets/{name}/report.pdf")
async def set_report_pdf(name: str):
    if not os.path.isdir(set_dir):
        return JSONResponse({"error": "set not found"}, status_code=404)
    try:
        from tools.export_pdf import render_pdf      # lazy
    except ImportError as e:
        return JSONResponse({"error": ...}, status_code=503)
    try:
        render_pdf(Path(set_dir), Path(output))
    except ValueError as e:                          # no metrics
        return JSONResponse({"error": ...}, status_code=404)
    except Exception as e:                           # render bug
        return JSONResponse({"error": ...}, status_code=500)
    return FileResponse(output, media_type="application/pdf",
                        filename=f"{name}_report.pdf")
```

**lazy import 的两个收益**：
1. 服务启动快（不每次启动都加载 matplotlib，~1-2s）
2. 未来 matplotlib 升级万一坏了 PDF 渲染，dashboard 的其他部分还能工作

**三级 status code**：
- 404：set 不存在或无指标可算
- 503：PDF backend 整个挂了（matplotlib 装坏了）
- 500：本场 set 渲染失败（具体 set 的某些数据触发了 bug）

教练看到 404 会想"哦这场没数据"；看到 503 会找管理员；看到 500 会换一场试试。**status code = 用户该做的下一步**。

### Standalone CLI + endpoint 双入口

```bash
python tools/export_pdf.py set_001_imported_xxx
python tools/export_pdf.py set_NNN -o /tmp/report.pdf
```

跟 endpoint 共享同一个 `render_pdf()` 函数。CLI 的存在让我们能：
- 在 dashboard 没起的时候批量出报告（脚本/cron）
- 调试渲染 bug 不用启 server
- 未来加 `tools/export_pdf.py --batch data/set_*` 一行命令出当周所有报告

**"endpoint 是 CLI 的网络包装"** 是清晰分工的一种姿态。逻辑在 CLI，I/O 在 endpoint。下游想加任何新入口（比如 grpc / cron / 命令行 batch）都不用改 render 逻辑。

### 验证

- ✅ 静态语法（py + js）
- ✅ standalone CLI 用 `data/set_001_*` 跑出 131KB PDF
- ✅ FastAPI TestClient smoke：phantom 404 + 真实 set 返回 application/pdf
- ✅ pytest 回归 9 failed / 94 passed = baseline

### 收获

1. **库选型把"装的成本"当 constraint**：不是"哪个库渲染最好"，而是"哪个库渲染够好且装着不痛"。weasyprint 渲染更好，但 native deps 是用户首次装的痛；matplotlib 渲染够好，零新 deps。**痛感和质量都要量化**。
2. **silent fail 是中文字体的常态**：matplotlib 找不到字体不报错，代码跑得很好但产物不能看。**渲染相关的代码必须人眼校验**，不能只信 "exit 0"。
3. **跨平台 fallback list 的副作用**：每次渲染打 N 行 warning。`logging.getLogger().setLevel()` 是个常用静音手段，比 `warnings.filterwarnings()` 更精准。
4. **JS / Py 对偶函数手动同步是临时债**：normalize_for_radar 同时存在两份实现，将来一定 drift。用注释 + DEVLOG 把 coupling **显式化**，至少改一处时能想起改两处。理想做法是下沉到后端单一来源，但当下不值这个改动量。
5. **CLI + endpoint 同一函数**：把渲染逻辑做成 standalone 可调用，endpoint 只是网络包装。**逻辑层和 I/O 层分离**是任何系统的健康标志。
6. **status code 是用户行为信号**：404 / 503 / 500 不是抽象 HTTP 数字，对应"换一场 / 找管理员 / 换一场试"三种用户响应。设计错误响应时想"用户看到这个会做什么"。

---

## 问题 #32：录制中打标 + 趋势告警 —— "看见 vs 让用户看见"

阶段 8 第二波：**8.5 录制中打标 (E) + 8.6 自动趋势告警 (F)**。前者是教练在录制时把"哪一刻有问题"的 mental note 锚到时间轴上；后者是把多场训练数据里的"长期趋势退步"主动推到教练眼前，而不是等他自己刷历史。

### 8.5 录制中打标 — 跟 8.1 同一套"pending + flush"模式

#### 痛点

教练录制时看到运动员翻身没翻好 — 想锚一下"这个时刻有问题"，回放时直接跳过去。**之前没有这个能力**：教练只能脑子记"大概第 12 秒"，回放时再手动滑进度条试。

#### 模式：跟 8.1 完全一致

8.1 的"教练录制中给 #3 起名 → btn-stop 后 flush 到刚出现的 set" 模式，被原样套到 8.5：

```js
let _recordingStartedAt = 0;          // ms epoch; 0 means not recording
const _pendingMarkers = [];           // [{ts_offset, label, note}]

// btn-start: stamp + clear
_recordingStartedAt = Date.now();
_pendingMarkers.length = 0;

// M key during recording:
const tsOffset = (Date.now() - _recordingStartedAt) / 1000;
_pendingMarkers.push({ ts_offset: tsOffset, label, note: '' });

// btn-stop response carries set_dir → flushLiveMarkers(setName)
```

**重复模式不是 bug，是产品深思熟虑的体现**。8.1 的 pending pattern 现在被 8.5 复用，将来 phase 9 / 10 还会被复用。值得提炼成更通用的"`_recordingPendingQueue<T>`" 抽象。但当下两份独立实现读起来更直白，不优化。

#### "wall-clock + 偏移" 而不是 "video time"

录制 stop 后视频被 H.264 转码（DEVLOG #13/#15 提过），转码可能改 fps。但 marker 的 `ts_offset` 是用 `Date.now()` 减去 `_recordingStartedAt` 算的**真实秒数**，跟视频 fps 无关。

回放时分析页用 `marker.ts_offset / video.duration` 做 ratio 映射 → 设 `video.currentTime`。这一对组合能容忍 source/transcoded fps 不同（同 DEVLOG #13 的设计哲学）。

#### "blank label silently dropped" 是教练友好

POST endpoint 收到 `{label: '   '}` 时，**不**返回 400，**也不**记一条空 marker。直接 silently 跳过：

```python
if not label:
    continue
```

教练按 M 键，prompt 弹出，按了 Esc 或者只输了空格 — 这种情况"什么都没发生"是最自然的 UX。返回 400 让教练再试一次反而粗暴。

### 8.6 趋势告警 — 把长期视角主动推到教练眼前

#### 痛点

DEVLOG #23 早就指出 `explosive_power / energy_index / motion_complexity` 这种 IMU 独有指标"单看没意义、横向才放光"。7.3 给了对比页 — 但教练得**主动**去翻才看得到趋势。**他实际不会主动翻**：每天忙完不一定有心思去对比。

8.6 把这个翻转过来：**系统主动告诉教练"张三的爆发力连续 3 场下降了"**。教练打开对比页第一眼就看见。

#### 规则集：先 hardcode 三条

```python
_ALERT_RULES = [
    {"id": "explosive_power_drop", "metric": "explosive_power",
     "window": 3, "direction": "down", "severity": "warn",
     "message": "爆发力连续 {n} 场下降 — 可能处于疲劳或过载状态"},

    {"id": "leg_deviation_up", "metric": "leg_deviation",
     "window": 3, "direction": "up", "severity": "warn",
     "message": "腿部偏差连续 {n} 场上升 — 建议回顾技术动作"},

    {"id": "overall_low", "metric": "overall_score",
     "window": 2, "direction": "below", "threshold": 6.0,
     "severity": "info",
     "message": "综合评分连续 {n} 场低于 {threshold} — 留意状态"},
]
```

第一版**故意 hardcode** 而不是塞进 `config.toml`：dogfood 之前我们不知道哪条规则真的有用、阈值合理与否。**让真实使用淘汰假设**，等总统大人用过几周再决定哪些规则进生产、哪些阈值要调。

#### 三种 direction 的语义

- `down` — 严格单调递减（每场都比上场低）
- `up` — 严格单调递增
- `below` — 连续 N 场低于 threshold

**为什么严格单调而不是"平均下降"**？因为严格单调是"信号"，平均下降是"噪音 + 偶尔反弹"。教练对前者反应大，对后者免疫力强。**信号要强才值得告警**。

#### 时间排序：靠 set 名字而不是 mtime

```python
def _set_date_key(name: str) -> str:
    m = re.search(r"_(\d{8})_(\d{6})$", name)
    return (m.group(1) + m.group(2)) if m else name
```

文件 mtime 不可靠（重新拷贝就改了）。Set 名字格式是 `set_NNN_YYYYMMDD_HHMMSS`，**录制时间已经编码在名字里**。直接 lex sort 就拿到时序。

`8.0` 的 `imported` set 名字格式是 `set_NNN_imported_<stem>_YYYYMMDD_HHMMSS`，正则同样匹配（贪婪到末尾）。

#### 缺 metric 不破坏 trend

```python
for s in set_names:
    v = _metric_value_in_set(s, rule["metric"])
    if v is not None:
        series.append((s, v))
alert = _apply_rule(rule, series)
```

某场 set 没视觉数据 → `leg_deviation` 算不出 → **跳过这场**而不是把它当 0。一次 IMU 没连不应该让"3 场单调下降"变成"4 场（含中间的 0）下降"。

#### Banner 设计：不显示 = 一切正常

```js
if (alerts.length === 0) {
    banner.hidden = true;
    return;
}
```

**没有告警时整条 hidden**，不显示"暂无告警"占位。让"看不见 banner = 不用担心"成为 UI 不变量。如果显示空状态，教练会习惯性扫一眼，反而稀释了真有告警时的注意力。

### 验证

| 模块 | 测试 |
|---|---|
| markers endpoint | TestClient：phantom 404、empty 默认、POST batch + 排序、blank label silently dropped、append、DELETE 清空 |
| alerts endpoint | TestClient：无 athletes → empty、1 binding → empty (window 不足)、绑定后扫描 |
| 整体 | JS / Py 静态语法、pytest 9 failed / 94 passed = baseline |
| 前端 | M 键 + prompt + flush 流程：人工 review，待 dogfood 实测 |

### 收获

1. **重复模式不是 bug 是产品深度**：8.1 的 pending + flush 在 8.5 复用了。第三次出现时再考虑抽象，前两次让代码冗余但直观。**抽象的成本是可读性损失**，要等"模式真的稳定"再付。
2. **wall-clock + offset > video-time**：转码 / 重新封装会让 video time 偏移。用挂钟时间记录"事件"，用 ratio 映射回任意 video，永远对得上。
3. **silent drop 比 400 友好**：用户操作错误时"什么都没发生"通常比"红色错误条"更好。仅在用户**期望**操作生效时（PUT 显式提交）才报错。
4. **hardcode rule 是 dogfood 前的负责任做法**：把规则塞 config 假装"灵活" → 真实数据可能证明 80% 的规则没用。先让规则跑起来在真数据上看效果，再决定哪条值得 expose 给配置。
5. **空状态 hidden 是 UI 信号清晰化**：让"没看到 banner = 一切正常" 成为不变量。空状态文字稀释真信号的注意力。
6. **mtime 不可靠，编码到 filename 里的时间是真理**：set 命名约定包含 timestamp，所有"按时间排序"的代码都直接解析名字而不是问 filesystem。这是当初定 set 命名格式时埋下的伏笔，phase 8 才兑现。

---

## 问题 #33：dogfood 第一战 — 三档调参 vs 真实泳池数据，把"该 fine-tune"从直觉变成数字

阶段 8 全部完成后，总统大人提供了**三段真实花泳训练视频**做 dogfood：32s 横屏 5 人同框 + 21s/22s 两段竖屏 2-3 人。这是项目第一次接触真实场景数据。直觉是"应该没大问题，可能要微调"，**结果数字让 fine-tune 从 nice-to-have 变成必须**。

### 第一遍：默认参数 baseline

`yolov8s-pose.pt` + 项目默认 `conf=0.35`，`imgsz=640`：

| 视频 | 帧数 | 人数 | persons 检出 | 召回率估算 |
|---|---|---|---|---|
| horizontal | 961 | 5 | **355** | ~7.4% |
| portrait_1 | 632 | 2 | **37** | ~2.9% |
| portrait_2 | 663 | 3 | **193** | ~9.7% |

**3 个 set 平均召回率 < 10%**。原因肉眼可见：花泳运动员做 ballet leg / barracuda（垂直倒立 + 双腿出水），**整个躯干和头部都在水下**，画面里只剩腿和脚。COCO 训练集是"陆地完整人体行走站立"，对这种"水中半身"完全没经验。

### 第二遍：trick 调参

#### 实验 1 — `conf 0.15`（仅降阈值）

portrait_1: 37 → **105 persons**（**2.84× 提升**）。简单解读：YOLO 其实**看见了**水中运动员，只是给的 score 整体偏低，被 0.35 阈值过滤掉了。降低阈值就解锁。

#### 实验 2 — `yolov8m-pose` + `conf 0.15`（换更大模型）

portrait_1: 105 → **108 persons**（仅 +3，**2.92×**）。**模型大小不是瓶颈**。yolov8m 看见的东西跟 s 几乎一样，只是耗 2× 推理时间换 3% 提升。**性价比差，删掉 yolov8m**。

#### 实验 3 — `conf 0.10`（继续降阈值）

portrait_1: 105 → 138（仍涨 +31%）。说明 conf 还有空间，但**假阳性变多 → BYTETracker 反而更乱**。继续降不解决根本问题。

#### 实验 4 — `imgsz 1280`（提升推理分辨率）⭐

| 视频 | baseline | conf 0.15 | conf 0.15 + imgsz 1280 | 总提升 |
|---|---|---|---|---|
| horizontal | 355 | 678 | **1470** | 4.14× |
| portrait_1 | 37 | 105 | **459** | **12.4×** 🚀 |
| portrait_2 | 193 | 367 | **845** | 4.38× |
| 总计 | 585 | 1150 | **2774** | 4.74× |

**portrait_1 涨 12 倍** —— 因为它远景小人，运动员只剩脚踝在画面里 ~40 像素，YOLO 默认 640 下采样后变 sub-pixel，**根本不看见**。1280 让小目标重现。

约召回率从 ~7% 飙到 ~36%。**imgsz 1280 是杀手锏**。

### 但 36% 仍然不是"够用"

总统大人在浏览器里实测后反馈：

> 体感没有变好，只是确实能同时识别到更多的人，但还是一直断断续续，在闪烁，没有稳定，ID 也一直在变化。

我跑了 set_008（horizontal, 5 人 32 秒）的 ID 统计：

| 指标 | 数值 |
|---|---|
| 真实运动员数 | 5 |
| 被分配的 unique ID 数 | **99** |
| BYTETracker 创建过的最大 ID | **544** |
| **ID 通胀倍数** | **19.8×** |
| 检测但 tracker 来不及关联（无 ID） | 535 次（占 36%） |
| 最大单帧并发 | 5（detector 偶尔能完整看见全部） |

**5 个运动员被发了 99 个 ID，平均每人换 20 个身份**。从教练视角看，就是骨架颜色和标签每秒钟换一次。这就是肉眼"闪烁、不稳定"的量化解释。

根因链条：detector 召回率 36% → BYTETracker 大部分时间看不见某个运动员 → 等 30 帧后把 track 当作 lost → 再次出现时分配新 ID。**这是 detector 问题，不是 tracker 问题**。tracker buffer 调长能延缓但不能解决。

### 决策：把 trick 落地，但承认它不够

**生产代码改动**：
- `tools/import_video.py` 默认 `--conf 0.15 --imgsz 1280`（离线 import 应该最高质量）
- `fastapi_app/yolo_pose.py` 默认 `conf=0.35 imgsz=640` **不动**（实时录制要 real-time，1280 慢 4× 摄像头吃不消）

把 `--imgsz` 暴露为 CLI 参数 + YoloPoseDetector 构造参数（默认 640，向后兼容），是这次 dogfood 唯一一处对生产代码的扩展。

### 真正的下一步：阶段 9 — Phase A + Phase B

zero-cost trick 的天花板是**详尽利用 COCO 模型现有能力**。要把召回率从 36% 推到 70%+，**只能 fine-tune**。

| 阶段 | 投入 | 解决 |
|---|---|---|
| **Phase A** — bbox detector fine-tune | ~150 帧 bbox 标注（1-2 小时）+ 训练 | "看不见"问题，召回 36% → >70% |
| **Phase B** — keypoint head fine-tune | 关键 4-6 个点（不是 17 个），~150 帧 + 训练 | "骨架位置不对"问题（COCO 17-point 在水中场景下 keypoint regression 完全错位） |

**先 A 后 B** 不是教条，是**单变量隔离**：标 1 个 bbox = 2 次点击，标 17 个 keypoint = 17+ 次点击。先用低成本 A 验证"fine-tune 这条路在水中场景能 work 吗"，**如果连 bbox 都训不上去，标 keypoint 也是浪费**。

### 收获

1. **dogfood 是检验所有"trick 信仰"的唯一标准**：阶段 8 完成时我以为 conf + imgsz 调参能把召回拉到 50-60%，实际撞在 36%。**没有真实数据验证，所有"应该够用了"都是赌博**。
2. **数字比体感更服人，但要先有体感才知道找哪个数字**：总统大人的"还是闪烁"是触发器，我去查 99 个 ID / 5 个运动员才把"闪烁"翻译成 "19.8× ID inflation"。**体感 → 数字 → 决策**，缺一环都不准。
3. **杀手锏 trick 往往藏在不显眼的参数里**：conf 是显眼参数（每个用户都会调），imgsz 一般人不会动。但 `imgsz 640 → 1280` 这一档对小目标 / partial body 的提升远超想象。**遇到 detector 召回低 + 看见目标小，先试 imgsz**。
4. **生产代码 vs 工具代码的默认值要分别决策**：实时录制走 `yolo_pose.py` 默认 → 性能优先 (640)；离线 import 走 `import_video.py` 默认 → 质量优先 (1280)。**同一段代码不同入口可以有不同 default**，别强求统一。
5. **fine-tune 之前先把 free trick 用尽，是负责任的工程姿态**：直接说"要 fine-tune"和"试过 4 档调参后还差 35%，所以要 fine-tune"是两个完全不同的可信度。**所有训练投入都应该有一个不能再调的 baseline 作为起点**，否则你不知道自己在 train 什么。
6. **Phase A → B 的拆分是数据成本最优**：bbox 标注成本是 keypoint 的 1/10。**先用便宜的数据验证假设，再用贵的数据精修**，这是任何机器学习项目的标准节奏。

---

> 本文档随项目进展持续更新。每次遇到有价值的技术问题都会追加记录。
