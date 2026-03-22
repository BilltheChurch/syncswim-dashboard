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

> 本文档随项目进展持续更新。每次遇到有价值的技术问题都会追加记录。
