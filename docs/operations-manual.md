# 操作手册：真实设备接入与平台部署

> **读者**：第一次拿到这个仓库、要把机器人真正跑起来的人。
>
> **本文假设你只做过一件事**：clone 了这个仓库。
> 从这里开始，每一步都能照抄。
>
> **当前形态的边界**（先看，免得白忙）：单机部署、无多实例、无负载均衡、
> 无下行语音下发（机器人**不回话**）、无 Redis 会话外置。
> 逐条限制与依据见 `docs/known-limitations.md`。
> 本手册覆盖的是**已实现**的部分。

---

## 目录

- [第 0 章：先跑通 PC 模拟端（10 分钟）](#第-0-章先跑通-pc-模拟端10-分钟)
- [第 1 章：环境准备](#第-1-章环境准备)
- [第 2 章：本地起服务](#第-2-章本地起服务)
- [第 3 章：接真实设备（分 5 步）](#第-3-章接真实设备分-5-步)
- [第 4 章：部署到服务器](#第-4-章部署到服务器)
- [第 5 章：日常运维](#第-5-章日常运维)
- [第 6 章：排障手册](#第-6-章排障手册)
- [附录 A：协议速查](#附录-a协议速查)
- [附录 B：命令速查](#附录-b命令速查)

---

# 第 0 章：先跑通 PC 模拟端（10 分钟）

**为什么先跑这个**：PC 模拟端和真实设备**跑的是同一份协议**。
模拟端跑不通，接真机一定也不通；模拟端跑通了，接真机只剩"把音频喂进去"这一件事。

跳过这章直接接真机，会把「协议问题」和「硬件问题」搅在一起 ——
两类问题的排查方式完全不同。

## 0.1 一次性检查环境

```powershell
cd D:\myproject\voice-companion

# Python 3.13
F:\tools\python313\python.exe --version          # 应为 Python 3.13.x

# JDK 21（路径按你的实际改）
$env:JAVA_HOME="F:\tools\jdk21\jdk-21.0.13+9"
& "$env:JAVA_HOME\bin\java.exe" -version          # 应为 21.x

# Maven
& "D:\apache-maven-3.9.2\apache-maven-3.9.2\bin\mvn.cmd" -v
```

**JDK 必须是 21**。用 JDK 17 编译会失败，报
`class file version 61.0 ... 65.0`（61 是 Java 17，65 是 Java 21）。

## 0.2 装 Python 依赖

```powershell
F:\tools\python313\python.exe -m pip install -r core\requirements.txt
```

> 首次安装较慢（faster-whisper 会带 ctranslate2、onnxruntime 等）。

## 0.3 下载模型（可选但强烈建议）

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\fetch-models.ps1 -Target all
```

下三个模型到 `core/models/`：

| 模型 | 大小 | 干什么用 | 不下会怎样 |
|---|---|---|---|
| `faster-whisper-base` | ~150MB | 端侧语音识别 | 识别不出文字，意图只能靠规则表命中 |
| `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` | ~400MB | 端侧本地对话 | 走固定话术库，不结合上下文 |
| `BGE-small-zh-v1.5` | ~23MB | 中文向量化（记忆召回） | 记忆召回不可用 |

> 模型**不入库**（体积大），所以 clone 之后是空的。
> 下载后 sha256 记入 `core/models/SHA256SUMS`，下次运行会强制比对，
> 不匹配就重下 —— 模型损坏的表现是"识别效果差"，极难排查。

## 0.4 起服务

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1
```

脚本会依次起 ChromaDB（8765）和云端后端（8080），并**等健康检查通过**才继续。
等 1-2 分钟（首次要编译），看到两个服务都"已就绪"即可。

验证：

```powershell
# ChromaDB
(Invoke-WebRequest "http://127.0.0.1:8765/api/v2/version" -UseBasicParsing).Content
# 应输出："1.0.0"

# 云端后端
(Invoke-WebRequest "http://127.0.0.1:8080/api/health" -UseBasicParsing).Content
# 应输出：{"status":"UP"}
```

## 0.5 起模拟端并对话

**另开一个终端**（在仓库根目录执行）：

```powershell
cd D:\myproject\voice-companion
F:\tools\python313\python.exe -m core.edge.simulator --url ws://127.0.0.1:8080/voice/uplink
```

对话里会说几句话，并打印识别结果与云端回复。**先确认这条链路是通的**：

- 能看到识别出的文本
- 能看到云端的回复
- 不会报"上行链路失败"

> **为什么模拟端必须在仓库根执行**：端侧代码在 `core/` 包下，
> 模块全名是 `core.edge.simulator`。在 `core/` 目录里跑
> `python -m edge.simulator` 会因包路径不对而失败。

## 0.6 跑一次完整评测（确认基线）

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\eval.ps1
```

产出两份报告：

| 报告 | 内容 |
|---|---|
| `core/eval-report.md` | 云端五维门禁（意图 / 记忆召回 / 记忆应答 / 安全 / 共情） |
| `core/eval-edge-report.md` | 端侧 ASR（分三个噪声条件） |

**基线数字**（本机实测）：

```
INTENT        100.0%  ≥ 85%   通过
MEMORY_RECALL 100.0%  ≥ 90%   通过
MEMORY_ANSWER 100.0%  ≥ 95%   通过
SAFETY        100.0%  ≥ 95%   通过
EMPATHY        80.0%  ≥ 75%   通过
ASR clean      85.7%  ≥ 80%   通过
```

> 数字会随机器与模型版本浮动，**重点看"是否通过"**，不要死抠具体数值。

**这一步跑通了，才继续往下。**

---

# 第 1 章：环境准备

## 1.1 目录结构与各自的作用

```
voice-companion/
├── core/                  ← 开源核心（MIT）
│   ├── protocol/schema/   ← ★ 协议定义（设备接入的唯一标准）
│   ├── edge/              ← PC 模拟端（端侧参考实现）
│   ├── cloud/             ← 云端后端（Java 21 / Spring Boot 3.3.5）
│   ├── eval/              ← 评测集与门禁
│   ├── e2e/               ← 端到端脚本
│   ├── models/            ← 模型（不入库）
│   └── scripts/           ← 启停与评测脚本
├── device-ref/            ← ★ 设备侧参考实现（STM32 固件骨架）
├── docs/                  ← 交付文档
├── deploy/                ← 公司内网层（不入库）
└── data/                  ← 运行期产物（不入库）
```

## 1.2 服务器配置要求

| 服务 | 端口 | 资源 | 说明 |
|---|---|---|---|
| ChromaDB | 8765 | 内存 ≥ 512MB | 磁盘按数据量 |
| 云端后端 | 8080 | JVM 堆 ≥ 512MB，磁盘 ≥ 200MB | HTTP + WebSocket |
| 端侧设备 | — | — | 设备侧，连到云端 8080 |

**整台机器实测约 700MB 内存**（仅 ChromaDB + 云端后端，空闲）。
加 Whisper 模型后端侧另需约 800MB。

**当前无 GPU 需求**（大模型是可选的外部服务）。

## 1.3 需要的软件

| 软件 | 版本 | Windows 安装 | Linux 安装 |
|---|---|---|---|
| Python | 3.13 | `F:\tools\python313` | `python3.13` |
| JDK | 21 | `F:\tools\jdk21` | `openjdk-21-jdk` |
| Maven | 3.9+ | `apache-maven-3.9.2` | `apt install maven` |
| ChromaDB | 1.0+ | `pip install chromadb` | 同左 |

---

# 第 2 章：本地起服务

> 如果第 0 章已经起好了，跳过这章。

## 2.1 启动顺序（不能改）

```
ChromaDB → 云端后端 → 端侧设备
```

**为什么 Chroma 必须先起**：云端后端启动时做一次 Chroma 连通性检查，
Chroma 没就绪会让后端**启动失败**。这个检查是有意的 ——
宁可启动失败，也不要让后端在 Chroma 不可用时"假装正常"。

## 2.2 一条命令起全部

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1
```

## 2.3 分步启动（排障时用）

```powershell
# 只起 Chroma
powershell -ExecutionPolicy Bypass -File core\scripts\chroma.ps1 start

# 查 Chroma 状态
powershell -ExecutionPolicy Bypass -File core\scripts\chroma.ps1 status

# 只起后端（假定 Chroma 已在跑）
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1 -SkipChroma

# 只起 Chroma，不起后端
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1 -SkipBackend
```

## 2.4 停服务

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\stop.ps1
```

> **已知限制**：脚本拉起的**嵌入服务不回收**（见 `known-limitations.md` 2.18）。
> 连跑几次评测后，后台会留下多个实例抢端口，表现为"脚本卡住不动"。
> 遇到时先跑 `stop.ps1`，必要时按端口手工清理。

---

# 第 3 章：接真实设备（分 5 步）

**这一章是本文的重点。** 分 5 步，每步都有验收标准 ——
上一步没验收通过就往下走，会把问题搅在一起。

```
第 1 步  读协议        → 知道要发什么
第 2 步  硬件接线与配置 → 麦克风、串口、Wi-Fi
第 3 步  端侧跑通      → 采集 + VAD + 意图（不连云端）
第 4 步  连上云端      → 协议握手 + 上行
第 5 步  双向验收      → 跨用户隔离 + 降级
```

---

## 第 1 步：读协议（30 分钟）

### 1.1 协议在哪

**`core/protocol/schema/` 是唯一标准。** 设备侧与云端共用这一份 schema。

| 文件 | 什么时候用 |
|---|---|
| `session.schema.json` | 会话开始 / 心跳 / 结束 |
| `audio-negotiation.schema.json` | 连接建立时协商音频格式 |
| `audio-frame.schema.json` | 上行音频帧 |
| `intent-report.schema.json` | 上行意图报告 |
| `text-reply.schema.json` | 下行文本回复 |
| `voice-chunk.schema.json` | 下行语音片段 |
| `control-channel.schema.json` | 控制通道 |
| `degrade-level.schema.json` | 降级等级 |

### 1.2 固件侧要用的常量

**`device-ref/firmware/include/vc_protocol.h` 把每个字段名固化成常量。**

固件不解析 JSON（flash 占用与实时性都不允许），
但每个字段名对应 schema 里的原始字段名。
**schema 改字段名而固件没改，测试立刻失败** —— 这是有意的守门。

先看这个头文件，它就是设备侧的"字典"：

```c
#include "vc_protocol.h"

/* 用常量拼字段名，不要手写字符串字面量 */
json_object *session = json_object_new_object();
json_object_object_add(session, VC_SESSION_ID, json_object_new_string(session_id));
json_object_object_add(session, VC_TYPE, json_object_new_string(VC_SESSION_TYPE_BEGIN));
json_object_object_add(session, VC_OWNER_KEY, json_object_new_string(owner_key));
```

**常量命名规则**：`VC_` + 字段名转大写下划线。

| 字段名 | 常量 |
|---|---|
| `sessionId` | `VC_SESSION_ID` |
| `ownerKey` | `VC_OWNER_KEY` |
| `sequence` | `VC_SEQUENCE` |
| `timestampMs` | `VC_TIMESTAMP_MS` |
| `payloadBase64` | `VC_PAYLOAD_BASE64` |
| `sampleRate` | `VC_SAMPLE_RATE` |
| `channels` | `VC_CHANNELS` |
| `text` | `VC_TEXT` |
| `intent` | `VC_INTENT` |
| `confidence` | `VC_CONFIDENCE` |
| `handledLocally` | `VC_HANDLED_LOCALLY` |
| `audioFormat` | `VC_AUDIO_FORMAT` |
| `emotion` | `VC_EMOTION` |
| `citations` | `VC_CITATIONS` |

> ★ **`vc_protocol.h` 里已包含全部协议字段名常量**，包括
> `VC_OWNER_KEY`、`VC_AUDIO_FORMAT`、`VC_SAMPLE_RATE`、`VC_CHANNELS`、
> `VC_HANDLED_LOCALLY`、`VC_EMOTION`、`VC_CITATIONS`。
>
> 这张表由测试**从 schema 自动推导** —— schema 加了字段而固件没加常量，
> 测试立刻失败。不必自己核对完整性。

**音频的"取值"常量不在这里**，在 `vc_audio_task.h`：

```c
#include "vc_audio_task.h"

/* 音频参数取值 */
VC_AUDIO_SAMPLE_RATE_HZ   /* 16000 */
VC_AUDIO_CHANNELS         /* 1 */
VC_AUDIO_BITS_PER_SAMPLE  /* 16 */
VC_AUDIO_FRAME_DURATION_MS /* 20 */
VC_AUDIO_FRAME_SAMPLES    /* 320 */
VC_AUDIO_FRAME_BYTES      /* 640 */
```

> **两套常量别搞混**：`vc_protocol.h` 是**字段名**（拼 JSON 的键），
> `vc_audio_task.h` 是**音频参数取值**（填 JSON 的值）。
> 两者都要用 —— 比如 `VC_SAMPLE_RATE`（键）配 `VC_AUDIO_SAMPLE_RATE_HZ`（值）。

### 1.3 设备侧的任务划分

`device-ref/firmware/include/` 里的四个头文件，划分的依据是**谁在等谁**：

| 任务 | 头文件 | 职责 | 等待关系 |
|---|---|---|---|
| 采集与 VAD | `vc_audio_task.h` | I2S/DMA 采集 → 帧组装 → VAD → 20ms 定长帧 | 永不等待 |
| 端侧 ASR | `vc_asr_task.h` | 语音段 → 识别 → 文本与置信度 | 等语音段 |
| 意图判定 | `vc_intent_task.h` | 规则表判定 → 本地处理还是上云 | 等识别文本 |
| 会话状态机 | `vc_state_machine.h` | 六态流转、打断处理、超时回退 | 被所有任务驱动 |

**音频任务永远在跑，其余任务等音频任务喂数据**；
云端消息任务独立于语音链路 —— 即使识别卡住也要能接收降级指令。

### 1.4 ★ 三条不可协商的约束

**这三条写错了，编译通过、联调通过，直到真机跑起来才暴露。**

#### 约束 1：帧长固定 20ms（320 采样点）

变长帧会让云端分片重组与端侧帧序号对不上，
表现为**"偶发丢字"**，且只在语音长短不一时出现。

- 16 kHz × 20 ms = 320 采样点 = 640 字节（16-bit 单声道）
- 半帧**必须补齐后再上行**，并显式标记 `isFinalPartial: true`
- **不允许把半帧当完整帧上行**

#### 约束 2：状态机六态必须与端侧 Python 实现一致

`core/edge/session/state_machine.py` 的 `SessionState`。

两端状态集不一致时，固件会停在 Python 侧不存在的状态上。

#### 约束 3：打断只丢"还没播出去的音频"，不丢"已识别的文本"

用户打断说"等等"，机器人应把已识别的那句**接着说完**，
而不是当作没发生过。

> 这三条由 `core/tests/device_ref/test_firmware_interfaces.py` 守着，
> 改固件后跑一遍测试就知道有没有破坏。

---

## 第 2 步：硬件接线与配置（半天）

### 2.1 必备硬件

| 项 | 要求 | 说明 |
|---|---|---|
| MCU | STM32 系列（带 I2S 或 PCM 接口） | 协议与具体型号无关 |
| 麦克风 | I2S 数字麦或模拟麦 + ADC | 16 kHz 采样 |
| 扬声器 | I2S DAC + 功放 | 回话（当前形态**不实现**，见下） |
| Wi-Fi | 2.4G | 连云端 |
| 串口 | USB-UART | 调试日志 |
| 电源 | 5V / 3.3V | — |

> **关于扬声器**：当前云端**没有下行语音下发**（机器人不回话）。
> 云端只下发**文本**回复。这是有意的范围裁剪 ——
> 详见 `known-limitations.md` 2.6。
> 设备端可以先只做上行，文本回复打在串口日志上，等下行语音实现了再接扬声器。

### 2.2 音频链路配置

| 参数 | 值 | 说明 |
|---|---|---|
| 采样率 | **16000 Hz** | 协议默认；也支持 24000 / 48000 |
| 位深 | 16 bit | `PCM_S16LE` |
| 声道 | **单声道** | 协议只支持单声道 |
| 帧长 | **20 ms** | 见约束 1 |
| 编码 | `PCM_S16LE` 或 `OPUS` | Opus 需在协商时给 `opusBitRate` |

**连接建立时的音频格式协商**（`session` 消息的 `audioFormat` 字段）：

```json
{
  "sampleRate": 16000,
  "channels": 1,
  "bitDepth": 16,
  "encoding": "PCM_S16LE",
  "frameDurationMs": 20
}
```

> **为什么是 16 kHz**：端侧 ASR 与记忆嵌入都用 16 kHz，
> 统一采样率省掉一次重采样，也省掉一次音质损失。

### 2.3 时钟漂移

**麦克风晶振与 MCU 主频不同源，长时间会漂移**。

- 症状：跑了几分钟后，云端收不到帧或帧序号跳变
- 排查：在固件里对比"采集到的采样点数"与"按时间算应采到的采样点数"
- 对策：以**采样点数**为主时间基准，而不是以毫秒计数为主

---

## 第 3 步：端侧跑通（不连云端）（1-2 天）

**先不连云端**，把「麦克风 → 帧 → VAD → 意图」这一段单独跑通。
这样出问题时不用怀疑网络。

### 3.1 验收标准

| 项 | 达标线 | 怎么测 |
|---|---|---|
| 采集连续 | 不丢帧 | 串口打印每秒帧数，应为 50 |
| 帧长正确 | 每帧恰好 320 采样点 | 打印帧长统计 |
| VAD 有效 | 说话时触发，静默时不触发 | 对着麦克风说话，看串口日志 |
| 断句合理 | 一句话说完后出一次识别 | 读完整句，看是否切出完整语音段 |
| 意图命中 | 常用指令能识别 | 读「开灯」「几点了」等 |

### 3.2 参考实现怎么用

`device-ref/firmware/include/` 的四个头文件是**接口定义**，不是完整实现 ——
它们规定"任务之间怎么协作"，但采集驱动、识别后端要你自己接。

| 你要接的 | 头文件给了什么 | 你要补的 |
|---|---|---|
| 麦克风 | `vc_audio_task.h` 的帧组装与 VAD 接口 | I2S/DMA 驱动配置、中断处理 |
| 语音识别 | `vc_asr_task.h` 的调用约定 | 厂商 SDK 或量化模型的移植 |
| 意图判定 | `vc_intent_task.h` 的规则表接口 | 规则表内容 / 小模型 |
| 对话 | — | 话术库 |

### 3.3 ★ 行为契约：PC 侧是设备侧的行为参考

**结构一致不等于行为一致** —— 固件头文件里写着的语义承诺，
和 PC 侧实际跑出来的行为可能对不上，
而这类分歧**编译通过、联调通过、直到真机跑起来才暴露**。

所以把行为契约写成机器可检查的形式：

| 文件 | 作用 |
|---|---|
| `core/edge/device_ref/behavior_contract.py` | 每条声明"固件侧语义"与"PC 侧参考实现"，写明"不做会怎样" |
| `core/tests/device_ref/test_behavior_contract.py` | 逐条核对：常量取值一致、枚举集合相同、行为规则**实际执行验证** |

**行为规则要真的跑一遍**，不能只比对符号名。
例如"打断丢音频、留文本" —— 两边都有 `on_recognized` 函数，
但 PC 侧若只记长度不记内容，打断时文本就没了。**只有真的打断一次才知道**。

### 3.4 已知的固件 / PC 分歧（已修，供对照）

| 分歧 | 固件侧 | PC 侧 | 后果 |
|---|---|---|---|
| 意图降级阈值 | `VC_INTENT_KEYWORD_ONLY_THRESHOLD 400`（0.4） | `RECOGNITION_CONFIDENCE_THRESHOLD 0.5` | 同一句话在固件上按关键词执行、在模拟端却拒识 |
| 打断事件缺文本长度 | `retained_text_length`（uint16） | 只有 `retained_text`，无长度 | 固件实现者只能猜该填什么；填 0 等于"文本全丢了" |

### 3.5 ★ 必须在真机上测、不能在 PC 上编的项

以下列在 `behavior_contract.py` 的 `HARDWARE_ONLY_MEASUREMENTS` 里：

| 项 | 验证方式 |
|---|---|
| 打断响应延迟**绝对值** | 目标板上打时间戳 |
| 端侧 ASR 在 Cortex-M 上的延迟 | 目标板上跑通一段真实录音，确认延迟与内存占用 |
| 任务栈与队列深度 | 目标板压力场景，确认无优先级反转与栈溢出 |
| I2S/DMA 中断抖动与时钟漂移 | 目标板测中断抖动与丢帧率 |
| flash 余量 | 量测 |
| 功耗与温升 | 功耗仪实测典型与峰值工况 |
| OTA 真实切换与回滚 | 真机执行一次完整升级，并人为制造断电与验签失败各一次 |

> **这份清单的价值在"排除"**：把"PC 上验不了的"明确列出来，
> 避免有人在 PC 上给它们编一个假的通过结论。

---

## 第 4 步：连上云端（1 天）

### 4.1 连接与鉴权

```
设备 → wss://<服务器>:8080/voice/uplink
```

| 项 | 值 | 说明 |
|---|---|---|
| 协议 | WebSocket（RFC 6455） | — |
| 路径 | `/voice/uplink` | — |
| 鉴权头 | `Authorization: Bearer <token>` | 也支持 `?token=` |
| 无鉴权时 | 直接连 | **仅开发期**，生产必须设 `VOICE_UPLINK_TOKEN` |

> **生产环境必须设置 `VOICE_UPLINK_TOKEN`**。
> 不设置时上行通道**不鉴权**，任何能连到端口的客户端都能建会话。

### 4.2 上行消息顺序

```
① session(begin)   ← 必须**显式**发，不能靠"发第一帧音频"隐含
② audio-frame × N  ← 连续序号
③ intent-report    ← 每说完一句
④ session(keepalive) ← 定期心跳
⑤ session(end)    ← 结束时，带 reason
```

**为什么 begin 必须显式发**：云端要在收到音频**之前**就知道会话存在，
才能提前建立会话上下文。

**为什么需要心跳**：让云端能区分"设备还在但不说话"与"设备掉线"。
没有心跳时云端只能靠 TCP 超时判断掉线，会把长时间的静默误判为离线，
从而回收掉其实还活着的会话。

### 4.3 四种上行消息的具体格式

#### ① 会话开始

```json
{
  "sessionId": "dev-001-session-20261123",
  "type": "begin",
  "ownerKey": "user-42",
  "timestampMs": 0,
  "audioFormat": {
    "sampleRate": 16000,
    "channels": 1,
    "bitDepth": 16,
    "encoding": "PCM_S16LE",
    "frameDurationMs": 20
  }
}
```

> ★ **`ownerKey` 是跨用户隔离的根基**。云端据此绑定记忆作用域 ——
> 没有它，云端写的记忆**全部落进同一个作用域**，跨用户隔离无从谈起。
>
> **生产部署中该值应由接入凭据推导，而非由设备自报** —— 否则设备可以随便报一个
> `ownerKey` 去读别人的记忆。

#### ② 音频帧

```json
{
  "sessionId": "dev-001-session-20261123",
  "sequence": 0,
  "timestampMs": 0,
  "sampleRate": 16000,
  "channels": 1,
  "payloadBase64": "<640 字节 PCM 的 base64>",
  "isFinalPartial": false
}
```

| 字段 | 要求 |
|---|---|
| `sequence` | 从 0 起连续递增；**重连后从断点续传，不重发** |
| `timestampMs` | 该帧首采样点的会话内相对毫秒偏移 |
| `payloadBase64` | 16 kHz 单声道 16-bit → 640 字节 → base64 约 856 字符 |
| `isFinalPartial` | 半帧补齐后的尾帧标记为 `true` |

> **序号由客户端维护，重连时从断点续传**。
> 若序号放在服务端或每次重连重新计数，云端会收到**序号回退**的帧，
> 无法判断是丢帧还是重传。

#### ③ 意图报告

```json
{
  "sessionId": "dev-001-session-20261123",
  "sequence": 42,
  "intent": "query_weather",
  "confidence": 0.92,
  "handledLocally": false,
  "text": "明天天气怎么样",
  "slots": { "city": "北京" }
}
```

| 字段 | 说明 |
|---|---|
| `intent` | 意图标识；未知取 `unknown` |
| `confidence` | 0~1 |
| `handledLocally` | `true` = 端侧已执行；`false` = 云端执行 |
| `text` | ★ 端侧识别出的**用户原话** |
| `slots` | 意图参数 |

> ★ **`text` 不能省**。云端据此写入长期记忆与做召回 ——
> 没有它，云端只拿到意图标识，**无法记住用户说过的话**。
>
> 记忆写入发生在**回复之前** —— 这一轮说的话要先落库，
> 下一轮才能召回它。顺序颠倒会让用户**永远慢一轮才被"记住"**。

#### ④ 心跳

```json
{ "sessionId": "dev-001-session-20261123", "type": "keepalive", "timestampMs": 0 }
```

#### ⑤ 会话结束

```json
{ "sessionId": "dev-001-session-20261123", "type": "end", "reason": "user_left" }
```

`type=end` 时 `reason` **必填**（schema 里用 `allOf/if/then` 强制）。

### 4.4 下行消息

设备要处理两类下行：

| 类型 | schema | 当前是否实现 |
|---|---|---|
| 文本回复 | `text-reply.schema.json` | ✅ 已实现 |
| 语音片段 | `voice-chunk.schema.json` | ⚠️ 协议已定义，**云端未实现下发** |

文本回复形如（这是**云端实际下发的内容**，可直接对照）：

```json
{
  "sessionId": "manual-probe-session-1",
  "text": "我记得，我妈妈叫李芳",
  "emotion": "tenderness",
  "citations": ["b8085cc5-f6f1-487f-9320-eb49ef131187"]
}
```

| 字段 | 说明 |
|---|---|
| `sessionId` | 与上行一致，设备据此把回复对回会话 |
| `text` | 回复正文 |
| `emotion` | 情感标签，**取值是固定集合**（见下） |
| `citations` | 引用的记忆标识数组；**没有命中记忆时为空数组** |

**`emotion` 的合法取值**（`text-reply.schema.json` 的枚举，写固件时要一一对应）：

```
neutral  joy  sadness  anger  fear  surprise  tenderness  encouragement
```

> ★ **`text-reply` 没有 `intent` 字段。**
> schema 是 `additionalProperties: false` —— 多发一个 `intent` 会被判不合规。
> 设备若要按意图区分处理，得自己在端侧记住"这句话对应的意图"，
> 不能指望云端在下行里回传。
>
> ★ **`citations` 由代码填充，不由模型生成** ——
> 这是「不同用户的记忆互不可见」能被机器断言的前提。
>
> ★ **`citations` 的值是 UUID，不是 `mem-20261123-001` 这种可读编号。**
> 设备侧不要解析它的格式，只当不透明字符串用。

### 4.5 端侧要实现的四条行为

| 行为 | 要求 | 错了会怎样 |
|---|---|---|
| **重连** | `sessionId` 保持不变，序号从断点续传 | 云端当作新会话，上下文全丢 |
| **打断** | 只丢还没播的音频，**已识别的文本要留** | 机器人把用户说过的话忘掉 |
| **断网降级** | 本地话术库顶上，不能静默 | 表现为"机器人死了" |
| **坏消息** | 单条协议不合法的消息**不该断开连接** | 重连丢掉已积累的会话上下文 |

> 云端侧也是同样原则：`SessionWebSocketHandler` 不因单条坏消息而断开连接 ——
> 一条协议不合法的消息不该让设备重连。

### 4.6 端侧断线重连的判定

| 类别 | 处理 | 为什么分开 |
|---|---|---|
| `UplinkError`（网络问题） | 降级到本地陪伴继续跑 | 网络断了可以本地兜底 |
| `UplinkAuthError`（鉴权问题） | **必须让人知道"去改配置"** | 静默降级会把配置错误伪装成网络故障 |

### 4.7 ★ 云端的实际行为（实测记录）

这一节是**照手册的 JSON 直连云端实测出来的**，不是设计意图。
设备实现者可以据此判断"我的实现对不对"。

**环境**：单机部署，未设 `VOICE_UPLINK_TOKEN`（开发期无鉴权）。

#### 实测 1：照抄手册的 JSON，一次就通

发 `session(begin)` → 发 `intent-report` → 收到回复：

```json
{
  "sessionId": "manual-probe-session-1",
  "text": "我记得，我妈妈叫李芳",
  "emotion": "tenderness",
  "citations": ["b8085cc5-f6f1-487f-9320-eb49ef131187"]
}
```

**要点**：

- 记忆在**第一轮**就写入并被召回 —— 写记忆发生在生成回复**之前**
- `citations` 里的值是 **UUID**
- `text-reply` **没有 `intent` 字段**（schema 是 `additionalProperties: false`）
- 兜底话术是 `"我这边还没有关于这件事的记录，你说得再具体一点我就能记下了。"`

#### 实测 2：重连（保持 sessionId，序号续传）

| 阶段 | 结果 |
|---|---|
| 第一次连接说出"我养了一只叫豆豆的猫" | 收到回复，引用 1 条 |
| 断开后**用同一个 sessionId** 重连，序号从 1 续传 | 收到回复，引用**同一条**记忆（UUID 相同） |

→ **云端认 sessionId，不认连接**。重连不会丢上下文。

#### 实测 3：跨用户隔离

| 用户 | 动作 | 结果 |
|---|---|---|
| A（ownerKey=`...-user-a`） | 说出"我妈妈叫李芳" | 引用 1 条，回复"我记得，我妈妈叫李芳" |
| B（ownerKey=`...-user-b`） | 问"我妈妈叫什么" | **引用 0 条**，回复兜底话术，**没有泄漏李芳** |

→ 隔离**真的生效**，不是靠"谁都召不回"蒙混过关。

#### 实测 4：不带 ownerKey

| 动作 | 结果 |
|---|---|
| `session(begin)` 不带 `ownerKey` | **仍能正常对话**，但记忆落进**默认作用域** |

→ 隔离失效，但**功能不报错**。这就是手册强调
"生产部署中 ownerKey 应由接入凭据推导，而非由设备自报"的原因 ——
靠设备自觉是不可靠的，必须在接入层强制。

#### 实测 5：★ 当前这句话自己会是 Top-1 命中

| 设备发出 | 云端回复 |
|---|---|
| `"明天下午三点有个会议"` | `"我记得，明天下午三点有个会议"` |

**这不是 bug，是设计**：云端把**写记忆放在生成回复之前**，
所以用户这一轮刚说的话立刻进入记忆库，也立刻是 Top-1 命中。

> ★ **设备实现者必须知道这条行为**。
> 看到"机器人重复用户刚说的话"，别以为是自己的固件坏了 ——
> 该修的是云端的这个行为，不是设备。
>
> 反过来也解释了另一件事：**问句不会被当成记忆**。
> 问句被分类器剔除（见 `CompanionMemoryClassifier` 的 `QUESTION_MARKERS`），
> 否则会出现"你说你想知道你妈妈叫什么"这种更糟的表现。

#### 实测 6：云端日志长什么样

设备联调时**同时盯云端日志**（`core/cloud/logs/backend.out.log`），
这是判断"设备发的东西云端认不认"的直接依据。

**会话注册**（收到 `session(begin)`）：

```
会话已注册：contract-session-a-1795441251377805900 → 处理单元 unit-0，用户=contract-iso-a-1795441251377799700
```

| 片段 | 含义 |
|---|---|
| `会话已注册：<sessionId>` | 云端认了你的 sessionId |
| `→ 处理单元 unit-N` | 会话被分配到的处理单元 |
| `用户=<ownerKey>` | ★ **ownerKey 已绑定到作用域** —— 这一行是最重要的 |

> **`用户=` 为空或不是你期望的值，说明 ownerKey 没传或传错了** ——
> 此时对话仍能进行，但记忆全部落进默认作用域，跨用户隔离失效。

**下发回复**（每次回你一条）：

```
下发回复：会话=contract-session-a-1795441251377805900 意图=chat 本地已处理=false 引用来源=[7a4ac619-4638-4131-9db0-cef7631008c2]
```

| 片段 | 含义 |
|---|---|
| `引用来源=[...]` | 非空 = 命中了记忆；**空 = 走了兜底话术** |
| `本地已处理=false` | 该意图由云端执行（端侧已处理的意图不会上行） |

**关闭连接**：

```
上行通道已关闭：CloseStatus[code=1000, reason=null]
```

**鉴权警告**（开发期正常，生产必须消失）：

```
上行通道未配置凭据，任何客户端都能接入 —— 生产部署必须配置
```

> ⚠️ 生产环境看到这行，说明 `VOICE_UPLINK_TOKEN` 没设 ——
> **任何客户端都能接入上行通道**。

---

## 第 5 步：双向验收（半天）

### 5.1 跑端到端脚本

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\e2e.ps1
```

产出 `data/reports/` 下的端到端报告，逐项断言：

| 断言 | 验证什么 |
|---|---|
| 用户A的回复引用自己的记忆 | 记忆召回对**同一个人**生效 |
| 用户B的回复引用自己的记忆 | 不是"谁都召不回"蒙混过关 |
| 用户B问用户A的事不引用A的记忆 | ★ **跨用户隔离** |
| 离线降级能出话 | 断网时本地兜底有效 |

> ★ 第 3 条是**核心**：它验证"用户 B 问用户 A 的事实"时，
> 引用数为 0。
>
> **这个断言曾经失效过**：早期用固定 owner key（`e2e-user-a` / `e2e-user-b`），
> 上一轮跑完残留的记忆留在作用域里，B 的作用域里躺着 A 的事实，
> 断言**因为状态残留而通过** —— 与被测机制脱钩。
> 现在改用**运行期唯一的 owner key**（微秒时间戳 + 进程号），
> 每次跑都是干净作用域。

### 5.2 人工验收清单

| # | 操作 | 期望 | 不符合时查什么 |
|---|---|---|---|
| 1 | 设备连上云端 | 后端日志出现 `会话已注册：<sessionId>` | WebSocket 路径、鉴权头 |
| 2 | 对着麦克风说话 | 设备日志出现识别文本 | 音频链路、VAD、ASR |
| 3 | 说完一句话 | 设备发出 `intent-report`（含 `text`） | 断句逻辑、`text` 是否带 |
| 4 | 云端回复 | 串口/日志出现文本回复；后端日志有 `下发回复：` | `ownerKey`、`text` 字段 |
| 5 | ★ 查日志里的归属 | 后端日志 `会话已注册` 行的 `用户=` **等于你的 ownerKey** | ★ ownerKey 没传 —— 隔离会失效 |
| 6 | 换一句话提到自己 | 下一轮回复引用上一轮（后端日志 `引用来源=[...]` 非空） | 记忆写入顺序（先写后回） |
| 7 | 问另一个用户的事 | 引用数为 0（后端日志 `引用来源=[]`） | `ownerKey` 一致性 |
| 8 | 拔网线 | 设备本地出话，不静默 | 降级策略 |
| 9 | 插回网线 | 自动重连，会话上下文还在 | `sessionId` 与序号续传 |
| 10 | 说"等等"打断 | 已识别的那句**接着说完** | 打断处理（丢音频、留文本） |
| 11 | 连发两句话 | 序号连续，无回退 | 序号维护 |

> ★ 第 5 条最容易被跳过，却是**最关键**的一条。
> `ownerKey` 没传时**对话一切正常**，只是记忆落进默认作用域 ——
> 没有明显报错，等到发现"不同用户串记忆"时，早就上线了。
> 所以每次联调都要**看一眼日志里的 `用户=` 是不是你期望的值**。

### 5.2.1 自动化验收（可选，但推荐）

```powershell
F:\tools\python313\python.exe -m pytest core/tests/e2e/test_device_contract.py -q
```

这条测试**对着真实云端**验证手册第 4 章的行为承诺：

| 测试 | 验证 |
|---|---|
| `test_manual_uplink_json_works_verbatim` | 照抄手册的 JSON 能通 |
| `test_text_reply_has_no_intent_field` | 下行**不带** `intent` 字段 |
| `test_emotion_value_is_from_the_declared_enum` | `emotion` 取值合法 |
| `test_citations_are_opaque_ids_not_readable_numbers` | `citations` 是不透明 ID |
| `test_reconnect_with_same_session_id_keeps_memory` | 重连保持上下文 |
| `test_cross_user_isolation_blocks_leak` | ★ 跨用户隔离 |
| `test_no_match_falls_back_to_no_recall_template` | 空作用域走兜底话术 |
| `test_current_utterance_is_its_own_top_hit` | ★ 当前话自命中是设计行为 |

> 云端未运行时整组跳过（不会在没起服务的机器上产生噪声）。

### 5.3 模型包与 OTA（若要上真机）

#### 模型包

```powershell
# 生成签名密钥（只需一次；私钥不得入库）
F:\tools\python313\python.exe device-ref/model-package/package_model.py --gen-key keys/device_sign_key.pem

# 打包
F:\tools\python313\python.exe device-ref/model-package/package_model.py --manifest build/manifest.json --out dist/companion_model_pkg --sign-key keys/device_sign_key.pem
```

产物是**目录**而非单一容器文件。未提供签名密钥时脚本**直接失败** ——
未签名的模型包等于明文分发模型文件，攻击者可替换模型而设备端无从察觉。

> **设备端的包安装与校验流程尚未实现**，只有打包侧。
> 设备端实现安装器后需做一次端到端安装。

#### OTA

```powershell
# 只演练流程，不碰设备
F:\tools\python313\python.exe device-ref/ota/ota_update.py --image dist/firmware-2.5.0.bin --device COM3 --dry-run

# 自检
F:\tools\python313\python.exe device-ref/ota/ota_update.py --self-check
```

三条不可协商的规则：

1. **验签失败即中止** —— 刷入未经验签的镜像等于放弃全部安全保证
2. **只写备用分区** —— 当前运行分区永远不动，它是唯一可回退的保障
3. **自检通过才切换** —— 自检不过就留在旧分区继续跑

> `--dry-run` **不打开设备、不写串口、不下发任何命令**，
> 只演练流程编排与参数判定。

---

# 第 4 章：部署到服务器

> 与第 0~3 章的差别主要是：**换机器、换地址、生产配置**。

## 4.1 部署形态

```
┌──────────────────────────────────────────────────────┐
│  服务器                                                │
│                                                       │
│  ┌──────────────┐      ┌────────────────────┐        │
│  │ ChromaDB     │◄─────┤ 云端后端            │        │
│  │  :8765       │      │  :8080              │        │
│  └──────────────┘      │  ├ /api/health      │        │
│                        │  └ /voice/uplink    │        │
│                        └────────────────────┘        │
│                              ▲                        │
│                              │ WebSocket              │
│                        ┌─────┴──────────┐             │
│                        │  真实设备       │             │
│                        └────────────────┘             │
└──────────────────────────────────────────────────────┘
```

**当前不支持**：多实例部署、负载均衡、跨机部署。
云端的会话注册表是**进程内**的，多实例之间不共享（见 `known-limitations.md` 2.2）。

## 4.2 上传到服务器

```bash
# 只传源码，不传模型与运行产物
rsync -av --exclude 'core/models' --exclude 'data' \
      --exclude '.git' --exclude '__pycache__' \
      voice-companion/ user@server:/opt/voice-companion/
```

模型单独分发（走内网制品库，见 4.5）。

## 4.3 环境变量（生产）

```bash
# ★ 必须设置：不设置时上行通道不鉴权，任何客户端都能接入
export VOICE_UPLINK_TOKEN='<生产接入凭据>'

# 大模型（可选，两者都设置才启用）
export VOICE_LLM_BASE_URL='https://your-llm-gateway.example.com/v1'
export VOICE_LLM_API_KEY='<key>'
export VOICE_LLM_MODEL='qwen-plus'

# Chroma（用默认值则不用设）
export VOICE_CHROMA_BASE_URL='http://127.0.0.1:8765'
export VOICE_CHROMA_DATA_PATH='/opt/voice-companion/data/chroma'
```

**完整变量清单**见 `docs/deployment.md` 第 2 节。

> **大模型是可选增强，不是必需依赖**。
> 两者都设置才启用；只设其一多半是配置写错了，
> 此时直接走模板路径而不是发起注定失败的请求。
> 大模型的失败（超时、5xx、响应不可解析）在服务内部被兜住，
> 自动退回模板，**不会中断对话**。

## 4.4 启动

```bash
cd /opt/voice-companion
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk
export PATH=$JAVA_HOME/bin:$PATH

# 编译
cd core/cloud && mvn -o clean package -DskipTests

# 起 Chroma
powershell 不适用，Linux 用 chroma 直接起：
chromadb run --path /opt/voice-companion/data/chroma --host 0.0.0.0 --port 8765 &

# 等 Chroma 就绪
until curl -sf http://127.0.0.1:8765/api/v2/version >/dev/null; do sleep 2; done

# 起云端
nohup java -jar core/cloud/target/voice-cloud-0.0.1-SNAPSHOT.jar \
      > core/cloud/logs/backend.out.log 2>&1 &

# 等云端就绪
until curl -sf http://127.0.0.1:8080/api/health >/dev/null; do sleep 2; done
echo "服务已就绪"
```

> **为什么这里不用 `start.ps1`**：它是 Windows 脚本（PowerShell）。
> Linux 上要么用 systemd（见 4.6），要么照上面手写。

## 4.5 模型分发

**不要让每个部署点都从公网镜像拉**。走内网制品库：

```bash
# 目标机上
python3.13 core/scripts/fetch-models.ps1 -Target all   # Windows 版
# Linux 上直接用 huggingface-cli 拉到 core/models/，
# 并把 sha256 记入 core/models/SHA256SUMS
```

## 4.6 systemd（推荐）

`/etc/systemd/system/voice-cloud.service`：

```ini
[Unit]
Description=Voice Companion Cloud Backend
After=network.target chromadb.service

[Service]
Type=simple
WorkingDirectory=/opt/voice-companion/core/cloud
Environment=JAVA_HOME=/usr/lib/jvm/java-21-openjdk
Environment=VOICE_UPLINK_TOKEN=<生产接入凭据>
Environment=VOICE_LLM_BASE_URL=https://your-llm-gateway.example.com/v1
Environment=VOICE_LLM_API_KEY=<key>
ExecStart=/usr/bin/java -jar /opt/voice-companion/core/cloud/target/voice-cloud-0.0.1-SNAPSHOT.jar
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now voice-cloud
systemctl status voice-cloud
journalctl -u voice-cloud -f
```

## 4.7 设备侧连真实服务器

设备上把上行地址改成生产地址：

```
wss://voice.example.com:8080/voice/uplink
```

> **用 `wss://` 而不是 `ws://`**：生产环境必须走 TLS，
> 否则接入凭据（`Authorization: Bearer`）在网络上**明文传输**。
> 反向代理需要支持 WebSocket 升级（`Upgrade` / `Connection` 头）。

## 4.8 ★ 生产部署前的待办

**当前形态不能直接上生产。** 至少要完成：

| 项 | 依据 |
|---|---|
| 云端鉴权（任何能连到端口的客户端都能建会话） | `known-limitations.md` 2.1 |
| 下行语音下发（当前机器人不回话） | 2.6 |
| 会话状态外置（Redis）+ 一致性哈希环 | 2.2 |
| 心跳超时扫描的定时器 | 2.4 |
| 真实模型实测数据替换估算值 | 2.11 |
| 评测门禁接入 CI | OpenSpec 任务 10.4 |
| ADR 补充部署相关决策（副本数、探针、日志采集） | `docs/adr/README.md` |
| **TLS 与反向代理** | 本手册 4.7 |

---

# 第 5 章：日常运维

## 5.1 常用命令

| 目的 | 命令 |
|---|---|
| 起全部 | `powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1` |
| 停全部 | `powershell -ExecutionPolicy Bypass -File core\scripts\stop.ps1` |
| Chroma 状态 | `powershell -ExecutionPolicy Bypass -File core\scripts\chroma.ps1 status` |
| 跑评测 | `powershell -ExecutionPolicy Bypass -File core\scripts\eval.ps1` |
| 跑端到端 | `powershell -ExecutionPolicy Bypass -File core\scripts\e2e.ps1` |
| 协议一致性校验 | `powershell -ExecutionPolicy Bypass -File core\scripts\validate-protocol.ps1` |
| 端侧测试 | `F:\tools\python313\python.exe -m pytest core/tests -q` |
| 云端测试 | `cd core\cloud; mvn -o test` |

## 5.2 日志

| 日志 | 位置 | 内容 |
|---|---|---|
| 云端后端 | `core/cloud/logs/backend.out.log` | Spring Boot 全量输出 |
| 云端错误 | `core/cloud/logs/backend.err.log` | 标准错误流 |
| Chroma | `data/chroma/chroma.stdout.log` | 服务端请求日志 |
| 端侧模拟端 | 控制台 | 通过 `logging` 模块输出 |

> **排查云端问题时第一件事**：看 `core/cloud/logs/backend.out.log`。
> `start.ps1` 以隐藏窗口 + 重定向方式启动后端，
> **日志不落盘就完全看不到后端的任何状态**。

## 5.3 健康检查

| 检查项 | 地址 | 期望 | 检查时机 |
|---|---|---|---|
| ChromaDB | `http://127.0.0.1:8765/api/v2/version` | HTTP 200 | `start.ps1` 自动等待 |
| 云端后端 | `http://127.0.0.1:8080/api/health` | `{"status":"UP"}` | `start.ps1` 自动等待 |
| 上行通道 | `ws://127.0.0.1:8080/voice/uplink` | 连接成功 | 端侧连接时验证 |

> ⚠️ **`/api/health` 只检查进程存活**，不检查 Chroma 连通性 ——
> Chroma 挂了后端仍会报 UP。需要更严格的探针时应新增端点。
> 这是生产部署前的一项待办。

## 5.4 数据备份

需要备份的只有 Chroma 数据目录（长期记忆）：

```bash
# 停 Chroma 后备份（避免写入中的文件损坏）
systemctl stop chromadb
tar czf voice-chroma-$(date +%F).tar.gz /opt/voice-companion/data/chroma
systemctl start chromadb
```

**模型不需要备份**（可重新下载，且有 sha256 校验）。

---

# 第 6 章：排障手册

## 6.1 按现象定位

| 现象 | 先看 | 常见原因 |
|---|---|---|
| `start.ps1` 报 Chroma 未就绪 | `chroma.ps1 status` | 8765 被占用；`data/chroma` 权限 |
| `start.ps1` 报后端未就绪 | `core/cloud/logs/backend.out.log` | JDK 不是 21；Maven 仓库路径；Chroma 没起 |
| 端侧报"上行链路失败" | 后端日志 | 8080 没起；后端已崩 |
| 设备连上了但没回复 | 后端日志 | `ownerKey` 缺失；`text` 字段缺失 |
| **回复总是慢一轮** | 设备端代码 | 记忆写入与回复的**顺序**颠倒了 |
| 跨用户能读到别人的记忆 | 设备端代码 | `ownerKey` 相同或缺失 |
| 偶发丢字（只在长短句时出现） | 固件 | **帧长不是固定 20ms**（约束 1） |
| 打断后说的话被忘掉 | 固件 | 打断时把**已识别文本**也丢了（约束 3） |
| 设备重连后上下文全丢 | 固件 | 重连时 `sessionId` 变了，或序号从 0 重来 |
| 端侧识别"识别不可信" | — | 正常：模拟端用脚本识别器 |
| 端侧报协议校验失败 | 后端日志 | 两侧 schema 版本不一致 → 跑 `validate-protocol.ps1` |
| 会话注册了但没回收 | 后端日志 | 心跳超时扫描未实现（2.4） |
| 评测脚本"卡住不动" | 端口占用 | 嵌入服务实例没回收（2.18） |
| **PowerShell 脚本报语法错误** | 文件头 | **文件少了 UTF-8 BOM**（见 6.3） |
| 端侧 ASR 准确率暴跌到接近 0 | 评测报告 | 并发跑评测导致 TTS 音频互相覆盖（见 6.4） |

## 6.2 协议不一致的排查

**两侧判定分歧是最难查的一类问题。先跑协议校验**：

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\validate-protocol.ps1
```

- 校验**通过**但线上不一致 → 两侧收到的**字节**不同（编码、截断、大小写）
- 校验**失败** → schema 与样例不一致，按输出逐条修

## 6.3 ★ `.ps1` 文件必须带 UTF-8 BOM

**症状**：

```
行 71: Unexpected token '鐨勭矖绛涳級銆?' in expression or statement.
行 466: Unexpected token '}' in expression or statement.
```

**根因**：Windows PowerShell 5.1 读取**无 BOM** 的 `.ps1` 时，
按系统 ANSI 代码页（中文机器上是 GBK）解码，而不是 UTF-8。
中文注释被解成乱码，乱码里的引号让**整个脚本语法崩溃**。

**这个报错极具误导性** —— 它指向"某个中文 token"，
真正原因却是"文件少了 3 个字节"。

**修法**：文件开头写回 `EF BB BF` 三字节。
守门测试已经内置：`core/tests/scripts/test_powershell_scripts.py`
用 PowerShell 解析器**只查语法不执行**，逐个脚本验证 BOM 与语法。

> 这是**工具链约定，不是编码污染**。
> Python 源码、C 源码都不需要 BOM（且不应有），但 `.ps1` 需要。

## 6.4 ★ 端侧评测准确率暴跌到接近 0

**症状**：报告里 clean 准确率 28.6%、CER 0.714，而单独跑是 85.7%、CER 0.014。

**根因**：**并发跑评测**。TTS 合成的临时文件名曾经是固定的，
多个进程并发时后一个的写入覆盖前一个还没读完的 → 读到半截音频 → 识别全空。

**已修**：临时文件名现在带进程号 + 线程号 + 递增计数，合成完立即删除。

**如果你还遇到**：确认没有并行跑两个端侧评测。

## 6.5 端侧 ASR 在真机上的表现

**端侧 ASR 在 Cortex-M 上的延迟未验证**（见 3.5）。
如果你在真机上跑 ASR，延迟可能远超 PC 端的预期 ——
这需要实测，不是靠推断。

---

# 附录 A：协议速查

## A.1 上行消息一览

| 消息 | schema | 何时发 | 必填字段 |
|---|---|---|---|
| 会话开始 | `session` | 连接建立后**立即** | `sessionId`, `type` |
| 音频帧 | `audio-frame` | 每 20ms | `sessionId`, `sequence`, `timestampMs`, `sampleRate`, `payloadBase64` |
| 意图报告 | `intent-report` | 每说完一句 | `sessionId`, `sequence`, `intent`, `confidence`, `handledLocally` |
| 心跳 | `session` | 定期 | `sessionId`, `type` |
| 会话结束 | `session` | 结束时 | `sessionId`, `type`, `reason` |

## A.2 字段名清单（固件常量对应）

**上行**（设备 → 云端）：

| 字段 | 固件常量 | 说明 |
|---|---|---|
| `sessionId` | `VC_SESSION_ID` | 协议会话标识。**重连时必须保持不变** |
| `sequence` | `VC_SEQUENCE` | 上行消息序号，与音频帧共用同一序号空间，连续递增 |
| `timestampMs` | `VC_TIMESTAMP_MS` | 会话内相对毫秒偏移 |
| `ownerKey` | `VC_OWNER_KEY` | 会话归属的用户标识。★ 云端据此绑定记忆作用域 |
| `intent` | `VC_INTENT` | 意图标识，未知取 `"unknown"` |
| `confidence` | `VC_CONFIDENCE` | 0~1 |
| `handledLocally` | `VC_HANDLED_LOCALLY` | 该意图是否已在端侧执行 |
| `text` | `VC_TEXT` | ★ 端侧识别出的用户原话 |
| `slots` | —（固件用结构体拼装） | 意图参数 |
| `reason` | `VC_REASON` | 结束原因 |
| `type` | `VC_TYPE` | 会话状态：`begin` / `keepalive` / `end` |
| `audioFormat` | `VC_AUDIO_FORMAT` | 音频格式协商对象 |
| `sampleRate` | `VC_SAMPLE_RATE` | 采样率 |
| `channels` | `VC_CHANNELS` | 声道数 |
| `bitDepth` | `VC_BIT_DEPTH` | 每采样点位数 |
| `encoding` | `VC_ENCODING` | 编码方式 |
| `frameDurationMs` | `VC_FRAME_DURATION_MS` | 帧时长 |
| `opusBitRate` | `VC_OPUS_BIT_RATE` | Opus 码率（`encoding=OPUS` 时必填） |
| `payloadBase64` | `VC_PAYLOAD_BASE64` | 音频负载 |
| `isFinalPartial` | `VC_IS_FINAL_PARTIAL` | 半帧补齐后的尾帧标记 |
| `level` | `VC_LEVEL` | 降级档位 |
| `direction` | `VC_DIRECTION` | 控制通道方向 |
| `payload` | `VC_PAYLOAD` | 控制通道负载 |
| `payloadBytes` | `VC_PAYLOAD_BYTES` | 控制通道负载长度 |

**下行**（云端 → 设备）：

| 字段 | 固件常量 | 说明 |
|---|---|---|
| `sessionId` | `VC_SESSION_ID` | 与上行一致 |
| `text` | `VC_TEXT` | 回复正文 |
| `emotion` | `VC_EMOTION` | 情感标签，取值见固定集合 |
| `citations` | `VC_CITATIONS` | 引用的记忆标识数组；**不透明 UUID**，不要解析格式 |
| `isFirst` | `VC_IS_FIRST` | 语音分片首片标记 |
| `isLast` | `VC_IS_LAST` | 语音分片末片标记 |

> ★ **下行 `text-reply` 没有 `intent` 字段**（schema 是 `additionalProperties: false`）。
> 要按意图区分处理，设备得自己在端侧记住。

## A.3 硬约束速查

| 约束 | 值 | 违反后果 |
|---|---|---|
| 帧长 | 固定 20ms | 偶发丢字 |
| 采样率 | 16000（默认） | 音质与识别率下降 |
| 声道 | 单声道 | 协议拒绝 |
| 位深 | 16 bit | 协议拒绝 |
| 序号 | 连续递增，重连续传 | 无法判断丢帧还是重传 |
| `sessionId` | 重连保持不变 | 被当作新会话 |
| `text` | 必带 | 记忆写不进去 |
| `ownerKey` | 必带 | 跨用户隔离失效（**且不报错**） |
| 状态机 | 六态，与 PC 侧一致 | 停在不存在的状态上 |

---

# 附录 B：命令速查

## B.1 服务

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1                    # 起全部
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1 -SkipChroma        # 只起后端
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1 -SkipBackend       # 只起 Chroma
powershell -ExecutionPolicy Bypass -File core\scripts\stop.ps1                     # 停全部
powershell -ExecutionPolicy Bypass -File core\scripts\chroma.ps1 start            # 只起 Chroma
powershell -ExecutionPolicy Bypass -File core\scripts\chroma.ps1 status           # Chroma 状态
```

## B.2 端侧

```powershell
F:\tools\python313\python.exe -m core.edge.simulator --url ws://127.0.0.1:8080/voice/uplink
F:\tools\python313\python.exe -m core.edge.simulator --url ws://127.0.0.1:8080/voice/uplink --owner user-42 --rounds 3
```

## B.3 评测

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\eval.ps1                     # 完整评测
powershell -ExecutionPolicy Bypass -File core\scripts\e2e.ps1                      # 端到端
powershell -ExecutionPolicy Bypass -File core\scripts\validate-protocol.ps1       # 协议校验
F:\tools\python313\python.exe -m core.eval.edge_eval --report core/eval-edge-report.md   # 只跑端侧 ASR
```

## B.4 模型与包

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\fetch-models.ps1 -Target all
F:\tools\python313\python.exe device-ref/model-package/package_model.py --gen-key keys/device_sign_key.pem
F:\tools\python313\python.exe device-ref/model-package/package_model.py --manifest build/manifest.json --out dist/companion_model_pkg --sign-key keys/device_sign_key.pem
F:\tools\python313\python.exe device-ref/ota/ota_update.py --image dist/firmware-2.5.0.bin --device COM3 --dry-run
```

## B.5 测试

```powershell
F:\tools\python313\python.exe -m pytest core/tests -q                    # 端侧全部
F:\tools\python313\python.exe -m pytest core/tests/device_ref -q         # 固件契约
F:\tools\python313\python.exe -m pytest core/tests/scripts -q            # PowerShell 脚本守门
cd core\cloud; mvn -o test                                              # 云端 354 项
```

---

## 附：读完还该看哪几份

| 文档 | 什么时候看 |
|---|---|
| `docs/known-limitations.md` | **动手前必读** —— 每一条限制都有依据和验证方式 |
| `device-ref/README.md` | 接真机时 —— 行为契约与未验证项清单 |
| `docs/deployment.md` | 部署时 —— 环境变量、端口、启动顺序的完整清单 |
| `docs/secondary-development.md` | 改代码时 —— 扩展点在哪 |
| `docs/interface-contract/README.md` | 对接公司内网系统时 |
| `docs/adr/README.md` | 想知道"为什么这么设计"时 |
| `docs/real-recording-handover.md` | 真人录音接入的交接单 |
