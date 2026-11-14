# 端云接口契约

> 本文档是端侧（Python）与云端（Java）之间的**唯一协议事实来源**。
> 机器可读的权威定义是 `core/protocol/schema/*.schema.json`；
> 本文档解释语义、约束与演进规则。
>
> **两者不一致时以 schema 为准**，并立即修正本文档。

## 目录

| 消息 | Schema | 方向 | 传输通道 |
|---|---|---|---|
| 音频帧 | `audio-frame.schema.json` | 端 → 云 | 上行 WebSocket |
| 语音片段 | `voice-chunk.schema.json` | 云 → 端 | 下行 WebSocket |
| 文本回复 | `text-reply.schema.json` | 云 → 端 | 下行 WebSocket |
| 会话生命周期 | `session.schema.json` | 双向 | 上行 WebSocket |
| 音频格式协商 | `audio-negotiation.schema.json` | 双向 | 会话建立时 |
| 降级档位 | `degrade-level.schema.json` | 端 → 云 | 上行 WebSocket |
| 控制通道 | `control-channel.schema.json` | 双向 | MQTT |
| 意图报告 | `intent-report.schema.json` | 端 → 云 | 上行 WebSocket |

## 通用约定

- **JSON 编码**：UTF-8，不带 BOM。
- **字段命名**：`camelCase`。Python 侧用同名的 snake_case 变量，通过显式转换映射。
- **未知字段**：所有 schema 均设 `additionalProperties: false`。
  这是**有意的**：多出一个字段说明两侧版本已经错位，静默忽略会让错位无法被发现。
  因此新增字段必须同时升级两侧，并在本文件登记。
- **必填性**：必填字段由 schema 的 `required` 定义。缺失即协议违规，接收方应拒绝该消息。
- **时间戳**：`timestampMs` 是**会话内相对毫秒偏移**，不是 Unix 时间戳。
  用相对值让两端不依赖时钟同步 —— 设备端时钟不可信。

## 消息详述

### 1. 音频帧（`audio-frame`）

端侧上行的单帧音频。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sessionId` | string | 是 | 会话标识。**重连时保持不变**，避免被当作新会话而丢掉上下文。 |
| `sequence` | integer | 是 | 帧序号，从 0 起连续递增。重连后从断点续传，不重发已确认的帧。 |
| `timestampMs` | integer | 是 | 该帧首采样点的会话内相对毫秒偏移。 |
| `sampleRate` | integer | 是 | 采样率，取值 `16000` / `24000` / `48000`。必须与协商结果一致。 |
| `channels` | integer | 否 | 声道数，当前协议只支持 `1`。 |
| `payloadBase64` | string | 是 | 负载的 base64 文本。 |
| `isFinalPartial` | boolean | 否 | 标记该帧为补齐后的尾帧。 |

**帧长约定**：帧长固定 20 毫秒。16kHz 下即 320 采样点 / 640 字节。
最后不足一帧的部分**必须补齐**并置 `isFinalPartial=true` 上行 ——
不允许把半帧当完整帧上行，云端按帧长切分时会错位。

**为什么 `sampleRate` 是必填**：云端要校验帧格式与协商结果是否一致。
若帧里不带格式，云端只能"相信"协商结果，无法发现端侧实际用了别的采样率。

### 2. 语音片段（`voice-chunk`）

云端下发的流式语音片段。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sessionId` | string | 是 | 会话标识。 |
| `sequence` | integer | 是 | 片段序号，连续递增。 |
| `timestampMs` | integer | 否 | 会话内相对毫秒偏移。 |
| `payloadBase64` | string | 是 | 音频负载，base64。**不可为空串**。 |
| `isFirst` | boolean | 否 | 首片段标记。用于端侧起播与首包延迟测量。 |
| `isLast` | boolean | 否 | 末片段标记。 |
| `emotion` | string | 否 | 情感标签，取值集合与 `text-reply` 一致。 |

**首包延迟的测量基准**：端侧从发出最后一条上行消息到收到 `isFirst=true` 的片段。
`isFirst` 必须打在**第一个**片段上，否则端侧无法区分首包与中间包。

### 3. 文本回复（`text-reply`）

设备关闭语音输出时使用。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sessionId` | string | 是 | 会话标识。 |
| `text` | string | 是 | 回复正文，不可为空串。 |
| `emotion` | string | 是 | 情感标签。 |
| `citations` | array\<string\> | 否 | 回复所引用的记忆或知识片段标识。 |

**情感标签取值**：`neutral` / `joy` / `sadness` / `anger` / `fear` / `surprise` /
`tenderness` / `encouragement`。

**`emotion` 与文本同时产出**，不需要额外一次模型调用 —— 标签是生成过程的副产品。

**`citations` 的语义**：只允许引用记忆或检索结果中的标识。
**没有来源就不许出现具体人名、地点、日期** —— 这是事实性约束的协议层落点。

### 4. 会话生命周期（`session`）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sessionId` | string | 是 | 会话标识。 |
| `type` | string | 是 | `begin` / `keepalive` / `end`。 |
| `reason` | string | 条件 | `type=end` 时**必填**。 |
| `timestampMs` | integer | 否 | 会话内相对毫秒偏移。 |
| `audioFormat` | object | 否 | `type=begin` 时携带协商结果。 |

**`type=end` 必须带 `reason`**：没有原因就无法区分"用户主动结束"与"异常断开"，
运维侧看不到会话为何消失。

**心跳不隐式创建会话**：只有走过 `begin` 的会话才是活会话。
让心跳隐式注册会让一个乱发的 `keepalive` 伪造出会话，占住处理单元。

### 5. 音频格式协商（`audio-negotiation`）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sampleRate` | integer | 是 | `16000` / `24000` / `48000`。 |
| `channels` | integer | 是 | 当前只支持 `1`。 |
| `bitDepth` | integer | 是 | 当前只支持 `16`。 |
| `encoding` | string | 是 | `PCM_S16LE` / `OPUS`。 |
| `frameDurationMs` | integer | 是 | 固定 `20`。 |
| `opusBitRate` | integer | 条件 | `encoding=OPUS` 时**必填**，取值 `6000`–`510000`。 |

**默认值**：`16000` / `1` / `16` / `PCM_S16LE` / `20`。

**请求可以只声明差异项**：端侧只发 `{"encoding": "OPUS"}` 也合法，
接收方先与默认值合并再校验。这样弱网切换到 Opus 时不需要重发完整格式。

**协商失败拒绝连接**，不接受"降级到别的格式凑合用" —— 双方对格式的认知
必须一致，否则每一帧都要靠猜。

### 6. 降级档位（`degrade-level`）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `level` | string | 是 | `NORMAL` / `DEGRADED_NETWORK` / `OFFLINE` / `MINIMAL`。 |
| `reason` | string | 否 | 降级原因，便于排查。 |
| `timestampMs` | integer | 否 | 会话内相对毫秒偏移。 |

**档位语义**：

| 档位 | 含义 | 端侧行为 |
|---|---|---|
| `NORMAL` | 一切正常 | 全部能力可用 |
| `DEGRADED_NETWORK` | 网络质量下降但可用 | 短响应、优先本地执行 |
| `OFFLINE` | 云端不可达 | 完全本地，长响应 |
| `MINIMAL` | 最低能力 | 只播固定话术 |

**降级与回升都逐级进行**，且判定**不依赖云端心跳** —— 等心跳确认的降级会让
断网时端侧仍在做无谓的上行重试。

### 7. 控制通道（`control-channel`）

走 MQTT，与音频会话**分离**：控制通道故障不得导致音频会话中断。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sessionId` | string | 是 | 会话标识。 |
| `direction` | string | 是 | `up` / `down`。 |
| `type` | string | 是 | 见下表。 |
| `payload` | object | 否 | 载荷内容，随 `type` 而定。 |
| `payloadBytes` | integer | 条件 | 载荷字节数。`type=profileDelta` 时**必填**，上限 `8192`。 |

| `type` | 方向 | 含义 |
|---|---|---|
| `statusReport` | 上行 | 设备状态上报 |
| `metricReport` | 上行 | 指标上报 |
| `faultReport` | 上行 | 故障上报 |
| `sessionEvent` | 上行 | 会话事件 |
| `configPush` | 下行 | 配置下发 |
| `profileDelta` | 下行 | 用户画像增量 |
| `versionNotice` | 下行 | 版本通知 |
| `diagnosticCommand` | 下行 | 远程诊断命令 |

**画像增量超上限的处理是"拒绝"而不是"截断"**：
截断后的画像会让用户模型处于"半新半旧"的状态，且无法察觉 ——
比明确失败更难排查。

### 8. 意图报告（`intent-report`）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sessionId` | string | 是 | 会话标识。 |
| `sequence` | integer | 是 | 上行消息序号，与音频帧**共用同一序号空间**，连续递增。 |
| `intent` | string | 是 | 意图标识。未知意图取 `unknown`。 |
| `confidence` | number | 是 | 取值区间 `[0, 1]`。 |
| `handledLocally` | boolean | 是 | 该意图是否已在端侧执行。 |
| `slots` | object | 否 | 意图参数，键值均为字符串。 |

**端侧只负责分类，不负责执行长尾意图**：`handledLocally=false` 时由云端执行。

**`confidence` 必须如实上报**：云端据此决定是直接采信还是重新判定。
端侧把低置信度报成高置信度，云端就再没有机会纠正。

## 版本与兼容性

### 兼容性规则

| 变更 | 是否兼容 | 要求 |
|---|---|---|
| 新增**可选**字段 | 兼容 | 两侧同时升级后启用该字段 |
| 新增必填字段 | **不兼容** | 必须引入新的 schema 版本 |
| 删除字段 | **不兼容** | 同上 |
| 收紧取值范围 | **不兼容** | 同上 |
| 放宽取值范围 | 兼容 | 直接改 schema |
| 新增消息类型 | 兼容 | 接收方忽略未知 `type` |

### 版本标识

当前协议版本：`v1`（对应 `openspec/changes/add-voice-companion-job-portfolio`）。

**版本号不在消息体里** —— 靠 schema 文件名与 `$id` 标识。
这样版本升级不需要改动每一处消息体，改的是 schema 文件。

### 演进流程

1. 改 `core/protocol/schema/*.schema.json`（**唯一事实来源**）；
2. 在共享样例集 `core/cloud/src/test/resources/protocol-samples/samples.json`
   增删样例，标注 `valid` 与说明；
3. 更新 Python 侧（`core/protocol/validator.py` 走统一入口，无需改动）与
   Java 侧（`ProtocolValidator` 按名称加载，也无需改动）；
4. 跑 `core/scripts/validate-protocol.ps1` 确认两侧判定一致；
5. 更新本文档的对应小节。

**校验脚本是契约的守门人**：schema 与样例不一致时，
两侧运行时会因判定分歧而行为不一致 —— 那是最难查的一类问题。

## 校验方式

```powershell
# 校验全部 schema 与样例
powershell -ExecutionPolicy Bypass -File core/scripts/validate-protocol.ps1

# 只做 schema 自检
powershell -ExecutionPolicy Bypass -File core/scripts/validate-protocol.ps1 -SchemaOnly
```

跨语言一致性由两侧共用同一批样例保证：

- Python：`core/tests/protocol/test_cross_language_consistency.py`
- Java：`core/cloud/src/test/java/com/company/bj/voice/cloud/protocol/ProtocolValidatorTest.java`
